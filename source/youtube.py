import asyncio
from googleapiclient.discovery import build

import main
import bot
import sql
import reconnect_decorator as reconnect_api_with_backoff

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

#
#	Youtube API functions, video/livestream/post fetching
#

@reconnect_api_with_backoff(initialize_youtube_client, "YouTube")
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

@reconnect_api_with_backoff(initialize_youtube_client, "YouTube")
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
