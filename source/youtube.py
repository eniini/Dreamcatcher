import requests
from datetime import datetime
import xml.etree.ElementTree as ET
from fastapi import Request, Query

import main
import bot
import web
import sql

global public_webhook_address
public_webhook_address = f"http://{main.PUBLIC_WEBHOOK_IP}:8000/youtube-webhook"

#
#	Webhook endpoints
#

@web.fastAPIapp.get("/youtube-webhook")
async def verify_youtube_webhook(
		hub_mode: str = Query(None, alias="hub.mode"),
		hub_challenge: str = Query(None, alias="hub.challenge"),
		hub_topic: str = Query(None, alias="hub.topic"),
	):
	"""
	Handles YouTube Web Sub (PubSubHubbub) verification challenge.
	"""
	main.logger.info(f"Received YouTube Web Sub verification request: {hub_mode}, {hub_challenge}, {hub_topic}\n")
	if hub_mode == "subscribe" and hub_challenge:
		return {"hub.challenge": hub_challenge} # Return the challenge to verify the subscription
	return "Invalid request", 400

YOUTUBE_NS = {
	"atom": "http://www.w3.org/2005/Atom",
	"yt": "http://www.youtube.com/xml/schemas/2015"
}

@web.fastAPIapp.post("/youtube-webhook")
async def youtube_webhook(request: Request):
	"""
	Receives YouTube Web Sub notifications when a new video is posted.
	"""
	data = await request.body()
	# parse received XMl data
	try:
		root = ET.fromstring(data)
	except ET.ParseError as e:
		main.logger.error(f"Error parsing XML data: {e}")
		return {"status": "error", "detail": "Invalid XML data"}

	# check if the notification is for a new video
	# TODO: could also handle activityId for other types of notifications

	for entry in root.findall("atom:entry", YOUTUBE_NS):
		# Video ID
		video_id = entry.find("yt:videoId", YOUTUBE_NS)
		video_id = video_id.text if video_id is not None else None

		# Title
		title = entry.find("atom:title", YOUTUBE_NS)
		title = title.text if title is not None else "(No title)"

		# Channel ID
		channel_id = entry.find("yt:channelId", YOUTUBE_NS)
		channel_id = channel_id.text if channel_id is not None else "UnknownChannel"

		# Video URL
		video_url = None
		for link in entry.findall("atom:link", YOUTUBE_NS):
			if link.attrib.get("rel") == "alternate":
				video_url = link.attrib.get("href")
		if not video_url and video_id:
			video_url = f"https://www.youtube.com/watch?v={video_id}"

		# Logging for debug/testing
		main.logger.info(f"Received YouTube notification: channel={channel_id}, video_id={video_id}, title={title}")

		# Safety check: skip if no video ID
		if not video_id:
			main.logger.warning("No video ID found in entry. Skipping.")
			continue

		# Lookup channel
		internal_channel_id = sql.get_id_for_channel_url(channel_id)
		if internal_channel_id is None:
			main.logger.error(f"Channel ID {channel_id} not found in database.")
			continue

		# Prevent duplicate notifications
		if sql.check_post_match(internal_channel_id, video_id):
			main.logger.info(f"Video {video_id} already notified, skipping.")
			continue
 
		# save the post to database and notify discord bot
		try:
			sql.update_latest_post(
				internal_channel_id,
				video_id,
				video_url,
				datetime.now(datetime.timezone.utc).isoformat()
			)
		except Exception as e:
			main.logger.error(f"Error updating latest YouTube ({channel_id}) post into database: {e}")
			continue
		# Get all discord channels subscribed to the YouTube channel, then notify each
		notify_list = sql.get_discord_channels_for_social_channel(internal_channel_id)
		for discord_channel in notify_list:
			await bot.notify_youtube_activity(
				target_channel=discord_channel,
				activity_type="upload",		#todo: tag for correct content type (upload, livestream, post)
				title=title,
				published_at="now",			#todo: get utc timestamp
				video_id=video_id,
				post_text=None				#todo: add if community postt
			)

	return {"status": "ok"}

#
#	POST request for Youtube Web Sub Hub
#

def subscribe_to_channel(channel_id: str, callback_url) -> tuple[int, str]:
	"""
	Subscribe to a Youtube channel's new video notifications.
	"""
	url = "https://pubsubhubbub.appspot.com/subscribe"
	data = {
		"hub.callback": callback_url,
		"hub.mode": "subscribe",
		"hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}",
		"hub.verify": "async"
	}
	response = requests.post(url, data=data)
	return response.status_code, response.text

def unsubscribe_from_channel(channel_id: str, callback_url) -> tuple[int, str]:
	"""
	Unsubscribe from a Youtube channel's new video notifications.
	"""
	url = "https://pubsubhubbub.appspot.com/subscribe"
	data = {
		"hub.callback": callback_url,
		"hub.mode": "unsubscribe",
		"hub.topic": f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}",
		"hub.verify": "async"
	}
	response = requests.post(url, data=data)
	return response.status_code, response.text