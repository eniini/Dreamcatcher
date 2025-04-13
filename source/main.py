import os
import sqlite3
import logging
import asyncio
import signal 
from dotenv import load_dotenv

import bot
import blsky
import web
import sql

load_dotenv()

# Initialize API keys & Discord Home Server ID

# APIS
DISCORD_BOT_TOKEN	= os.getenv("DISCORD_BOT_TOKEN")
YOUTUBE_API_KEY		= os.getenv("YOUTUBE_API_KEY")
BLUESKY_USERNAME	= os.getenv("BLUESKY_USERNAME")
BLUESKY_PASSWORD	= os.getenv("BLUESKY_PASSWORD")

HOME_SERVER_ID		= int(os.getenv("HOME_SERVER_ID"))
HOME_CHANNEL_ID		= int(os.getenv("HOME_CHANNEL_ID"))

TARGET_YOUTUBE_ID	= os.getenv("TARGET_CHANNEL_ID")
TARGET_PLAYLIST_ID	= os.getenv("TARGET_PLAYLIST_ID")
TARGET_BLUESKY_ID	= os.getenv("TARGET_BLUESKY_ID")

PUBLIC_WEBHOOK_IP = os.getenv("PUBLIC_WEBHOOK_IP")

class HTTPLogFilter(logging.Filter):
	def filter(self, record):
		# skip logs that are simply 200 OK
		if '200 OK' in record.getMessage():
			return False
		return True

# Setup logging for the main process
logging.basicConfig(level=logging.INFO) # change this too warning for production!
logger = logging.getLogger(__name__)
logger.addFilter(HTTPLogFilter())  # Add the filter to the logger

# Set to store notified streams to avoid duplicate notifications
notified_streams = set()

async def main():
	try:
		# Initialize the SQLite database
		sql.init_db()
	except Exception as e:
		logger.error(f"Error initializing content subscription database: {e}")
		return
		
	# initialize APIs
	await blsky.initialize_bluesky_client()
	
	asyncio.create_task(bot.bot.start(DISCORD_BOT_TOKEN))
	asyncio.create_task(web.run_web_server())

	# Create an event to signal shutdown
	shutdown_event = asyncio.Event()

	# Define a signal handler to set the shutdown event
	def handle_signal():
		logger.info("Received shutdown signal, stopping...")
		shutdown_event.set()

	# Add signal handlers
	for sig in (signal.SIGINT, signal.SIGTERM):
		signal.signal(sig, lambda s, f: handle_signal())

	# Wait for the shutdown event
	await shutdown_event.wait()

	# Shutdown tasks
	await bot.on_shutdown()
	await web.close_web_server()

def main_entry():
	# Run the main function
	asyncio.run(main())

if __name__ == "__main__":
	main_entry()
