import sqlite3
import asyncio
import functools
import re
import urlextract
from atproto import Client

import main
import bot
import sql

postFetchCount = 5 # number of posts to fetch from Bluesky API per API call.

# Modifies Bluesky URI format (at://<DID>/<COLLECTION>/<RKEY>) into standard URL
URI_TO_URL_REGEX = re.compile(r"at://([^/]+)/([^/]+)/([^/]+)")

async def initialize_bluesky_client() -> None:
	global client
	global extractor
	
	try:
		# Initialize Bluesky API client
		client = Client()
		client.login(main.BLUESKY_USERNAME, main.BLUESKY_PASSWORD)
		main.logger.info(f"Bluesky API initalized successfully.\n")

		# Initialize URL extractor
		extractor = urlextract.URLExtract()

	except Exception as e:
		main.logger.error(f"Failed to initialize Bluesky API client: {e}\n")
		raise

def reconnect_api_with_backoff(max_retries=5, base_delay=2):
	"""
	Tries to re-establish given API connection with exponential falloff.
	"""
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

def bluesky_post_already_notified(post_uri: str) -> bool:
	"""
	Checks if the given Bluesky post URI is already stored in the database.
	"""
	try:
		if sql.check_post_match(main.TARGET_BLUESKY_ID, post_uri) is True:
			return True
		return False
	except Exception as e:
		main.logger.error(f"Error checking database if post is already notified: {e}\n")
		return False

def bluesky_save_post_to_db(post_uri: str, content: str) -> None:
	"""
	Saves the Bluesky post URI and content in the database.
	"""
	try:
		sql.update_latest_post(main.TARGET_BLUESKY_ID, post_uri, content)
	except Exception as e:
		main.logger.error(f"Error saving post to database: {e}\n")


def convert_bluesky_uri_to_url(at_uri: str):
	"""
	Converts a Bluesky AT URI (at://<DID>/<COLLECTION>/<RKEY>) into a valid web URL.
	Example:
	Input: at://did:plc:abcd1234/app.bsky.feed.post/xyz987
	Output: https://bsky.app/profile/did:plc:abcd1234/post/xyz987
	"""
	# Bluesky URI format: at://<DID>/<COLLECTION>/<RKEY>
	# match = re.match(r"at://([^/]+)/([^/]+)/([^/]+)", at_uri)
	match = URI_TO_URL_REGEX.match(at_uri)

	if match:
		did = match.group(1)  # Extract DID
		collection = match.group(2)  # Extract Collection Type
		rkey = match.group(3)  # Extract Record Key

		# Check if the URI belongs to a post
		if collection == "app.bsky.feed.post":
			return f"https://bsky.app/profile/{did}/post/{rkey}"
	
	return None  # Return None if the URI is invalid or not a post

def extract_media(post: any) -> list:
	"""
	Extracts image URLs from a Bluesky post, if available.
	"""
	images = []

	# find and extract DID of author
	did = getattr(post, "author", None) and getattr(post.author, "did", None)
	if not did and hasattr(post, "uri"):
		# regex DID from at://URI
		match = re.match(r"at://([^/]+)/", post.uri)
		if match:
			did = match.group(1)

	if hasattr(post.record, "embed") and hasattr(post.record.embed, "images"):
		try:
			for image in post.record.embed.images:
				if hasattr(image, "image") and hasattr(image.image, "ref"):
					link = getattr(image.image.ref, "link", None)
					mime_type = getattr(image.image, "mime_type", "jpeg").split("/")[-1]
					if link:
						if link and did:
							# Construct public image URL with DID and file extension
							image_url = f"https://cdn.bsky.app/img/feed_thumbnail/plain/{did}/{link}@{mime_type}"
							images.append(image_url)
		except Exception as e:
			main.logger.info(f"Error extracting media from post: {e}\n")
	return images if images else []

def extract_links(post: any) -> list:
	"""
	Extracts full URLs from a Bluesky post's facets.
	"""
	full_links = []
	# Ensure facets (hyperlinks etc.) exist
	if post.record and post.record.facets:  
		try:
			for facet in post.record.facets:
				# redundancy check
				if facet.features:
					for feature in facet.features:
						# Find specifically the URI element, otherwise nothing is appended.
						try:
							uri = getattr(feature, "uri", None)
							if feature.uri and hasattr(feature, "uri"):
								full_links.append(feature.uri)
						except Exception as e:
							continue	# means that URI element was not found, meaning other type of link?
										# might be important later
		except Exception as e:
			main.logger.info(f"Error extracting links from post: {e}\n")
	return full_links if full_links else []

def replace_urls(text: str, links: list) -> str:
	"""
	Replaces truncated URLs in text with full URLs.
	NOTE: Currently used to remove truncated URLs from text, as they are posted separately to enable previews.
	"""
	truncated_links = extractor.find_urls(text)
	# Replace truncated links with full URLs
	if truncated_links and links:
		# match short links with full links, replace in text
		for short_link, full_link in zip(truncated_links, links):
			text = text.replace(short_link, "")
			# text = text.replace(short_link, f"[🔗 {short_link}]({full_link})")
	return text

#
#	Bluesky post sharing task
#

@reconnect_api_with_backoff()
async def fetch_bluesky_posts():
	"""
	Fetches the latest Bluesky posts from the API.
	"""
	try:
		feed = client.get_author_feed(actor=main.TARGET_BLUESKY_ID, limit=postFetchCount)
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

async def share_bluesky_posts() -> None:
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
					content = replace_urls(post['text'], post['links'])
					images = post['post_images']
					links = post['links']
					# skip if already sent
					if (bluesky_post_already_notified(post_uri)):
						break
					# Send notification to all whitelisted Discord channels
					await bot.notify_bluesky_activity(post_uri, content, images, links)
					# Save the post URI and content to the database
					bluesky_save_post_to_db(post_uri, content)
		except Exception as e:
			main.logger.info(f"Error sharing Bluesky posts: {e}\n")

		# Wait for 10 seconds before checking again
		await asyncio.sleep(10)
