import asyncio
import functools
import re
import urlextract
from atproto import Client

import main
import bot
import sql
from reconnect_decorator import reconnect_api_with_backoff

postFetchCount = 5 # number of posts to fetch from Bluesky API per API call. (More than one is necessary if multiple posts are made in a short time)
postFetchTimer = 60 # time in seconds to wait before fetching new posts.

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

# --------------------------------- BLUESKY API INTEGRATION ---------------------------------#

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

@reconnect_api_with_backoff(initialize_bluesky_client, "Bluesky")
async def fetch_bluesky_profile(channel_id):
	"""
	Fetches the profile (display name & avatar) of the target Bluesky user.
	"""
	try:
		profile = client.get_profile(channel_id)
		if profile:
			display_name = profile.display_name
			avatar_url = profile.avatar
			return {"display_name": display_name, "avatar_url": avatar_url}
		else:
			return None

	except Exception as e:
		main.logger.error(f"Error fetching Bluesky profile: {e}\n")
		return None



@reconnect_api_with_backoff(initialize_bluesky_client, "Bluesky")
async def fetch_bluesky_posts(channel_id):
	"""
	Fetches the latest Bluesky posts from the API.
	"""
	try:
		feed = client.get_author_feed(actor=channel_id, limit=postFetchCount)
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
			# Fetch all YouTube subscriptions from the database
			bluesky_subscriptions = sql.get_all_social_media_subscriptions_for_platform("Bluesky")
			for channel_id in bluesky_subscriptions:

				internal_id = sql.get_id_for_channel_url(channel_id)

				# Fetch posts from Bluesky
				posts = await fetch_bluesky_posts(channel_id)
				if not posts:
					continue

				last_post_id = sql.get_latest_post_id(internal_id)
				# Filter posts to include only those more recent than the stored post
				new_posts = []
				for post in posts:
					if post['uri'] == last_post_id:
						break
					new_posts.append(post)
				# if no new posts, skip to next channel
				if len(new_posts) == 0:
					continue
				main.logger.info(f"Found {len(new_posts)} new posts for Bluesky channel {channel_id}...\n")
				# get profile information for the channel
				profile = await fetch_bluesky_profile(channel_id)

				# Post new posts to Discord in reverse order (oldest first)
				for post in reversed(new_posts):
					post_uri = post['uri']
					content = replace_urls(post['text'], post['links'])
					images = post['post_images']
					links = post['links']

					notify_list = sql.get_discord_channels_for_social_channel(internal_id)
					for discord_channel in notify_list:
						main.logger.info(f"Sending Bluesky post {post_uri} to Discord channel {discord_channel}...\n")
						await bot.notify_bluesky_activity(
							discord_channel,
							post_uri,
							content,
							images,
							links,
							profile.get("display_name"),
							profile.get("avatar_url")
						)

				# Update the database with the most recent post ID (first in the new_posts list)
				if new_posts:
					most_recent_post = new_posts[0]  # The first post in new_posts is the most recent
					sql.update_latest_post(internal_id, most_recent_post['uri'], most_recent_post['text'])

		except Exception as e:
			main.logger.error(f"Error while fetching Bluesky subscriptions or fetching posts: {e}\n")

		# Wait before fetching new posts
		await asyncio.sleep(postFetchTimer)
