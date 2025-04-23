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
# edit: the video/livestream details are fetched in a batch request, so the cost is 1 unit for 50 video IDs.
# this means that the soft cap for YT channels to monitor is roughly 300 channels.

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
	Fetches the public channel name from Youtube API. Used by bot command to verify user input channel ID.
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

#
#	Main YT API loop
#

@reconnect_api_with_backoff()
async def check_for_youtube_activities() -> None:
	global youtubeClient

	main.logger.info(f"Starting the Youtube activity sharing task...\n")
	while True:
		try:
			# Fetch all Youtube subscriptions from the database
			youtube_subscriptions = sql.get_all_social_media_subscriptions_for_platform("YouTube")

			pending_notifications = []
			video_ids_to_check = []

			for channel_id in youtube_subscriptions:
				try:
					activity_info = fetch_latest_youtube_activity(channel_id)
					if activity_info:
						pending_notifications.append(activity_info)
						if activity_info["video_id"]:
							video_ids_to_check.append(activity_info["video_id"])
				except Exception as e:
					main.logger.error(f"Error processing activities for channel {channel_id}: {e}\n")
			
			video_metadata_map = batch_fetch_video_metadata(video_ids_to_check)

			await process_youtube_notifications(pending_notifications, video_metadata_map)
		
		except Exception as e:
			main.logger.error(f"Error inside Youtube activity loop: {e}\n")

		await asyncio.sleep(wait_time)

def fetch_latest_youtube_activity(channel_id: str) -> dict | None:
	"""
	Fetches all the necessary information about the latest activity of a given channel,
	bundled together with the channel name and internal ID.
	"""
	internal_id = sql.get_id_for_channel_url(channel_id)
	channel_name = sql.get_channel_name(internal_id)

	response = youtubeClient.activities().list(
		part='snippet, contentDetails',
		channelId=channel_id,
		maxResults=1
	).execute()

	for item in response.get('items', []):
		activity_type = item['snippet']['type']
		activity_id = item['id']
		title = item['snippet']['title']
		video_id = item.get("contentDetails", {}).get("upload", {}).get("videoId")

		if activity_type != "upload" or not video_id:
			return None

		return {
			"internal_id": internal_id,
			"channel_name": channel_name,
			"activity_id": activity_id,
			"title": title,
			"activity_type": activity_type,
			"video_id": video_id,
			"discord_channels": sql.get_discord_channels_for_social_channel(internal_id)
		}

	return None

def batch_fetch_video_metadata(video_ids: set[str]) -> dict:
	"""
	Fetches metadata for a batch of video IDs. Input a set to avoid duplicates, is converted to a list for YT API call.
	Returns a dictionary mapping video IDs to their queried metadata (livestream/video details).
	The API call is managed in batches of 50 video IDs to avoid exceeding the API quota.
	"""
	video_metadata_map = {}
	video_ids = list(video_ids)

	for i in range(0, len(video_ids), 50):
		batch_video_ids = video_ids[i:i + 50]
		response = youtubeClient.videos().list(
			part='snippet, liveStreamingDetails',
			id=','.join(batch_video_ids)
		).execute()

		for item in response.get('items', []):
			video_metadata_map[item['id']] = item

	return video_metadata_map

async def process_youtube_notifications(pending_notifications: list[dict], video_metadata_map: dict) -> None:
	"""
	Process the batch of activity, updating database and notifying Discord channels if new activity is found.
	"""
	for item in pending_notifications:
		video_id = item["video_id"]
		video_data = video_metadata_map.get(video_id)

		phase_suffix = ""
		if video_data:
			live_status = video_data["snippet"].get("liveBroadcastContent", "none")

			# determine notification type based on live status
			if live_status == "upcoming":
				item["activity_type"] = "liveStreamSchedule"
				phase_suffix = "scheduled"
			elif live_status == "live":
				item["activity_type"] = "liveStreamNow"
				phase_suffix = "live"
			else:
				# check if we already notified this video as a livestream
				previously_notified_id = item["activity_id"] + "live"
				if sql.check_post_match(item["internal_id"], previously_notified_id):
					# livestream of this was already notified, skip notifying as upload
					continue
				# otherwise notify
				item["activity_type"] = "upload"
		
		virtual_id = item["activity_id"] + phase_suffix
		if sql.check_post_match(item["internal_id"], virtual_id):
			continue

		sql.update_latest_post(item["internal_id"], virtual_id, item["title"])

		for discord_channel in item["discord_channels"]:
			await bot.notify_youtube_activity(
				discord_channel,
				item["activity_type"],
				item["channel_name"],
				item["video_id"])

# @reconnect_api_with_backoff()
# async def check_for_youtube_activities() -> None:
# 	global youtubeClient
# 
# 	main.logger.info(f"Starting the Youtube activity sharing task...\n")
# 	while True:
# 		try:
# 			# Fetch all YouTube subscriptions from the database
# 			youtube_subscriptions = sql.get_all_social_media_subscriptions_for_platform("YouTube")
# 
# 			for channel_id in youtube_subscriptions:
# 
# 				internal_id = sql.get_id_for_channel_url(channel_id)
# 				channel_name = sql.get_channel_name(internal_id)
# 
# 				try:
# 					# Fetch the YouTube channel's activities
# 					request = youtubeClient.activities().list(
# 						part='snippet',
# 						channelId=channel_id,
# 						maxResults=1
# 					)
# 					response = request.execute()
# 					for item in response.get('items', []):
# 						activity_id = item['id']
# 						activity_type = item['snippet']['type']
# 						title = item['snippet']['title']
# 
# 						# Handle uploads (fetch video ID if necessary)
# 						video_id = None
# 						phase_suffix = ""
# 
# 						if activity_type == "upload":
# 							video_id = item.get("contentDetails", {}).get("upload", {}).get("videoId")
# 							#video_id = await get_latest_video_from_playlist(channel_id)
# 							if video_id is None:
# 								main.logger.error(f"Failed to fetch video ID for activity {activity_id} from playlist!\n")
# 								continue
# 
# 							# Check if the video is a livestream (scheduled or live)
# 							video_response = youtubeClient.videos().list(
# 								part='snippet, liveStreamingDetails',
# 								id=video_id
# 							).execute()
# 
# 							if video_response["items"]:
# 								video_item = video_response["items"][0]
# 								live_status = video_item["snippet"].get("liveBroadcastContent", "none")
# 
# 								# determine notification type based on live status
# 								if live_status == "upcoming":
# 										activity_type = "liveStreamSchedule"
# 										phase_suffix = "scheduled"
# 								elif live_status == "live":
# 										activity_type = "liveStreamNow"
# 										phase_suffix = "live"
# 								else:
# 									activity_type = "upload"
# 
# 						# Check if the activity is already notified (factoring in the state of the livestream)
# 						virtual_id = activity_id + phase_suffix
# 						if sql.check_post_match(internal_id, virtual_id):
# 							#main.logger.info(f"Activity {activity_id} already notified for channel {channel_name}.\n")
# 							continue
# 
# 						# Save the activity to the database
# 						sql.update_latest_post(internal_id, virtual_id, title)
# 
# 						# Notify Discord channels subscribed to this YouTube channel
# 						discord_channels = sql.get_discord_channels_for_social_channel(internal_id)
# 
# 						for discord_channel in discord_channels:
# 							main.logger.info(f"Notifying Discord channel {discord_channel} about new activity...\n")
# 							await bot.notify_youtube_activity(
# 								discord_channel,
# 								activity_type,
# 								channel_name,
# 								video_id)
# 
# 				except Exception as e:
# 					main.logger.error(f"Error processing activities for channel {channel_id}: {e}\n")
# 		except Exception as e:
# 			main.logger.error(f"Error fetching YouTube subscriptions or processing activities: {e}\n")
# 
# 		# Wait for the configured interval before checking again
# 		await asyncio.sleep(wait_time)
