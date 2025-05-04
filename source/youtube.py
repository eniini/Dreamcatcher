import asyncio
from googleapiclient.discovery import build

import json

import main
import bot
import sql
from reconnect_decorator import reconnect_api_with_backoff

# To note: Youtube API has a quota limit of 10,000 units per day.
# Activities.list() and PlaylistItems.list() both cost 1 unit per request.
# So for every successful new post check, 2 units are used. (1 for activities, 1 for playlistItems query for the actual video/livestream url)
# edit: the video/livestream details are fetched in a batch request, so the cost is 1 unit for 50 video IDs.
# this means that the soft cap for YT channels to monitor is roughly 300 channels.

def calculate_optimal_polling_interval(quota_limit: int = 10000, quota_buffer: float = 0.05) -> int:
	"""
	Calculates the optimal polling interval (in seconds) to stay under the YouTube API daily quota.

	Args:
		channel_count (int): Number of YouTube channels being monitored.
		quota_limit (int): Total daily quota limit (default is 10,000).
		quota_buffer (float): Fractional buffer to leave unused (default 0.05 = 5%).

	Returns:
		int: Optimal number of seconds to wait between polling cycles.
	"""
	# Leave a buffer to avoid accidental overuse
	max_quota_usage = quota_limit * (1 - quota_buffer)

	# Each cycle uses 1 activity + 1 batched video call (treated as a single extra call)
	quota_per_cycle = len(sql.get_all_social_media_subscriptions_for_platform("YouTube")) + len(sql.get_all_social_media_subscriptions_for_platform("YouTube_members")) + 1

	# Max cycles per day
	max_cycles_per_day = max_quota_usage // quota_per_cycle

	# Seconds per day / cycles per day = wait time
	seconds_per_day = 24 * 60 * 60
	optimal_interval = int(seconds_per_day // max_cycles_per_day)

	return max(optimal_interval, 60)  # Minimum 60 seconds to avoid unecessary aggressive polling

#
#	API initialization
#

async def initialize_youtube_client():
	global youtubeClient
	try:
		youtubeClient = build('youtube', 'v3', developerKey=main.YOUTUBE_API_KEY)
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
		main.logger.info(f"Invalid channel ID: {channel_id}.\n")
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
		else:
			main.logger.info(f"No content found for channel ID: {channel_id}...\n")
			return None

	except Exception as e:
		main.logger.error(f"Error generating request for channel handle: {e}")
		raise

#
#	Main YT API loop
#

@reconnect_api_with_backoff(initialize_youtube_client, "YouTube")
async def check_for_youtube_activities() -> None:
	global youtubeClient

	main.logger.info(f"Starting the Youtube activity sharing task...\n")

	wait_time = calculate_optimal_polling_interval()

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
			
			video_metadata_map = batch_fetch_activity_metadata(video_ids_to_check)

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
		part="snippet, contentDetails",
		channelId=channel_id,
		maxResults=1
	).execute()

	for item in response.get("items", []):
		activity_type = item["snippet"]["type"]
		activity_id = item["id"]
		title = item["snippet"]["title"]
		video_id = item.get("contentDetails", {}).get("upload", {}).get("videoId")

		if not video_id:
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

def batch_fetch_activity_metadata(video_ids: set[str]) -> dict:
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
			part="snippet, liveStreamingDetails, status",
			id=','.join(batch_video_ids)
		).execute()

		# Prepopulate the map with unavailable videos for default values
		for vid in batch_video_ids:
			video_metadata_map[vid] = {
				"item": None,
				"status": "unavailable"}

		for item in response.get('items', []):

			vid = item['id']
			snippet = item.get("snippet", {})

			live_status = snippet.get("liveBroadcastContent", "none").lower()

			if live_status == "upcoming":
				detected_status = "liveStreamScheduled"
			elif live_status == "live":
				detected_status = "liveStreamNow"
			else:
				detected_status = "upload"
			
			video_metadata_map[vid] = {
				"item": item,
				"status": detected_status
			}
	return video_metadata_map

async def process_youtube_notifications(pending_notifications: list[dict], video_metadata_map: dict) -> None:
	"""
	Process the batch of activity, updating database and notifying Discord channels if new activity is found.
	"""
	for item in pending_notifications:
		video_id = item["video_id"]
		video_data = video_metadata_map.get(video_id, {})
		title = item["title"]
		members_only = False
		phase_suffix = ""

		if item["activity_type"] == "membersOnlyContent":
			members_only = True

		# get final status classification
		detected_status = video_data.get("status")

		# determine notification type based on live status
		if detected_status == "liveStreamScheduled":
			phase_suffix = "scheduled"
		elif detected_status == "liveStreamNow":
			phase_suffix = "live"
		else:
			# check if we already notified this video as a livestream
			previously_notified_id = item["activity_id"] + "live"
			if sql.check_post_match(item["internal_id"], previously_notified_id):
				# livestream of this was already notified, skip notifying as upload
				continue

		virtual_id = item["activity_id"] + phase_suffix
		if sql.check_post_match(item["internal_id"], virtual_id):
			continue

		sql.update_latest_post(item["internal_id"], virtual_id, title)

		main.logger.info(f"New activity detected for channel {item['channel_name']} ({item['internal_id']})")
		main.logger.info(f"Activity type: {detected_status}")
		main.logger.info(f"Video ID: {video_id}")
		main.logger.info(f"Video title: {title}")
		main.logger.info(f"members only: {members_only}")

		for discord_channel in item["discord_channels"]:
			await bot.notify_youtube_activity(
				discord_channel,
				detected_status,
				item["channel_name"],
				item["video_id"],
				members_only)

#
#	Youtube Members-Only activity loop
#

@reconnect_api_with_backoff(initialize_youtube_client, "YouTube")
async def check_for_members_only_youtube_activity() -> None:
	global youtubeClient

	main.logger.info(f"Starting the Members-Only Youtube activity sharing task...\n")

	wait_time = calculate_optimal_polling_interval()

	while True:
		try:
			youtube_subscriptions = sql.get_all_social_media_subscriptions_for_platform("YouTube_members")

			pending_notifications = []
			video_ids_to_check = []

			for channel_url in youtube_subscriptions:
				internal_id = sql.get_id_for_channel_url(channel_url, "YouTube_members")
				channel_name = sql.get_channel_name(internal_id)

				try:
					members_only_videos = fetch_latest_members_only_content(channel_url, 1)

					for video_id in members_only_videos:

						if sql.check_post_match(internal_id, video_id):
							continue  # already processed

						pending_notifications.append({
							"internal_id": internal_id,
							"channel_name": channel_name,
							"activity_id": video_id,
							"title": "(unknown title - resolving)",
							"activity_type": "membersOnlyContent",
							"video_id": video_id,
							"discord_channels": sql.get_discord_channels_for_social_channel(internal_id)
						})
						video_ids_to_check.append(video_id)

				except Exception as e:
					main.logger.error(f"Error checking members-only playlist for {channel_name}: {e}\n")

			video_metadata_map = batch_fetch_activity_metadata(set(video_ids_to_check))
			
			await process_youtube_notifications(pending_notifications, video_metadata_map)

		except Exception as e:
			main.logger.error(f"Error inside members-only Youtube activity loop: {e}\n")

		await asyncio.sleep(wait_time)

def fetch_latest_members_only_content(channel_url: str, number_of_items: 1) -> list[str]:
	"""
	Fetches latest activity ID(s) from given channel's members-only playlist.
	"""
	global youtubeClient
	playlist_id = "UUMO" + channel_url[2:]  # Transform UCxxxx → UUMOxxxx

	video_ids = []

	response = youtubeClient.playlistItems().list(
		part="contentDetails",
		playlistId=playlist_id,
		maxResults=number_of_items,
	).execute()

	for item in response.get("items", []):
		video_id = item["contentDetails"].get("videoId")
		if video_id:
			video_ids.append(video_id)

	return video_ids
