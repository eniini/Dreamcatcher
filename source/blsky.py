import asyncio
import re
import urlextract
from atproto import Client
from atproto import models

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

def convert_bluesky_uri_to_video_url(at_uri: str):
	"""
	Converts a Bluesky AT URI to a direct video embed URL for Discord (d.bksye.app).
	"""
	match = URI_TO_URL_REGEX.match(at_uri)
	if match:
		did = match.group(1)
		rkey = match.group(3)
		try:
			# Attempt to fetch the public handle for the DID
			profile = client.get_profile(did)
			handle = getattr(profile, 'handle', None)
			if handle:
				return f"https://d.bskye.app/profile/{handle}/post/{rkey}"
		except Exception:
			pass
		# Fallback to DID if handle not found
		return f"https://d.bskye.app/profile/{did}/post/{rkey}"
	return None

def extract_media(post: any) -> list | None:
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
		return images if images else None

def contains_video(post: any) -> bool:
	"""
	Extracts video URL from a Bluesky post if it contains a video embed.
	"""
	record = getattr(post, "record", None)
	if not record:
		return False
	embed = getattr(record, "embed", None)
	if not embed:
		return False

	# Case 1: Direct video embed
	if isinstance(embed, models.AppBskyEmbedVideo.Main):
		return True
	# Case 2: RecordWithMedia containing video
	elif isinstance(embed, models.AppBskyEmbedRecordWithMedia.Main):
		return True
	else:
		return False

def extract_external_embed(post: any) -> dict | None:
	"""
	Extracts external embed data (link preview) from a Bluesky post.
	Returns a dict with uri, title, description, and thumb if available.
	"""
	record = getattr(post, "record", None)
	embed = getattr(record, "embed", None)

	if not embed:
		return None

	# External link preview
	if getattr(embed, "$type", None) == "app.bsky.embed.external":
		ext = embed.external
		return {
			"uri": getattr(ext, "uri", None),
			"title": getattr(ext, "title", None),
			"description": getattr(ext, "description", None),
			"thumb": getattr(ext.thumb, "ref", None) if getattr(ext, "thumb", None) else None
		}
	return None

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
	if not text:
		return ""
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
			display_name = getattr(profile, 'display_name', None)
			avatar_url = getattr(profile, 'avatar', None)
			did = getattr(profile, 'did', None)
			return {"display_name": display_name, "avatar_url": avatar_url, "did": did}
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
			reply_parent_uri = None
			reply_parent_did = None

			# check if post is a reply
			if hasattr(item.post.record, "reply") and item.post.record.reply:
				reply_parent_uri = item.post.record.reply.parent.uri
				reply_parent_did = item.post.record.reply.parent.uri.split("/")[2]  # DID from at://

			# Robust repost detection (per Bluesky spec)
			is_repost = isinstance(
				item.reason,
				models.AppBskyFeedDefs.ReasonRepost
			)
			if (is_repost):
				reposter = item.reason.by.handle
				original_author = item.post.author.handle

			# Quote post detection
			is_quote = False
			record = item.post.record
			is_quote = isinstance(
				record.embed,
				models.AppBskyEmbedRecord.Main) or isinstance(
				record.embed,
				models.AppBskyEmbedRecordWithMedia.Main
			)

			#has_text = bool(getattr(record, "text", "").strip())
			#has_embed = hasattr(record, "embed") and record.embed is not None

			posts.append({
				"text": getattr(item.post.record, "text", ""),
				"uri": item.post.uri,
				"post_images": extract_media(item.post),
				"video": contains_video(item.post),
				"external": extract_external_embed(item.post),
				"links": extract_links(item.post),
				"reply_parent_uri": reply_parent_uri,
				"reply_parent_did": reply_parent_did,
				"is_repost": is_repost,
				"is_quote": is_quote,
				"repost_author": original_author if is_repost else None
			})
		return posts
	except Exception as e:
		main.logger.error(f"Error fetching Bluesky posts: {e}\n")
		return None

@reconnect_api_with_backoff(initialize_bluesky_client, "Bluesky")
async def fetch_bluesky_post_by_uri(uri: str):
	"""
	Directly fetches a single Bluesky post by its URI.
	"""
	try:
		record = client.get_post_thread(uri)
		parent = record.thread.post

		return {
			"text": parent.record.text,
			"uri": parent.uri,
			"images": extract_media(parent),
			"video": contains_video(parent),
			"external": extract_external_embed(parent),
			"links": extract_links(parent),
			"author_did": parent.author.did,
			"author_name": parent.author.display_name,
			"author_avatar": parent.author.avatar
		}
	except Exception as e:
		main.logger.error(f"Failed to fetch parent post {uri}: {e}")
		return None

async def share_bluesky_posts() -> None:
	main.logger.info(f"Starting the Bluesky post sharing task...\n")

	first_run = True

	while True:
		try:
			# Fetch all YouTube subscriptions from the database
			bluesky_subscriptions = sql.get_all_social_media_subscriptions_for_platform("Bluesky")
			for channel_id in bluesky_subscriptions:

				internal_id = sql.get_id_for_channel_url(channel_id)

				# Keep track of already shared post URIs to avoid duplicates for reposts and replies.
				posted_post_uris = set()

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
				profile_did = profile.get("did") if profile else None

				# Post new posts to Discord in reverse order (oldest first)
				if not main.startup.silent:
					for post in reversed(new_posts):
						post_uri = post['uri']
						contains_video = True if (post.get("video") == True) else False
						post_type = "root"
						notify_list = sql.get_discord_channels_for_social_channel(internal_id)
						profile_display_name = profile.get("display_name") if profile else None
						profile_avatar_url = profile.get("avatar_url") if profile else None

						# Skip if we've already shared this post (repost or reply)
						if post_uri in posted_post_uris:
							continue

						# Determine post type (repost, reply, self_reply, etc.)
						if post['is_repost']:
							post_type = "repost"
						if post["reply_parent_uri"]:
							post_type = "reply"
							if profile_did and post["reply_parent_did"] == profile_did:
								post_type = "self_reply"
							else:
								parent_uri = post["reply_parent_uri"]
								if parent_uri not in posted_post_uris:
									parent_post = await fetch_bluesky_post_by_uri(parent_uri)
									if parent_post:
										posted_post_uris.add(parent_uri)
										for discord_channel in notify_list:
											parent_has_video = parent_post.get("video")
											if parent_has_video:
												await bot.notify_bluesky_activity(
													target_channel = discord_channel,
													post_uri = parent_post["uri"],
													content = None,
													images = None,
													links = [convert_bluesky_uri_to_url(parent_post["uri"])],
													channel_name = parent_post["author_name"],
													avatar_url = profile_avatar_url,
													post_type = "parent_post",
													author_url = parent_post["author_avatar"]
												)
											else:
												await bot.notify_bluesky_activity(
													target_channel = discord_channel,
													post_uri = parent_post["uri"],
													content = parent_post["text"],
													images = parent_post["images"],
													links = parent_post["links"],
													channel_name = parent_post["author_name"],
													avatar_url = profile_avatar_url,
													post_type = "parent_post",
													author_url = parent_post["author_avatar"]
												)

						posted_post_uris.add(post_uri)

						for discord_channel in notify_list:
							repost_profile = await fetch_bluesky_profile(post["repost_author"]) if post["repost_author"] else None

							main.logger.info(f"Sending Bluesky post {post_uri} to Discord channel {discord_channel}...\n")
							if contains_video:
								video_url = convert_bluesky_uri_to_video_url(post_uri)
								await bot.notify_bluesky_activity(
									target_channel = discord_channel,
									post_uri = post_uri,
									content = replace_urls(post['text'], post['links']),
									images = post['post_images'],
									links = [video_url],
									channel_name = profile_display_name,
									avatar_url = profile_avatar_url, # Reposting user's avatar to maintain consistency/context
									post_type = post_type,
									author_url = repost_profile.get("avatar_url") if repost_profile else None
								)
							elif post_type == "repost":
								
								await bot.notify_bluesky_activity(
									target_channel = discord_channel,
									post_uri = post_uri,
									content = replace_urls(post['text'], post['links']),
									images = post['post_images'],
									links = post['links'],
									channel_name = repost_profile.get("display_name"),
									avatar_url = profile_avatar_url, # Reposting user's avatar to maintain consistency/context
									post_type = "repost",
									author_url = repost_profile.get("avatar_url") if repost_profile else None
								)
							else:
								external = post.get("external")
								links = post['links']
								if external and external.get("uri"):
									if links is not None:
										links = list(links)
										links.append(external["uri"])
									else:
										links = [external["uri"]]
								await bot.notify_bluesky_activity(
									target_channel = discord_channel,
									post_uri = post_uri,
									content = replace_urls(post['text'], post['links']),
									images = post['post_images'],
									links = links,
									channel_name = profile_display_name,
									avatar_url = profile_avatar_url,
									post_type = post_type,
									author_url = None
								)
				else:
					main.logger.info(f"Skipping notification for Bluesky posts due to silent start.\n")
				# First run silent start handling: if this is first time the loop is run since startup, actually notifying about posts is skipped
				# and this asyncio task signals the StartupSilencer that it has finished the silent loop.
				if first_run:
					if hasattr(main, "startup") and main.startup.silent:
						await main.startup.task_finished_first_run()
					first_run = False
					main.logger.info(f"Finished first run of Bluesky post sharing task.\n")

				# Update the database with the most recent post ID (first in the new_posts list)
				if new_posts:
					most_recent_post = new_posts[0]  # The first post in new_posts is the most recent
					sql.update_latest_post(internal_id, most_recent_post['uri'], most_recent_post['text'])

		except Exception as e:
			main.logger.error(f"Error while fetching Bluesky subscriptions or fetching posts: {e}\n")

		# Wait before fetching new posts
		await asyncio.sleep(postFetchTimer)
