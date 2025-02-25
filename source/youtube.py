import sqlite3
import asyncio
import functools

from googleapiclient.discovery import build

import main
import bot


async def initialize_youtube_client():
	global youtubeClient
	try:
		youtubeClient = build('youtube', 'v3', developerKey=main.YOUTUBE_API_KEY)
		main.logger.info(f"Youtube API initialized successfully.\n")
	except Exception as e:
		main.logger.error(f"Failed to initialize Youtube API client: {e}\n")
		raise

def reconnect_api_with_backoff(max_retries=5, base_delay=2):
	"""Tries to re-establish given API connection with exponential falloff."""
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

# --------------------------------- SCHEDULED STREAMS ---------------------------------#

def youtube_post_already_notified(post_id: str) -> bool:
	"""Checks if the given Youtube post ID is already stored in the database."""
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

def youtube_save_post_to_db(post_id: str):
	"""Saves the Youtube post ID in the database."""
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

@reconnect_api_with_backoff()
async def get_latest_video_from_playlist() -> str:
	"""Fetches the latest video ID from the channel's uploads playlist."""
	playlist_id = main.NIMI_PLAYLIST_ID
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
async def check_for_youtube_activities():
	while True:
		try:
			# Fetch the YouTube channel's activities
			request = youtubeClient.activities().list(
				part='snippet',
				channelId=main.NIMI_YOUTUBE_ID,
				maxResults=1
			)
			response = request.execute()
			for item in response.get('items', []):
				activity_id = item['id']
				activity_type = item['snippet']['type']
				title = item['snippet']['title']
				published_at = item['snippet']['publishedAt']
				video_id = None
				post_text = None
				if activity_type == "post":
					post_text = item["snippet"]["description"]
				# Check if it's a new upload/livestream/short
				if activity_type == "upload":
					video_id = await get_latest_video_from_playlist()
		except Exception as e:
			main.logger.error(f"Error fetching Youtube API information or saving it to SQL: {e}")
			await reconnect_api_with_backoff(initialize_youtube_client)
		# Check if post is new content, send discord notification if yes.
		try:
			if youtube_post_already_notified(activity_id):
				break
			else:
				youtube_save_post_to_db(activity_id)
			if video_id or post_text:
				await bot.notify_youtube_activity(activity_type, title, published_at, video_id, post_text)
		except Exception as e:
			main.logger.error(f"Error saving Youtube API result to SQL: {e}")		

		# wait for 60 seconds before checking again
		await asyncio.sleep(60)
