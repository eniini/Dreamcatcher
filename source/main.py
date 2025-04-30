import os
import logging
import asyncio
import signal 
from dotenv import load_dotenv

import bot
import blsky
import sql
import youtube
import twitch

load_dotenv()

# Initialize API keys & Discord Home Server ID

# APIS
DISCORD_BOT_TOKEN		= os.getenv("DISCORD_BOT_TOKEN")
YOUTUBE_API_KEY			= os.getenv("YOUTUBE_API_KEY")
BLUESKY_USERNAME		= os.getenv("BLUESKY_USERNAME")
BLUESKY_PASSWORD		= os.getenv("BLUESKY_PASSWORD")
TWITCH_CLIENT_ID		= os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET	= os.getenv("TWITCH_CLIENT_SECRET")

HOME_SERVER_ID			= int(os.getenv("HOME_SERVER_ID"))
HOME_CHANNEL_ID			= int(os.getenv("HOME_CHANNEL_ID"))

# Setup logging for the main process
logging.basicConfig(level=logging.INFO)  # Change this to WARNING for production!
logger = logging.getLogger(__name__)

# Suppress httpx INFO logs
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

# Set to store notified streams to avoid duplicate notifications
notified_streams = set()

yt_wait_time = 60  # default
wait_time_updated = asyncio.Event()

async def main():
	try:
		# Initialize the SQLite database
		sql.init_db()
	except Exception as e:
		logger.error(f"Error initializing content subscription database: {e}")
		return
		
	# initialize APIs
	await blsky.initialize_bluesky_client()
	await youtube.initialize_youtube_client()
	await twitch.initialize_twitch_session()
	
	asyncio.create_task(bot.bot.start(DISCORD_BOT_TOKEN))

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

def main_entry():
	# Run the main function
	asyncio.run(main())

if __name__ == "__main__":
	main_entry()
