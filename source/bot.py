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

async def bot_internal_message(message):
	"""
	Sends a message to the home/debug channel only.
	"""
	try:
		homeGuild = discord.utils.get(bot.guilds, id=main.HOME_SERVER_ID)
		homeChannel = discord.utils.get(homeGuild.text_channels, id=main.HOME_CHANNEL_ID)
		await homeChannel.send(f"{message}")
	except Exception as e:
		main.logger.error(f"Failed to send a message to the home channel.\n")

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
			main.logger.info(f"Connected to home channel: {homeChannel.name}\n")
			await homeChannel.send(f"Dreamcatcher is now online! 💭")
			main.logger.info(f"Bot is ready! Logged in as {bot.user.name}#{bot.user.discriminator}\n")

		# Start the Bluesky post sharing task
		bot.loop.create_task(blsky.share_bluesky_posts())

		# Start the YT activity checking task
		bot.loop.create_task(youtube.check_for_youtube_activities())

	except Exception as e:
		main.logger.error(f"Error connecting to home server: {e}\n")

# SUBSCRIBE TO STREAM NOTIFICATIONS
@bot.command(name="subscribe", help="Subscribe the current channel to receive upcoming stream notifications.")
async def subscribe(ctx, channel: discord.TextChannel):
	try:
		if (channel):
			main.add_channel_to_whitelist(str(channel.id))
			if (channel.permissions_for(channel.guild.me).send_messages == False):
				await ctx.send(f"I don't have permission to send messages in {channel.name}. Please try subscribing again after granting the necessary permissions.")
				main.logger.info(f"[BOT.COMMAND] Bot does not have permission to send messages in {channel.name}\n")
			else:
				await ctx.send(f"{channel.name} will now receive upcoming stream notifications!")
				main.logger.info(f"[BOT.COMMAND] Channel {channel.name} subscribed...\n")
		else:
			# adding the current channel to the whitelist
			add_channel_to_whitelist(str(ctx.channel.id))
			await ctx.send("This channel will now receive upcoming stream notifications!")
			main.logger.info(f"[BOT.COMMAND] Channel {ctx.channel.name} subscribed...\n")
	except Exception as e:
		main.logger.error(f"Error subscribing discord channel for bot notifications: {e}\n")

# UNSUBSCRIBE FROM STREAM NOTIFICATIONS
@bot.command(name="unsubscribe", help="Unsubscribe the current channel from receiving upcoming stream notifications.")
async def unsubscribe(ctx, channel: discord.TextChannel):
	try:
		if (channel):
			main.remove_channel_from_whitelist(str(channel.id))
			await ctx.send(f"{channel.name} will no longer receive upcoming stream notifications!")
			main.logger.info(f"[BOT.COMMAND] Channel {channel.name} unsubscribed...\n")
		else:
			remove_channel_from_whitelist(str(ctx.channel.id))
			await ctx.send("This channel will no longer receive upcoming stream notifications!")
			logger.info(f"[BOT.COMMAND] Channel {ctx.channel.name} unsubscribed...")
	except Exception as e:
		main.logger.error(f"Error unsubscribing discord channel from bot notifications: {e}\n")

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
		main.logger.info(f"[BOT.COMMAND] YouTube API response: {response}\n")

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
		main.logger.info(f"Error fetching latest stream: {e}\n")
		await ctx.send("An error occurred while fetching the latest stream.")

async def notify_youtube_activity(activity_type, title, published_at, video_id, post_text):
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
				main.logger.error(f"Error sending message to channel {channel.name}: {e}\n")
		else:
			main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}\n")

async def notify_bluesky_activity(post_uri, content, images, links):
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
			except Exception as e:
				main.logger.info(f"Error sending Bluesky post to channel {channel.name}: {e}\n")
		else:
			main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}")