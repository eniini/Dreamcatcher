import asyncio
import functools
import datetime
from googleapiclient.discovery import build

import main
import bot
import sql

# To note: Youtube API has a quota limit of 10,000 units per day.
# Activities.list() and PlaylistItems.list() both cost 1 unit per request.
# So for every successful new post check, 2 units are used. (1 for activities, 1 for playlistItems query for the actual video/livestream url)
# this means that optimal wait time for checking new posts varies highly based on:
# - how many posts can be expected per day,
# - how many channels are queried

wait_time = 60  # default wait time between checks, in seconds

#
#	API initialization
#

async def initialize_youtube_client():
	global youtubeClient
	global public_webhook_address
	try:
		youtubeClient = build('youtube', 'v3', developerKey=main.YOUTUBE_API_KEY)
		public_webhook_address = f"http://{main.PUBLIC_WEBHOOK_IP}:8000/youtube-webhook"
		main.logger.info(f"Youtube API initialized successfully.\n")
	except Exception as e:
		main.logger.error(f"Failed to initialize Youtube API client: {e}\n")
		raise

def reconnect_api_with_backoff(max_retries=5, base_delay=2):
	"""
	Tries to re-establish given API connection with exponential falloff.
	"""
	def decorator(api_func):
		@functools.wraps(api_func)
		async def wrapper(*args, **kwargs):
			attempt = 0
			while attempt < max_retries:
				try:
					return await api_func(*args, **kwargs)
				except Exception as e:
					attempt += 1
					main.logger.warning(f"Youtube API call failed! (attempt {attempt}/{max_retries}): {e}")

					if "quotaExceeded" in str(e) or "403" in str(e):
						main.logger.critical(f"Bot has exceeded Youtube API quota.")
						await bot.bot_internal_message("Bot has exceeded Youtube API quota!")
						return None
					if attempt == max_retries:
						main.logger.error(f"Max retries reached. Could not recover API connection.")
						await bot.bot_internal_message("Bot failed to connect to Youtube API after max retries...")

					wait_time = base_delay * pow(2, attempt - 1)
					main.logger.info(f"Reinitializing Youtube API client in {wait_time:.2f} seconds...")

					await asyncio.sleep(wait_time)
					# try to reconnect API
					await initialize_youtube_client()
		return wrapper
	return decorator

#
#	Youtube API functions, video/livestream/post fetching
#

@reconnect_api_with_backoff()
async def get_latest_video_from_playlist(channel_id: str) -> str:
	"""
	Fetches the latest video ID from the channel's uploads playlist.
	This is the least expensive way to check for new videos. (less Youtube API quota usage)
	Must be called in order to get the actual video URL, as activities() only returns video ID.
	"""
	global youtubeClient

	if not channel_id or not channel_id.startswith("UC"):
		main.logger.error(f"Invalid channel ID: {channel_id}.\n")
		return None

	playlist_id = channel_id.replace("UC", "UU", 1)

	try:
		request = youtubeClient.playlistItems().list(
			part="contentDetails",
			playlistId=playlist_id,
			maxResults=1
		)
		response = request.execute()
		if response["items"]:
			return response["items"][0]["contentDetails"]["videoId"]
	except Exception as e:
		main.logger.error(f"Error fetching latest video from playlist: {e}")
	return None

@reconnect_api_with_backoff()
async def check_for_youtube_activities() -> None:
	global youtubeClient

	main.logger.info(f"Starting the Youtube activity sharing task...\n")
	while True:
		try:
			# Fetch all YouTube subscriptions from the database
			youtube_subscriptions = sql.get_all_social_media_subscriptions_for_platform("YouTube")
			main.logger.info(f"Found following YouTube subscriptions: {youtube_subscriptions}\n")
			for channel_id in youtube_subscriptions:
				internal_id = sql.get_id_for_channel_url(channel_id)
				try:
					main.logger.info(f"Checking for new activities for channel {channel_id} [{internal_id}]...\n")
					# Fetch the YouTube channel's activities
					request = youtubeClient.activities().list(
						part='snippet',
						channelId=channel_id,
						maxResults=1
					)
					response = request.execute()
					for item in response.get('items', []):
						activity_id = item['id']
						activity_type = item['snippet']['type']
						title = item['snippet']['title']
						published_at = item['snippet']['publishedAt']
						post_text = item['snippet'].get('description', None)

						# Check if the activity is already notified
						if sql.check_post_match(channel_id, activity_id):
							main.logger.info(f"Activity {activity_id} already notified, skipping...\n")
							continue

						# Handle uploads (fetch video ID if necessary)
						video_id = None
						if activity_type == "upload":
							video_id = await get_latest_video_from_playlist(channel_id)
							if video_id is None:
								main.logger.error(f"Failed to fetch video ID for activity {activity_id} from playlist!\n")
								continue

						# Save the activity to the database
						sql.update_latest_post(internal_id, activity_id, title)
						main.logger.info(f"New activity found for channel {channel_id} [{internal_id}]: {activity_type} - {title} ({published_at})\n")

						# Notify Discord channels subscribed to this YouTube channel
						discord_channels = sql.get_discord_channels_for_social_channel(internal_id)

						for discord_channel in discord_channels:
							main.logger.info(f"Notifying Discord channel {discord_channel} about new activity...\n")
							await bot.notify_youtube_activity(
								discord_channel,
								activity_type,
								title,
								published_at,
								video_id,
								post_text)

				except Exception as e:
					main.logger.error(f"Error processing activities for channel {channel_id}: {e}\n")
		except Exception as e:
			main.logger.error(f"Error fetching YouTube subscriptions or processing activities: {e}\n")

		# Wait for the configured interval before checking again
		await asyncio.sleep(wait_time)
