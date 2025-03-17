import sqlite3
from datetime import datetime, timezone
import main
import os

global db_file
db_file = "bot_database.db"

def get_connection():
	try:
		conn = sqlite3.connect(db_file)
		conn.row_factory = sqlite3.Row
		return conn
	except sqlite3.Error as e:
		main.logger.error(f"Error connecting to database: {e}")
		return None

#
# Add Nimi's socials into database for placeholder/debugging.
#

def initialize_placeholder_data():
	"""
	Is ran automatically if bot_database.db doesn't exist yet.
	"""
	add_discord_channel(main.HOME_CHANNEL_ID, "DREAMCATCHER_HOME_CHANNEL")
	add_social_media_channel("YouTube", main.TARGET_YOUTUBE_ID, None)
	add_subscription(main.HOME_CHANNEL_ID, main.TARGET_YOUTUBE_ID)

#
# Database Connection & Setup
#

def init_db():
	"""
	Establishes connection to SQLite database.
	Create tables for DiscordChannels, SocialMediaChannels, and Subscriptions.
	"""
	
	conn = get_connection()
	if conn is None:
		return
	cursor = conn.cursor()

	# Check if bot_database.db exists
	clean_setup = not os.path.exists(db_file)

	# Table for Discord Channels.
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS DiscordChannels (
			channel_id TEXT PRIMARY KEY,
			channel_name TEXT
		)
	''')

	# Table for Social Media Channels.
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS SocialMediaChannels (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			platform TEXT NOT NULL,
			external_url TEXT NOT NULL,
			webhook_id TEXT,
			last_post_timestamp TEXT
		)
	''')

	# Table for Subscriptions (linking Discord and Social Media Channels).
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS Subscriptions (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			discord_channel_id TEXT NOT NULL,
			social_media_channel_id INTEGER NOT NULL,
			subscription_date TEXT,
			FOREIGN KEY(discord_channel_id) REFERENCES DiscordChannels(channel_id),
			FOREIGN KEY(social_media_channel_id) REFERENCES SocialMediaChannels(id)
		)
	''')

	# Table for tracking the latest post per social media channel.
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS LatestPosts (
			social_media_channel_id INTEGER PRIMARY KEY,
			post_id TEXT NOT NULL,
			content TEXT,
			timestamp TEXT,
			FOREIGN KEY(social_media_channel_id) REFERENCES SocialMediaChannels(id)
		)
	''')
	conn.commit()
	# Close the connection after setup
	conn.close()

	# populate the newly generated SQL with hardcoded data.
	if clean_setup is True:
		initialize_placeholder_data()

#	------------------- TABLES HANDLING -----------------------------

#
#	Discord Channels management
#

def add_discord_channel(discord_channel_id, discord_channel_name):
	"""
	Add a new discord channel, returns an unique id.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('''
			INSERT OR IGNORE INTO DiscordChannels (channel_id, channel_name)
			VALUES (?, ?)
		''', (discord_channel_id, discord_channel_name))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error adding discord channel: {e}")
	finally:
		conn.close()

def remove_discord_channel(discord_channel_Id):
	"""
	Remove a discord channel given its id.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('DELETE FROM DiscordChannels WHERE channel_id = ?', (discord_channel_Id,))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error removing discord channel: {e}")
	finally:
		conn.close()

#
#	Social media channel management
#

def add_social_media_channel(platform, external_url, webhook_id):
	"""
	Add a new discord channel, returns an unique id.
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO SocialMediaChannels (platform, external_url, webhook_id)
			VALUES (?, ?, ?)
		''', (platform, external_url, webhook_id))
		id = cursor.lastrowid
		conn.commit()
		return id
	except sqlite3.Error as e:
		main.logger.error(f"Error adding social media channel: {e}")
		return None
	finally:
		conn.close()

def remove_social_media_channel(row_id):
	"""
	Remove a discord channel given its row id.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('DELETE FROM SocialMediaChannels WHERE id = ?', (row_id,))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error removing social media channel: {e}")
	finally:
		conn.close()

#
# Social Media Subscription Management
#

def add_subscription(discord_channel_id, social_media_channel_id):
	"""
	Add a new subscription linking a Discord channel with a Social Media channel.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		subscription_date = datetime.now(timezone.utc).isoformat()
		cursor.execute('''
			INSERT INTO Subscriptions (discord_channel_id, social_media_channel_id, subscription_date)
			VALUES (?, ?, ?)
		''', (discord_channel_id, social_media_channel_id, subscription_date))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error adding subscription: {e}")
	finally:
		conn.close()

def remove_subscription(discord_channel_id, subscription_id=None):
	"""
	Remove a social media subscription from Discord channel given its subscription_id.
	If subscription_id is None, recursively remove all social media subscriptions for the given discord channel.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		if subscription_id is not None:
			cursor.execute('DELETE FROM Subscriptions WHERE id = ? AND discord_channel_id = ?', (subscription_id, discord_channel_id))
		else:
			cursor.execute('DELETE FROM Subscriptions WHERE discord_channel_id = ?', (discord_channel_id,))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error removing subscription: {e}")
	finally:
		conn.close()

# ------------------- DATABASE QUERIES -----------------------------

#
# Query Functions for Notifications & Listings
#

def is_discord_channel_subscribed(discord_channel_id, social_media_channel_id):
	"""
	Return True if discord channel has an active subscription to the given social media channel.
	"""
	conn = get_connection()
	if conn is None:
		return False
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT id FROM Subscriptions WHERE discord_channel_id = ? AND social_media_channel_id = ?
		''', (discord_channel_id, social_media_channel_id))
		if cursor.fetchone() is not None:
			return True
		return False
	except sqlite3.Error as e:
		main.logger.error(f"Error checking subscription: {e}")
		return False
	finally:
		conn.close()

def get_channel_url(channel_id):
	"""
	Find the matching id in SocialMediaChannels table and return the saved external_url
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT external_url FROM SocialMediaChannels
			WHERE id = ?
		''', (channel_id,))
		return cursor.fetchone()
	except sqlite3.Error as e:
		main.logger.error(f"Error getting channel URL: {e}")
		return None
	finally:
		conn.close()

def get_discord_channels_for_social_channel(social_media_channel_id):
	"""
	Return a list of Discord channels subscribed to a given social media channel.
	Each row contains the discord_channel_id and subscription_date.
	"""
	conn = get_connection()
	if conn is None:
		return []
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT discord_channel_id, subscription_date FROM Subscriptions
			WHERE social_media_channel_id = ?
		''', (social_media_channel_id,))
		return cursor.fetchall()
	except sqlite3.Error as e:
		main.logger.error(f"Error getting discord channels: {e}")
		return []
	finally:
		conn.close()

def list_social_media_subscriptions_for_discord_channel(discord_channel_id):
	"""
	List all social media subscriptions for a specific Discord channel.
	Returns a list of rows containing social media channel details along with subscription metadata.
	"""
	conn = get_connection()
	if conn is None:
		return []
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT s.id, s.platform, s.external_url, s.webhook_id, s.last_post_timestamp, sub.subscription_date
			FROM SocialMediaChannels s
			JOIN Subscriptions sub ON s.id = sub.social_media_channel_id
			WHERE sub.discord_channel_id = ?
		''', (discord_channel_id,))
		return cursor.fetchall()
	except sqlite3.Error as e:
		main.logger.error(f"Error listing subscriptions: {e}")
		return []
	finally:
		conn.close()

# ------------------- RECORD MANAGEMENT -----------------------------

#
# Latest Post Management Functions
#

def update_latest_post(social_media_channel_id, post_id, content, timestamp=None):
	"""
	Insert or update the LatestPosts record for a given social media channel.
	This function overwrites the previous latest post with the new data whenever a webhook is updated.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		if timestamp is None:
			timestamp = datetime.now(timezone.utc).isoformat()
		# SQLite UPSERT syntax: if a record for this social_media_channel_id exists, update it.
		cursor.execute('''
			INSERT INTO LatestPosts (social_media_channel_id, post_id, content, timestamp)
			VALUES (?, ?, ?, ?)
			ON CONFLICT(social_media_channel_id)
			DO UPDATE SET
				post_id=excluded.post_id,
				content=excluded.content,
				timestamp=excluded.timestamp
		''', (social_media_channel_id, post_id, content, timestamp))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error updating latest post: {e}")
	finally:
		conn.close()

def check_post_match(social_media_channel_id, post_id):
	"""
	Compare latest post by given channel to the one saved into database. If the post_id is the same as stored one,
	Return true. Otherwise return false, indicating that the post is new.
	"""
	conn = get_connection()
	if conn is None:
		return False
	try:
		cursor = conn.cursor()
		# find matching table for social media channel if one exists
		cursor.execute('''
			SELECT post_id FROM LatestPosts
			WHERE social_media_channel_id = ?
		''', (social_media_channel_id,))
		row = cursor.fetchone()
		if row is None:
			return False
		# return True if stored post is the same as given
		return row['post_id'] == post_id
	except sqlite3.Error as e:
		main.logger.error(f"Error checking post match: {e}")
		return False
	finally:
		conn.close()
