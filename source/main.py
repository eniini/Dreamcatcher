import os
import sqlite3
import logging
import re
import asyncio

from dotenv import load_dotenv

import bot
import youtube
import blsky

# Matches full URLs and truncated ones (www, .com/, domain-like)
URL_REGEX = re.compile(r'(\b(?:https?://|www\.)?\S+\.\S{2,}(?:/\S*)?)')

# Modifies Bluesky URI format (at://<DID>/<COLLECTION>/<RKEY>) into standard URL
URI_TO_URL_REGEX = re.compile(r"at://([^/]+)/([^/]+)/([^/]+)")

load_dotenv()

# Initialize API keys & Discord Home Server ID
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
NIMI_YOUTUBE_ID = os.getenv("NIMI_CHANNEL_ID")
HOME_SERVER_ID = int(os.getenv("HOME_SERVER_ID"))
HOME_CHANNEL_ID = os.getenv("HOME_CHANNEL_ID")
NIMI_PLAYLIST_ID = os.getenv("NIMI_PLAYLIST_ID")
NIMI_BLUESKY_ID = os.getenv("NIMI_BLUESKY_ID")
BLUESKY_USERNAME = os.getenv("BLUESKY_USERNAME")
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")


# Setup logging for the main process
logging.basicConfig(level=logging.INFO) # change this too warning for production!
logger = logging.getLogger(__name__)

# Set to store notified streams to avoid duplicate notifications
notified_streams = set()

# ------------------- DATABASE OPERATIONS -------------------
# Initialize SQLite databases
def init_db():
	conn = sqlite3.connect('whitelist_channels.db')
	c = conn.cursor()
	c.execute("""CREATE TABLE IF NOT EXISTS whitelist_channels
		   (channel_id TEXT PRIMARY KEY)""")
	conn.commit()
	conn.close()

	conn = sqlite3.connect('bluesky_posts.db')
	c = conn.cursor()
	c.execute("""CREATE TABLE IF NOT EXISTS bluesky_posts
			(id INTEGER PRIMARY KEY AUTOINCREMENT,
			uri TEXT UNIQUE,  -- Stores post URI
			content TEXT,      -- Stores post text
			timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
	conn.commit()
	conn.close()

	conn = sqlite3.connect('youtube_posts.db')
	c = conn.cursor()
	c.execute("""CREATE TABLE IF NOT EXISTS youtube_posts
			(id INTEGER PRIMARY KEY AUTOINCREMENT,
			activity_id TEXT UNIQUE,  -- Stores activity ID
			timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
	conn.commit()
	conn.close()

def add_channel_to_whitelist(channel_id):
	try:
		conn = sqlite3.connect('whitelist_channels.db')
		c = conn.cursor()
		c.execute("INSERT OR IGNORE INTO whitelist_channels (channel_id) VALUES (?)", (channel_id,))
		conn.commit()
		conn.close()
	except Exception as e:
		logger.error(f"Error adding channel to whitelist: {e}\n")

def remove_channel_from_whitelist(channel_id):
	try:
		conn = sqlite3.connect('whitelist_channels.db')
		c = conn.cursor()
		c.execute("DELETE FROM whitelist_channels WHERE channel_id = ?", (channel_id,))
		if c.rowcount == 0:
			# no matching item found
			conn.close()
			return False
		conn.commit()
		conn.close()
		return True
	except Exception as e:
		logger.error(f"Error removing channel from whitelist: {e}\n")
		return False

def get_whitelisted_channels():
	try:
		conn = sqlite3.connect('whitelist_channels.db')
		c = conn.cursor()
		c.execute("SELECT channel_id FROM whitelist_channels")
		channels = [row[0] for row in c.fetchall()]
		conn.close()
		return channels
	except Exception as e:
		logger.error(f"Error fetching whitelisted channels: {e}\n")
		return []


async def main():
	# Initialize the SQLite database
	init_db()
	await youtube.initialize_youtube_client()
	await blsky.initialize_bluesky_client()
	await bot.bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
	try:
		asyncio.run(main())
	except Exception as e:
		logger.error(f"Error initializing the Discord bot: {e}\n")
