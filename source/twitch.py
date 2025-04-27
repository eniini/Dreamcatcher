import aiohttp
import asyncio
import re
import time

import main
import sql
from reconnect_decorator import reconnect_api_with_backoff
import bot

WAIT_TIME = 60  # seconds between checks

twitch_session = None
twitch_auth_token = None
twitch_auth_token_expires = 0

#
#	# Twitch API helper functions

async def initialize_twitch_session():
	global twitch_session
	if twitch_session is None or twitch_session.closed:
		twitch_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False))
		# check if the session is open
		if not twitch_session.closed:
			main.logger.info("Twitch session initialized successfully.\n")
		else:
			main.logger.error("Failed to initialize Twitch session.\n")

async def close_twitch_session():
	global twitch_session
	if twitch_session and not twitch_session.closed:
		await twitch_session.close()
		twitch_session = None

async def initialize_twitch_auth_token(force_refresh: bool = False) -> str:
	"""
	Fetches and sets the Twitch auth token using the client ID and secret.
	Fresh token is generated each time bot starts, then reused until it expires.
	Force refresh can be used to get a new token if needed.
	"""
	global twitch_auth_token, twitch_auth_token_expires
	
	# if no token is set, fetch a new one
	if not twitch_auth_token or time.time() > twitch_auth_token_expires or force_refresh:
		main.logger.info("Fetching new Twitch auth token...")

		token_url = "https://id.twitch.tv/oauth2/token"
		payload = {
			"client_id": main.TWITCH_CLIENT_ID,
			"client_secret": main.TWITCH_CLIENT_SECRET,
			"grant_type": "client_credentials"
		}

		async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
			async with session.post(token_url, data=payload) as response:
				if response.status != 200:
					raise Exception(f"Twitch API error while fetching token: {response.status}")
				token_data = await response.json()

				twitch_auth_token = token_data["access_token"]
				twitch_auth_token_expires = time.time() + token_data["expires_in"] - 60 # 1 minute buffer

				main.logger.info(f"New Twitch auth token fetched successfully.\n")

	return twitch_auth_token

@reconnect_api_with_backoff(initialize_twitch_session, "Twitch")
async def twitch_get(endpoint: str, params: dict = None) -> dict:
	"""
	Makes a GET request to Twitch API with proper authorization.
	endpoint: Twitch API endpoint to call (e.g., "users", "streams")
	params: dictionary of query params
	"""
	global twitch_auth_token

	url = f"https://api.twitch.tv/helix/{endpoint}"
	headers = {
		"Client-ID": main.TWITCH_CLIENT_ID,
		"Authorization": f"Bearer {twitch_auth_token}"
	}

	async with twitch_session.get(url, headers=headers, params=params) as response:
		if response.status != 200:
			error_text = await response.text()
			raise Exception(f"Twitch API GET {url} failed: {response.status} - {error_text}")
		
		return await response.json()

#
#	# Twitch API calls
#

async def verify_twitch_channel(user_input: str) -> str | None:
	# Fetches and verifies the Twitch channel ID from the channel handle
	"""
	Given a Twitch URL or username, validate existence and return the user ID if valid.
	Returns None if the user does not exist.
	"""
	# Extract username if a URL is given
	match = re.search(r"(?:twitch\.tv/)?([a-zA-Z0-9_]+)$", user_input.strip())
	if not match:
		return None
	username = match.group(1)

	data = await twitch_get("users", params={"login": username})
	if data.get("data"):
		user_info = data["data"][0]
		return user_info["id"]  # Return the internal user ID

	return None

async def fetch_twitch_stream_info(user_login: str) -> dict | None:
	"""
	Fetches the stream information for a given Twitch user.
	"""
	main.logger.info(f"Fetching stream info for user: {user_login}...\n")
	data = await twitch_get("streams", params={"user_login": user_login})
	# Check if the stream is live
	if data.get("data"):
		return data["data"][0]
	return None

async def fetch_twitch_scheduled_broadcast(user_id: str) -> dict | None:
	"""
	Fetches the scheduled broadcast information for a given Twitch user ID.
	"""
	main.logger.info(f"Fetching scheduled broadcast info for user ID: {user_id}...\n")
	data = await twitch_get("schedule", params= {"broadcaster_id": user_id, "first": 1})
	segments = data.get("data", {}).get("segments", [])
	# Check if there are any scheduled segments
	if segments:
		return segments[0]
	return None

#
#	# Twitch activity sharing task
#

async def check_for_twitch_activities():
	global twitch_session, twitch_auth_token

	main.logger.info("Starting the Twitch activity sharing task...\n")
	while True:
		try:
			twitch_subscriptions = sql.get_all_social_media_subscriptions_for_platform("Twitch")
			pending_notifications = []

			twitch_auth_token = await initialize_twitch_auth_token()

			for twitch_id in twitch_subscriptions:
				internal_id = sql.get_id_for_channel_url(twitch_id)
				twitch_login_name = sql.get_channel_name(internal_id)

				try:
					match = re.search(r"(?:twitch\.tv/)?([a-zA-Z0-9_]+)$", twitch_login_name.strip())
					if not match:
						main.logger.error(f"Invalid Twitch login format: {twitch_login_name}\n")
						continue
					twitch_login_name = match.group(1)
					# Check if live
					live_info = await fetch_twitch_stream_info(twitch_login_name)
					if live_info:
						pending_notifications.append({
							"type": "liveStreamNow",
							"internal_id": internal_id,
							"channel_name": twitch_login_name,
							"title": live_info["title"]
						})
					else:
						# If not live, check schedule
						user_id = sql.get_twitch_user_id(twitch_login_name)
						scheduled_info = await fetch_twitch_scheduled_broadcast(user_id)
						if scheduled_info:
							pending_notifications.append({
								"type": "liveStreamSchedule",
								"internal_id": internal_id,
								"channel_name": twitch_login_name,
								"title": scheduled_info["title"],
								"start_time": scheduled_info["start_time"]
							})

				except Exception as e:
					main.logger.error(f"Error processing Twitch user {twitch_login_name}: {e}\n")

			await process_twitch_notifications(pending_notifications)

		except Exception as e:
			main.logger.error(f"Error inside Twitch activity loop: {e}\n")

		await asyncio.sleep(WAIT_TIME)

async def process_twitch_notifications(pending_notifications: list[dict]) -> None:
	"""
	Process the batch of Twitch activities, updating database and notifying Discord channels.
	"""
	for item in pending_notifications:
		virtual_id = str(item["internal_id"]) + item["title"] + item["type"]

		if sql.check_post_match(item["internal_id"], virtual_id):
			continue

		sql.update_latest_post(item["internal_id"], virtual_id, item["title"])

		discord_channels = sql.get_discord_channels_for_social_channel(item["internal_id"])

		for discord_channel in discord_channels:
			await bot.notify_twitch_activity(
				discord_channel,
				item["type"],
				item["channel_name"],
				item.get("title"),
				item.get("start_time")
			)
