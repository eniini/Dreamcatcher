import sqlite3
import asyncio
import functools

from atproto import Client

import main
import bot

async def initialize_bluesky_client():
	global client
	try:
		# Initialize Bluesky API client
		client = Client()
		client.login(main.BLUESKY_USERNAME, main.BLUESKY_PASSWORD)
		main.logger.info(f"Bluesky API initalized successfully.\n")
	except Exception as e:
		main.logger.error(f"Failed to initialize Bluesky API client: {e}\n")
		raise

def reconnect_api_with_backoff(max_retries=5, base_delay=2):
	"""Tries to re-establish given API connection with exponential falloff."""
	def decorator(api_func):
		@functools.wraps(api_func)
		async def wrapper(*args, **kwargs):
			attempt=0
			while (attempt < max_retries):
				try:
					return await api_func(*args, **kwargs)
				except Exception as e:
					attempt+=1
					main.logger.warning(f"Bluesky API call failed! (attempt{attempt}/{max_retries}): {e}")

					if ("quotaExceeded" in str(e) or "403" in str(e)):
						main.logger.critical(f"Bot has exceeded Bluesky API quota.")
						bot.bot_internal_message("Bot has exceeded Blueskye API quota!")
						return None
					if (attempt == max_retries):
						main.logger.error(f"Max retries reached. Could not recover API connection.")
						bot.bot_internal_message("Bot failed to connect to Bluesky API after max retries...")

					wait_time = base_delay * pow(2, attempt - 1)
					main.logger.info(f"Reinitializing Bluesky API client in {wait_time:.2f} seconds...")

					await asyncio.sleep(wait_time)
					# try to reconnect API
					await initialize_bluesky_client()
		return wrapper
	return decorator

# --------------------------------- BLUESKY API INTEGRATION ---------------------------------#

def bluesky_post_already_notified(post_uri):
	"""Checks if the given Bluesky post URI is already stored in the database."""
	try:
		conn = sqlite3.connect("bluesky_posts.db")
		cursor = conn.cursor()
		cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bluesky_posts'")
		table_exists = cursor.fetchone()
		if table_exists:
			cursor.execute("SELECT uri FROM bluesky_posts WHERE uri = ?", (post_uri,))
		else:
			return False
		result = cursor.fetchone()
		conn.close()
		return result is not None  # True if post exists, False otherwise
	except Exception as e:
		main.logger.error(f"Error checking database if post is already notified: {e}\n")
		return False

def bluesky_save_post_to_db(post_uri, content):
	"""Saves the Bluesky post URI and content in the database."""
	try:
		conn = sqlite3.connect("bluesky_posts.db")
		cursor = conn.cursor()
		# insert new post, ignore if exists
		cursor.execute("INSERT OR IGNORE INTO bluesky_posts (uri, content) VALUES (?, ?)", (post_uri, content))

		# Delete older posts, keeping only the latest 20
		cursor.execute("""
			DELETE FROM bluesky_posts 
			WHERE id NOT IN (
				SELECT id FROM bluesky_posts 
				ORDER BY timestamp DESC 
				LIMIT 20
			)
		""")
		conn.commit()
		conn.close()
	except Exception as e:
		main.logger.error(f"Error saving post to database: {e}\n")

def convert_bluesky_uri_to_url(at_uri):
	"""
	Converts a Bluesky AT URI (at://<DID>/<COLLECTION>/<RKEY>) into a valid web URL.
	Example:
	Input: at://did:plc:abcd1234/app.bsky.feed.post/xyz987
	Output: https://bsky.app/profile/did:plc:abcd1234/post/xyz987
	"""
	# Bluesky URI format: at://<DID>/<COLLECTION>/<RKEY>
	# match = re.match(r"at://([^/]+)/([^/]+)/([^/]+)", at_uri)
	match = main.URI_TO_URL_REGEX.match(at_uri)

	if match:
		did = match.group(1)  # Extract DID
		collection = match.group(2)  # Extract Collection Type
		rkey = match.group(3)  # Extract Record Key

		# Check if the URI belongs to a post
		if collection == "app.bsky.feed.post":
			return f"https://bsky.app/profile/{did}/post/{rkey}"
	
	return None  # Return None if the URI is invalid or not a post

def extract_media(post):
	"""Extracts image URLs from a Bluesky post, if available."""
	images = []
	if hasattr(post.record, "embed") and hasattr(post.record.embed, "images"):
		try:
			for image in post.record.embed.images:
				#if (image.fullsize):
				#	images.append(image.fullsize)  # Get full-size image URL
				#else:
					images.append(image)
		except Exception as e:
			main.logger.info(f"Error extracting media from post: {e}\n")
	return images

def extract_links(post):
	"""Extracts full URLs from a Bluesky post's facets."""
	full_links = []

	if hasattr(post.record, "facets"):  # Ensure facets exist
		for facet in post.record.facets:
			if hasattr(facet, "features"):
				for feature in facet.features:
					if hasattr(feature, "uri"):  # Hyperlink feature
						full_links.append(feature.uri)  # Extract full URL

	return full_links  # List of full URLs

@reconnect_api_with_backoff()
async def fetch_bluesky_posts():
	try:
		feed = client.get_author_feed(actor=main.NIMI_BLUESKY_ID, limit=5)
		# Extract post text from FeedViewPost objects
		posts = []
		for item in feed.feed:
			if hasattr(item.post.record, "text"):  # Ensure post has text
				post_text = item.post.record.text
				post_uri = item.post.uri  # Get post URI
				images = extract_media(item.post)
				links = extract_links(item.post)
				posts.append({"text": post_text, "uri": post_uri, "post_images": images, "links": links})
		return posts
	except Exception as e:
		main.logger.error(f"Error fetching Bluesky posts: {e}\n")
		return None

async def share_bluesky_posts():
	main.logger.info(f"Starting the Bluesky post sharing task...\n")
	while True:
		try:
			posts = await fetch_bluesky_posts()
			# Allow time for API response
			await asyncio.sleep(5)
			if posts:
				for post in posts:
					#logger.info(f"Post: {post['text']}\n")
					post_uri = post['uri']
					content = post['text']
					images = post['post_images']
					links = post['links']
					# skip if already sent
					if (bluesky_post_already_notified(post_uri)):
						main.logger.info(f"⚠️ Skipping duplicate post: {post_uri}")
						break
					# Send notification to all whitelisted Discord channels
					await bot.notify_bluesky_activity(post_uri, content, images, links)
					# Save the post URI and content to the database
					bluesky_save_post_to_db(post_uri, content)
		except Exception as e:
			main.logger.info(f"Error sharing Bluesky posts: {e}\n")

		# Wait for 10 seconds before checking again
		await asyncio.sleep(10)
