import logging
import sqlite3
import asyncio

from googleapiclient.discovery import build

import main
import bot

# Initialize Youtube API client
youtube = build('youtube', 'v3', developerKey=main.YOUTUBE_API_KEY)
print(type(youtube))

# --------------------------------- SCHEDULED STREAMS ---------------------------------#

def youtube_post_already_notified(post_id):
	"""Checks if the given Youtube post ID is already stored in the database."""
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

def youtube_save_post_to_db(post_id):
	"""Saves the Youtube post ID in the database."""
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

async def get_latest_video_from_playlist():
	"""Fetches the latest video ID from the channel's uploads playlist."""
	playlist_id = main.NIMI_PLAYLIST_ID
	if not playlist_id:
		return None

	try:
		request = youtube.playlistItems().list(
			part="contentDetails",
			playlistId=playlist_id,
			maxResults=1
		)
		response = request.execute()
		if response["items"]:
			return response["items"][0]["contentDetails"]["videoId"]
	except Exception as e:
		main.logger.info(f"Error fetching latest video from playlist: {e}")
	return None

async def check_for_youtube_activities():
	while True:
		try:
			# Fetch the YouTube channel's activities
			request = youtube.activities().list(
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

				# Notify only if its new content
				if (youtube_post_already_notified(activity_id)):
					break
				else:
					youtube_save_post_to_db(activity_id)
				# if the post is new, query YT API again for video details
				if video_id or post_text:
					await bot.notify_discord(activity_type, title, published_at, video_id, post_text)
		except Exception as e:
			main.logger.info(f"Error fetching Youtube API information or saving it to SQL: {e}")
		# wait for 60 seconds before checking again
		await asyncio.sleep(60)
