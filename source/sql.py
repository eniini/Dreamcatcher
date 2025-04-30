import os
import sqlite3
import pandas as pd
from datetime import datetime, timezone

import main

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
# Debug / Test Functions
#

def read_table_contents():
	conn = get_connection()
	if conn is None:
		return
	
	pd.set_option('display.max_rows', None)
	pd.set_option('display.max_columns', None)
	pd.set_option('display.width', 0)
	pd.set_option('display.max_colwidth', 25)

	result_str = "Active Discord Channels:\n"
	result_str += (f"{pd.read_sql_query('SELECT * FROM DiscordChannels', conn)}\n")
	result_str += "\nFollowed Social Media Channels:\n"
	result_str += (f"{pd.read_sql_query('SELECT * FROM SocialMediaChannels', conn)}\n")
	result_str += "\nSubscriptions:\n"
	result_str += (f"{pd.read_sql_query('SELECT * FROM Subscriptions', conn)}\n")
	result_str += "\nLatest Posts:\n"
	result_str += (f"{pd.read_sql_query('SELECT * FROM LatestPosts', conn)}\n")


	conn.commit()
	conn.close()

	return result_str

def initialize_placeholder_data():
	"""
	Is ran automatically if bot_database.db doesn't exist yet.
	"""
	main.logger.info(f"Clean setup, initalizing placeholder data...\n")

	add_discord_channel(main.HOME_CHANNEL_ID, "DREAMCATCHER_HOME_CHANNEL")

	id = add_social_media_channel("YouTube", "UCIfAvpeIWGHb0duCkMkmm2Q", "Nimi Nightmare")
	add_subscription(main.HOME_CHANNEL_ID, id)

	id = add_social_media_channel("Bluesky", "niminightmare.bsky.social", "Nimi Nightmare")
	add_subscription(main.HOME_CHANNEL_ID, id)

	main.logger.info(f"{read_table_contents()}\n")

#
# Database Connection & Setup
#

def init_db():
	"""
	Establishes connection to SQLite database.
	Create tables for DiscordChannels, SocialMediaChannels, and Subscriptions.
	"""
	# Check if bot_database.db exists
	clean_setup = not os.path.exists(db_file)

	conn = get_connection()
	if conn is None:
		return
	cursor = conn.cursor()

	# Table for Discord Channels.
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS DiscordChannels (
			channel_id TEXT PRIMARY KEY,
			channel_name TEXT,
			notification_role TEXT
		)
	''')

	# Table for Social Media Channels.
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS SocialMediaChannels (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			platform TEXT NOT NULL,
			external_url TEXT NOT NULL,
			channel_name TEXT,
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


def add_notification_role(discord_channel_id, notification_role):
	"""
	Add a notification role to a discord channel.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('''
			UPDATE DiscordChannels SET notification_role = ?
			WHERE channel_id = ?
		''', (notification_role, discord_channel_id))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error adding notification role: {e}")
	finally:
		conn.close()

def remove_notification_role(discord_channel_id):
	"""
	Remove the notification role for a discord channel.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('''
			UPDATE DiscordChannels SET notification_role = NULL
			WHERE channel_id = ?
		''', (discord_channel_id,))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error removing notification role: {e}")
	finally:
		conn.close()

def get_notification_role(discord_channel_id):
	"""
	Get the notification role for a discord channel.
	Ignore rows where notification_role is NULL.
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT notification_role FROM DiscordChannels
			WHERE channel_id = ? AND notification_role IS NOT NULL
		''', (discord_channel_id,))
		row = cursor.fetchone()
		return row['notification_role'] if row else None
	except sqlite3.Error as e:
		main.logger.error(f"Error getting notification role: {e}")
		return None
	finally:
		conn.close()

#
#	Social media channel management
#

def add_social_media_channel(platform, external_url, channel_name):
	"""
	Add a new discord channel, returns an unique id.
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO SocialMediaChannels (platform, external_url, channel_name)
			VALUES (?, ?, ?)
		''', (platform, external_url, channel_name))
		id = cursor.lastrowid
		conn.commit()
		return id
	except sqlite3.Error as e:
		main.logger.error(f"Error adding social media channel: {e}")
		return None
	finally:
		conn.close()

def remove_social_media_channel(social_media_channel_id):
	"""
	Remove a discord channel given its id.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('DELETE FROM SocialMediaChannels WHERE id = ?', (social_media_channel_id,))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error removing social media channel: {e}")
	finally:
		conn.close()

#
# Latest Posts management
#

def remove_latest_post(social_media_channel_id):
	"""
	Remove the latest post for a given social media channel.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		cursor.execute('DELETE FROM LatestPosts WHERE social_media_channel_id = ?', (social_media_channel_id,))
		conn.commit()
	except sqlite3.Error as e:
		main.logger.error(f"Error removing latest post: {e}")
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

def remove_subscription(discord_channel_id, social_media_channel_id=None):
	"""
	Remove a social media subscription from Discord channel given its social_media_channel_id.
	If social_media_channel_id is None, recursively remove all social media subscriptions for the given discord channel.
	"""
	conn = get_connection()
	if conn is None:
		return
	try:
		cursor = conn.cursor()
		if social_media_channel_id is not None:
			cursor.execute('DELETE FROM Subscriptions WHERE social_media_channel_id = ? AND discord_channel_id = ?', (social_media_channel_id, discord_channel_id))
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

def get_channel_platform(channel_id):
	"""
	Find the matching id in SocialMediaChannels table and return the saved platform
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT platform FROM SocialMediaChannels
			WHERE id = ?
		''', (channel_id,))
		row = cursor.fetchone()
		return row['platform'] if row else None
	except sqlite3.Error as e:
		main.logger.error(f"Error getting channel platform: {e}")
		return None
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
		row = cursor.fetchone()
		return row['external_url'] if row else None
	except sqlite3.Error as e:
		main.logger.error(f"Error getting channel URL: {e}")
		return None
	finally:
		conn.close()

def get_channel_name(channel_id):
	"""
	Find the matching id in SocialMediaChannels table and return the saved channel_name
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT channel_name FROM SocialMediaChannels
			WHERE id = ?
		''', (channel_id,))
		row = cursor.fetchone()
		return row['channel_name'] if row else None
	except sqlite3.Error as e:
		main.logger.error(f"Error getting channel name: {e}")
		return None
	finally:
		conn.close()

def get_id_for_channel_url(external_url):
	"""
	Get the matching Subscription id for given socialMediaChannel url if a subscription for it exists.
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT id FROM SocialMediaChannels
			WHERE external_url = ?
		''', (external_url,))
		row = cursor.fetchone()
		return int(row['id']) if row else None
	except sqlite3.Error as e:
		main.logger.error(f"Error getting internal id for given URL ({external_url}): {e}")
		return None
	finally:
		conn.close()

def get_discord_channels_for_social_channel(social_media_channel_id: int):
	"""
	Return a list of Discord channels subscribed to a given social media channel.
	"""
	conn = get_connection()
	if conn is None:
		return []
	try:
		cursor = conn.cursor()
		main.logger.info(f"Trying to select all discord channel subscriptions where social_media_channnel_id = {social_media_channel_id}")
		cursor.execute('SELECT discord_channel_id FROM Subscriptions WHERE social_media_channel_id', (social_media_channel_id,))
		rows = cursor.fetchall()
		main.logger.info(f"Matching rows: {rows}")
		cursor.execute('''
			SELECT discord_channel_id FROM Subscriptions
			WHERE social_media_channel_id = ?
		''', (social_media_channel_id,))
		rows = cursor.fetchall()
		# return a list of discord channel ids
		return [row['discord_channel_id'] for row in rows]
	except sqlite3.Error as e:
		main.logger.error(f"Error getting discord channels: {e}")
		return None
	finally:
		conn.close()

def list_social_media_subscriptions_for_discord_channel(discord_channel_id, target_platform=None):
	"""
	List all social media subscriptions for a specific Discord channel.
	Returns a list of internal IDs of social media channels subscribed to the given Discord channel.
	If target_platform is provided, filter results by the given platform.
	"""
	conn = get_connection()
	if conn is None:
		return []
	try:
		cursor = conn.cursor()
		
		if target_platform:
			cursor.execute('''
				SELECT DISTINCT s.id
				FROM SocialMediaChannels s
				JOIN Subscriptions sub ON s.id = sub.social_media_channel_id
				WHERE sub.discord_channel_id = ? AND s.platform = ?
			''', (discord_channel_id, target_platform))
		else:
			cursor.execute('''
				SELECT DISTINCT s.id
				FROM SocialMediaChannels s
				JOIN Subscriptions sub ON s.id = sub.social_media_channel_id
				WHERE sub.discord_channel_id = ?
			''', (discord_channel_id,))

		rows = cursor.fetchall()
		return [row['id'] for row in rows]
	except sqlite3.Error as e:
		main.logger.error(f"Error listing subscriptions: {e}")
		return []
	finally:
		conn.close()

def get_all_social_media_subscriptions_for_platform(platform):
	"""
	List all social media subscriptions for a specific platform.
	Returns a list of external URLs for the given platform.
	"""
	conn = get_connection()
	if conn is None:
		return []
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT DISTINCT s.external_url
			FROM SocialMediaChannels s
			JOIN Subscriptions sub ON s.id = sub.social_media_channel_id
			WHERE s.platform = ?
		''', (platform,))
		rows = cursor.fetchall()
		return [row['external_url'] for row in rows]
	except sqlite3.Error as e:
		main.logger.error(f"Error listing subscriptions: {e}")
		return []
	finally:
		conn.close()

# ------------------- RECORD MANAGEMENT -----------------------------

#
# Latest Post Management Functions
#

def update_latest_post(social_media_channel_id: int, post_id: str, content: str, timestamp=None):
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

def get_latest_post_id(social_media_channel_id: int):
	"""
	Returns the post_id of the latest post for a given social media channel.
	If no post exists, returns None.
	"""
	conn = get_connection()
	if conn is None:
		return None
	try:
		cursor = conn.cursor()
		cursor.execute('''
			SELECT post_id FROM LatestPosts
			WHERE social_media_channel_id = ?
		''', (social_media_channel_id,))
		row = cursor.fetchone()
		if row is None:
			return None
		return row['post_id']
	except sqlite3.Error as e:
		main.logger.error(f"Error getting latest post: {e}")
		return None
	finally:
		conn.close()

def check_post_match(social_media_channel_id: int, post_id: str):
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
