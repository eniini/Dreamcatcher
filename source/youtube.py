import sqlite3
import asyncio
import functools
import requests
import xml.etree.ElementTree as ET
from fastapi import Request, Query
from googleapiclient.discovery import build

import main
import bot
import web

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
#	SQL functions
#

def youtube_post_already_notified(post_id: str) -> bool:
	"""
	Checks if the given Youtube post ID is already stored in the database.
	"""
	try:
		conn = sqlite3.connect("youtube_posts.db")
		cursor = conn.cursor()
		cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='youtube_posts'")
		table_exists = cursor.fetchone()
		if table_exists:
			cursor.execute("SELECT activity_id FROM youtube_posts WHERE activity_id = ?", (post_id,))
		else:
			return False
		result = cursor.fetchone()
		conn.close()
		return result is not None  # True if post exists, False otherwise
	except Exception as e:
		main.logger.error(f"Error checking YT activity post in database: {e}")
		# returning true if SQL query fails for some reason to avoid looping.
		return True

def youtube_save_post_to_db(post_id: str) -> None:
	"""
	Saves the Youtube post ID in the database.
	"""
	try:
		conn = sqlite3.connect("youtube_posts.db")
		cursor = conn.cursor()
		# insert new post, ignore if exists
		cursor.execute("INSERT OR IGNORE INTO youtube_posts (activity_id) VALUES (?)", [post_id])
		# Delete older posts, keeping only the latest 20
		cursor.execute("""
			DELETE FROM youtube_posts 
			WHERE id NOT IN (
				SELECT id FROM youtube_posts 
				ORDER BY timestamp DESC 
				LIMIT 20
			)
		""")
		conn.commit()
		conn.close()
	except Exception as e:
		main.logger.error(f"Error saving post to database: {e}")

def save_discord_subscription(server_id: str, channel_id: str) -> None:
	"""
	Saves the Discord Channel and its associated subscribed Youtube channel ID in the database.
	"""
	try:
		conn = sqlite3.connect("youtube_channels.db")
		cursor = conn.cursor()
		cursor.execute("INSERT OR IGNORE INTO youtube_channels (server_id, channel_id) VALUES (?, ?)", (server_id, channel_id))
		conn.commit()
		conn.close()
		# return c.rowcount > 0
	except Exception as e:
		main.logger.error(f"Error saving Youtube channel to YT database: {e}")

def remove_discord_subscription(server_id: str, channel_id: str) -> None:
	"""
	Removes the Discord Channel and its associated subscribed Youtube channel ID from the database.
	Automatically calls the Youtube Web Sub unsubscribe function if no other server is subscribed to the same channel.
	"""
	try:
		conn = sqlite3.connect("youtube_channels.db")
		cursor = conn.cursor()
		cursor.execute("DELETE FROM youtube_channels WHERE server_id = ? AND channel_id = ?", (server_id, channel_id))
		conn.commit()
		
		# check the SQL database if any other server is subscribed to the same channel
		cursor.execute("SELECT server_id FROM youtube_channels WHERE channel_id = ?", (channel_id,))
		result = cursor.rowcount
		if result == 0:
			# no other server is subscribed to this channel, unsubscribe from Youtube Web Sub
			unsubscribe_from_channel(channel_id)
		conn.close()
	except Exception as e:
		main.logger.error(f"Error removing Youtube channel from YT database: {e}")

def is_discord_channel_subscribed(channel_id: str) -> bool:
	"""
	Queries Discord channel ID from the DB, returns true it exists (has active subscription).
	"""
	try:
		conn = sqlite3.connect("youtube_channels.db")
		cursor = conn.cursor()
		cursor.execute("SELECT channel_id FROM youtube_channels WHERE channel_id = ?", (channel_id))
		result = cursor.rowcount
		conn.close()
		return True if result > 0 else False
	except Exception as e:
		main.logger.error(f"Error fetching Youtube channel from YT database: {e}")

def get_all_subscribed_channels(channel_id: str) -> list[str]:
	"""
	Fetches all discord channels which are subscribed to {channel_id} Youtube channel.
	"""	
	try:
		conn = sqlite3.connect("youtube_channels.db")
		cursor = conn.cursor()
		cursor.execute("SELECT server_id FROM youtube_channels WHERE channel_id = ?", (channel_id,))
		result = [row[0] for row in cursor.fetchall()]
		conn.close()
		return result
	except Exception as e:
		main.logger.error(f"Error fetching Discord channels from YT database: {e}")

#
#	Webhook endpoints
#

@web.fastAPIapp.get("/youtube-webhook")
async def verify_youtube_webhook(
		hub_mode: str = Query(None),
		hub_challenge: str = Query(None),
		hub_topic: str = Query(None)
	):
	"""
	Handles YouTube Web Sub (PubSubHubbub) verification challenge.
	"""
	if hub_mode == "subscribe" and hub_challenge:
		return {"hub.challenge": hub_challenge} # Return the challenge to verify the subscription
	return "Invalid request"

@web.fastAPIapp.post("/youtube-webhook")
async def youtube_webhook(request: Request):
	"""
	Receives YouTube Web Sub notifications when a new video is posted.
	"""
	data = await request.body()
	# parse received XMl data
	root = ET.fromstring(data)

	# check if the notification is for a new video
	# TODO: could also handle activityId for other types of notifications

	for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
		#activity_id = entry.find('{http://www.youtube.com/xml/schemas/2015}activityId').text
		video_url = entry.find("{http://www.w3.org/2005/Atom}link").attrib["href"]
		video_id = video_url.split("v=")[-1]
		#video_id = entry.find("{http://www.w3.org/2005/Atom}link").attrib["href"].split("/")[-1]
		channel_id = entry.find("{http://www.w3.org/2005/Atom}author").find("{http://www.w3.org/2005/Atom}uri").text.split("/")[-1]
		title = entry.find("{http://www.w3.org/2005/Atom}title").text

		main.logger.info(f"New video from channel {channel_id}: {video_id}\n")

		# check if post was already notified/processed
		if youtube_post_already_notified(video_id):
			main.logger.info(f"Video {video_id} already notified, skipping...\n")
			return {"status": "ignored"}
		# save the post to database and notify discord bot
		youtube_save_post_to_db(video_id)
		await bot.notify_youtube_activity(
			activity_type="upload",		#todo: tag for correct content type (upload, livestream, post)
			title=title,
			published_at="now",			#todo: get utc timestamp
			video_id=video_id,
			post_text=None				#todo: add if community postt
		)

	# notify discord bot about video...

	return {"status": "ok"}

#
#	POST request for Youtube Web Sub Hub
#

def subscribe_to_channel(channel_id: str, callback_url) -> tuple[int, str]:
	"""
	Subscribe to a Youtube channel's new video notifications.
	"""
	url = "https://pubsubhubbub.appspot.com/subscribe"
	data = {
		"hub.callback": callback_url,
		"hub.mode": "subscribe",
		"hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}",
		"hub.verify": "async"
	}
	response = requests.post(url, data=data)
	return response.status_code, response.text

def unsubscribe_from_channel(channel_id: str, callback_url) -> tuple[int, str]:
	"""
	Unsubscribe from a Youtube channel's new video notifications.
	"""
	url = "https://pubsubhubbub.appspot.com/subscribe"
	data = {
		"hub.callback": callback_url,
		"hub.mode": "unsubscribe",
		"hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}",
		"hub.verify": "async"
	}
	response = requests.post(url, data=data)
	return response.status_code, response.text

#
#	Youtube API functions, video/livestream/post fetching
#

@reconnect_api_with_backoff()
async def get_latest_video_from_playlist() -> str:
	"""
	Fetches the latest video ID from the channel's uploads playlist.
	This is the least expensive way to check for new videos. (less Youtube API quota usage)
	Must be called in order to get the actual video URL, as activities() only returns video ID.
	"""
	playlist_id = main.TARGET_PLAYLIST_ID
	if not playlist_id:
		return None

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
	video_id = None
	post_text = None

	main.logger.info(f"Starting the Youtube activity sharing task...\n")
	while True:
		try:
			# Fetch the YouTube channel's activities
			request = youtubeClient.activities().list(
				part='snippet',
				channelId=main.TARGET_YOUTUBE_ID,
				maxResults=1
			)
			response = request.execute()
			for item in response.get('items', []):
				activity_id = item['id']
				activity_type = item['snippet']['type']
				title = item['snippet']['title']
				published_at = item['snippet']['publishedAt']
				if activity_type == "post":
					post_text = item["snippet"]["description"]
		except Exception as e:
			main.logger.error(f"Error fetching Youtube API information or saving it to SQL: {e}")
			await initialize_youtube_client()
		# Check if post is new content, send discord notification if yes.
		try:
			result = youtube_post_already_notified(activity_id)
			if result:
				# Post already notified, skip
				pass
			else:
				# Check if it's a new upload/livestream/short, needs additional query for video URL
				if activity_type == "upload":
						video_id = await get_latest_video_from_playlist()
						if video_id is None:
							main.logger.error(f"Failed to fetch video ID {activity_id} from playlist!\n")

							# If video URL query fails, save it to database anyway to avoid looping.
							# (if the ID is for video/livestream it won't be a post, therefore no activity is notified)
							continue

				youtube_save_post_to_db(activity_id)
				if video_id or post_text:
					await bot.notify_youtube_activity(activity_type, title, published_at, video_id, post_text)
		except Exception as e:
			main.logger.error(f"Error saving Youtube API result to SQL: {e}")

		# wait for 60 seconds before checking again.
		await asyncio.sleep(wait_time)
