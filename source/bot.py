import discord
import asyncio
from discord.ext import commands

import main
import blsky
import youtube

# Discord bot setup
intents = discord.Intents.default()
intents.messages = True # allow bot to read messages
intents.message_content = True # allow bot to read message content
bot = commands.Bot(command_prefix='!', intents=intents)

# ------------------- DISCORD BOT EVENTS -------------------
@bot.event
async def on_ready():
	# Connect to home (debug) server and channel
	try:
		homeGuild = discord.utils.get(bot.guilds, id=main.HOME_SERVER_ID)
		if not homeGuild:
			main.logger.info(f"Home server not found! Please check the server ID in the .env file.\n")
		
		homeChannel = discord.utils.get(homeGuild.text_channels, id=main.HOME_CHANNEL_ID)
		if not homeChannel:
			main.logger.info(f"Home channel not found! Please check the channel ID in the .env file.\n")
		else:
			main.logger.info(f"Connected to home channel: {homeChannel.name}")
			await homeChannel.send(f"Dreamcatcher is now online! 💭")
			main.logger.info(f"Bot is ready! Logged in as {bot.user.name}#{bot.user.discriminator}")

		# Start the Bluesky post sharing task
		bot.loop.create_task(share_bluesky_posts())

		# Start the YT activity checking task
		bot.loop.create_task(youtube.check_for_youtube_activities())

	except Exception as e:
		main.logger.error(f"Error connecting to home server: {e}")



# SUBSCRIBE TO STREAM NOTIFICATIONS
@bot.command(name="subscribe", help="Subscribe the current channel to receive upcoming stream notifications.")
async def subscribe(ctx, channel: discord.TextChannel):
	try:
		if (channel):
			main.add_channel_to_whitelist(str(channel.id))
			if (channel.permissions_for(channel.guild.me).send_messages == False):
				await ctx.send(f"I don't have permission to send messages in {channel.name}. Please try subscribing again after granting the necessary permissions.")
				main.logger.info(f"[BOT.COMMAND] Bot does not have permission to send messages in {channel.name}")
			else:
				await ctx.send(f"{channel.name} will now receive upcoming stream notifications!")
				main.logger.info(f"[BOT.COMMAND] Channel {channel.name} subscribed...")
		else:
			# adding the current channel to the whitelist
			add_channel_to_whitelist(str(ctx.channel.id))
			await ctx.send("This channel will now receive upcoming stream notifications!")
			main.logger.info(f"[BOT.COMMAND] Channel {ctx.channel.name} subscribed...")
	except Exception as e:
		main.logger.error(f"Error subscribing discord channel for bot notifications: {e}")

# UNSUBSCRIBE FROM STREAM NOTIFICATIONS
@bot.command(name="unsubscribe", help="Unsubscribe the current channel from receiving upcoming stream notifications.")
async def unsubscribe(ctx, channel: discord.TextChannel):
	try:
		if (channel):
			main.remove_channel_from_whitelist(str(channel.id))
			await ctx.send(f"{channel.name} will no longer receive upcoming stream notifications!")
			main.logger.info(f"[BOT.COMMAND] Channel {channel.name} unsubscribed...")
		else:
			remove_channel_from_whitelist(str(ctx.channel.id))
			await ctx.send("This channel will no longer receive upcoming stream notifications!")
			logger.info(f"[BOT.COMMAND] Channel {ctx.channel.name} unsubscribed...")
	except Exception as e:
		main.logger.error(f"Error unsubscribing discord channel from bot notifications: {e}")

# GET LATEST STREAM
@bot.command(name="latest_stream", help="Fetches the latest live stream from the monitored YouTube channel.")
async def latest_stream(ctx):
	try:
		# Fetch the latest live stream from the YouTube channel
		request = youtube.search().list(
			part='snippet',
			channelId=main.NIMI_YOUTUBE_ID,
			type='video',
			order='date',
			maxResults=1
		)
		response = request.execute()
		# Log the response for debugging
		main.logger.info(f"[BOT.COMMAND] YouTube API response: {response}")

		if response.get('items', []):
			item = response['items'][0]
			video_id = item['id']['videoId']
			title = item['snippet']['title']
			video_url = f"https://www.youtube.com/watch?v={video_id}"
			await ctx.send(
				f"Nimi's latest Stream was:\n"
				f"**{title}**\n"
				f"Watch here: {video_url}"
			)
		else:
			await ctx.send("No live streams are currently available.")
	except Exception as e:
		main.logger.info(f"Error fetching latest stream: {e}")
		await ctx.send("An error occurred while fetching the latest stream.")




async def share_bluesky_posts():
	main.logger.info(f"Starting the Bluesky post sharing task...\n")
	while True:
		try:
			posts = blsky.fetch_bluesky_posts()
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
					if (blsky.bluesky_post_already_notified(post_uri)):
						#logger.info(f"⚠️ Skipping duplicate post: {post_uri}")
						break
					# Send notification to all whitelisted Discord channels
					whitelisted_channels = main.get_whitelisted_channels()
					for channel_id in whitelisted_channels:
						channel = await bot.fetch_channel(int(channel_id))
						# check if the bot has permission to send messages in the channel
						if channel and channel.permissions_for(channel.guild.me).send_messages:
							try:
								# Extract possible truncated links using regex macro
								truncated_links = main.URL_REGEX.findall(content)
								# Replace truncated links with full URLs
								if truncated_links and links:
									# match short links with full links, replace in content
									for short_link, full_link in zip(truncated_links, links):
										content = content.replace(short_link, f"[🔗 {short_link}]({full_link})")
								# Create embed for better formatting
								post_url = blsky.convert_bluesky_uri_to_url(post_uri)
								embed = discord.Embed(
									title="🦋 New Bluesky Post!",
									description=content,
									color=discord.Color.blue(),
									url=post_url
								)
								embed.set_author(name="Nimi Nightmare 💭",
								icon_url="https://cdn.bsky.app/img/avatar/plain/did:plc:mqa7bk3vtcfkh4y6xzpxivy6/bafkreicg73sfqnrrasx6xprjxkl2evhz3qmzpchhafesw6mnscxrp45g2q@jpeg"
								)
								embed.set_thumbnail(url="https://cdn.bsky.app/img/avatar/plain/did:plc:mqa7bk3vtcfkh4y6xzpxivy6/bafkreicg73sfqnrrasx6xprjxkl2evhz3qmzpchhafesw6mnscxrp45g2q@jpeg")
								
								# fetch reposted image... embed.set_image(url=image_url)
								if images:
									embed.set_image(url=images[0]) # Show the first image in the post
								embed.timestamp = discord.utils.utcnow()
								await channel.send(
									embed=embed
								)
								# If multiple images exist, send them separately
								if len(images) > 1:
									for img_url in images[1:]:
										await channel.send(img_url)  # Send additional images as normal messages

								# Save the post URI and content to the database
								blsky.bluesky_save_post_to_db(post_uri, content)

							except Exception as e:
								main.logger.info(f"Error sending Bluesky post to channel {channel.name}: {e}")
						else:
							main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}")
		except Exception as e:
			main.logger.info(f"Error fetching or sending Bluesky posts: {e}")

		# Wait for 10 seconds before checking again
		await asyncio.sleep(10)


async def notify_discord(activity_type, title, published_at, video_id, post_text):
	whitelisted_channels = main.get_whitelisted_channels()
	for channel_id in whitelisted_channels:
		channel = await bot.fetch_channel(int(channel_id))
		if channel and channel.permissions_for(channel.guild.me).send_messages:
			try:
				if activity_type == "upload":
					video_url = f"https://www.youtube.com/watch?v={video_id}"
					await channel.send(
						f"**Nimi just uploaded a new video!** 💭\n"
						f"{video_url}"
					)
				elif activity_type == "liveStreamSchedule":
					video_url = f"https://www.youtube.com/watch?v={video_id}"
					await channel.send(
						f"📢 **Nimi just scheduled a new stream!** 💭\n"
						f"{video_url}"
					)
				elif activity_type == "post":
					await channel.send(
						f"📝 **Nimi just posted a new community message!** 💬\n" \
						f"_{post_text}_\n" \
						f"🔗 Check it out: https://www.youtube.com/channel/{main.NIMI_YOUTUBE_ID}/community"
					)
			except Exception as e:
				main.logger.error(f"Error sending message to channel {channel.name}: {e}")
		else:
			main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}")
