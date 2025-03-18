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
		hub_mode: str = Query(None),
		hub_challenge: str = Query(None),
		hub_topic: str = Query(None)
	):
	"""
	Handles YouTube Web Sub (PubSubHubbub) verification challenge.
	"""
	if hub_mode == "subscribe" and hub_challenge:
		return {"hub.challenge": hub_challenge} # Return the challenge to verify the subscription
	return "Invalid request"

@web.fastAPIapp.post("/youtube-webhook")
async def youtube_webhook(request: Request):
	"""
	Receives YouTube Web Sub notifications when a new video is posted.
	"""
	data = await request.body()
	# parse received XMl data
	root = ET.fromstring(data)

	# check if the notification is for a new video
	# TODO: could also handle activityId for other types of notifications

	for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
		#activity_id = entry.find('{http://www.youtube.com/xml/schemas/2015}activityId').text
		video_url = entry.find("{http://www.w3.org/2005/Atom}link").attrib["href"]
		video_id = video_url.split("v=")[-1]
		#video_id = entry.find("{http://www.w3.org/2005/Atom}link").attrib["href"].split("/")[-1]
		channel_id = entry.find("{http://www.w3.org/2005/Atom}author").find("{http://www.w3.org/2005/Atom}uri").text.split("/")[-1]
		title = entry.find("{http://www.w3.org/2005/Atom}title").text

		main.logger.info(f"New video from channel {channel_id}: {video_id}\n")

		# check if post was already notified/processed
		if sql.check_post_match(channel_id, video_id):
			main.logger.info(f"Video {video_id} already notified, skipping...\n")
			return {"status": "ignored"}
 
		# save the post to database and notify discord bot
		try:
			sql.update_latest_post(channel_id, video_id, video_url, datetime.now(datetime.timezone.utc).isoformat())
		except Exception as e:
			main.logger.error(f"Error updating latest YouTube ({channel_id}) post into database: {e}")
			return {"status": "error"}
		
		await bot.notify_youtube_activity(
			activity_type="upload",		#todo: tag for correct content type (upload, livestream, post)
			title=title,
			published_at="now",			#todo: get utc timestamp
			video_id=video_id,
			post_text=None				#todo: add if community postt
		)

	# notify discord bot about video...

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
	try:
		sql.add_social_media_channel("YouTube", channel_id, None)
	except Exception as e:
		main.logger.error(f"Error adding YouTube channel ({channel_id}) subscription into database: {e}")
		return 500, "Internal Server Error"
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