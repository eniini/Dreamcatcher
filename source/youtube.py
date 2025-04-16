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
async def get_channel_name(channel_id: str) -> str:
	"""
	Fetches the public channel name.
	"""
	global youtubeClient

	if not channel_id or not channel_id.startswith("UC"):
		main.logger.error(f"Invalid channel ID: {channel_id}.\n")
		return None

	try:
		request = youtubeClient.channels().list(
			part="snippet",
			id=channel_id
		)
		response = request.execute()
		if response["items"]:
			return response["items"][0]["snippet"]["title"]
	except Exception as e:
		main.logger.error(f"Error fetching channel name: {e}")
	return None

async def get_channel_handle(channel_id: str) -> str:
	"""
	Fetches the public channel handle (youtube.com/@channelhandle).
	"""
	global youtubeClient

	if not channel_id or not channel_id.startswith("UC"):
		main.logger.error(f"Invalid channel ID: {channel_id}.\n")
		return None

	try:
		request = youtubeClient.channels().list(
			part="snippet, brandingSettings",
			id=channel_id
		)
		response = request.execute()
		# Try to get handle from brandingSettings
		if response["items"]:
			item = response["items"][0]
			handle = None
			branding = item.get("brandingSettings", {}).get("channel", {})
			if "handle" in branding:
				handle = branding["handle"]
			elif "customUrl" in item["snippet"] and item["snippet"]["customUrl"].startswith("@"):
				handle = item["snippet"]["customUrl"]
			return handle

	except Exception as e:
		main.logger.error(f"Error fetching channel handle: {e}")
	return None

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

#
#	Main YT API loop
#

@reconnect_api_with_backoff()
async def check_for_youtube_activities() -> None:
	global youtubeClient

	main.logger.info(f"Starting the Youtube activity sharing task...\n")
	while True:
		try:
			# Fetch all YouTube subscriptions from the database
			youtube_subscriptions = sql.get_all_social_media_subscriptions_for_platform("YouTube")

			for channel_id in youtube_subscriptions:

				internal_id = sql.get_id_for_channel_url(channel_id)
				channel_name = sql.get_channel_name(internal_id)

				try:
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

						# Handle uploads (fetch video ID if necessary)
						video_id = None
						phase_suffix = ""

						if activity_type == "upload":
							video_id = await get_latest_video_from_playlist(channel_id)
							if video_id is None:
								main.logger.error(f"Failed to fetch video ID for activity {activity_id} from playlist!\n")
								continue

							# Check if the video is a livestream (scheduled or live)
							video_response = youtubeClient.videos().list(
								part='snippet, liveStreamingDetails',
								id=video_id
							).execute()

							if video_response["items"]:
								video_item = video_response["items"][0]
								live_status = video_item["snippet"].get("liveBroadcastContent", "none")

								# determine notification type based on live status
								if live_status == "upcoming":
										activity_type = "liveStreamSchedule"
										phase_suffix = "scheduled"
								elif live_status == "live":
										activity_type = "liveStreamNow"
										phase_suffix = "live"
								else:
									activity_type = "upload"

						# Check if the activity is already notified (factoring in the state of the livestream)
						virtual_id = activity_id + phase_suffix
						if sql.check_post_match(internal_id, virtual_id):
							main.logger.info(f"Activity {activity_id} already notified for channel {channel_name}.\n")
							continue

						# Save the activity to the database
						sql.update_latest_post(internal_id, virtual_id, title)

						# Notify Discord channels subscribed to this YouTube channel
						discord_channels = sql.get_discord_channels_for_social_channel(internal_id)

						for discord_channel in discord_channels:
							main.logger.info(f"Notifying Discord channel {discord_channel} about new activity...\n")
							await bot.notify_youtube_activity(
								discord_channel,
								activity_type,
								channel_name,
								video_id)

				except Exception as e:
					main.logger.error(f"Error processing activities for channel {channel_id}: {e}\n")
		except Exception as e:
			main.logger.error(f"Error fetching YouTube subscriptions or processing activities: {e}\n")

		# Wait for the configured interval before checking again
		await asyncio.sleep(wait_time)
