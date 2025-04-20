import discord
import asyncio
from discord.ext import commands

import main
import blsky
import youtube
import sql

# Discord bot setup
intents = discord.Intents.default()
intents.messages = True # allow bot to read messages
intents.message_content = True # allow bot to read message content
bot = commands.Bot(command_prefix='!', intents=intents)

# track the bluesky/youtube task so we can cancel it
bluesky_task = None
youtube_task = None

#
#	Discord bot helper & debug functions
#

async def bot_internal_message(message: str) -> None:
	"""
	Sends a message to the home/debug channel only.
	"""
	try:
		# The channels are fetched during startup, no need to async call them now
		homeGuild = discord.utils.get(bot.guilds, id=main.HOME_SERVER_ID)
		homeChannel = discord.utils.get(homeGuild.text_channels, id=main.HOME_CHANNEL_ID)
		await homeChannel.send(f"{message}")
	except Exception as e:
		main.logger.error(f"Failed to send a message to the home channel.\n")


async def load_cogs() -> None:
	"""
	Loads all the discord bot cogs.
	"""
	try:
		await bot.load_extension("cogs.admin")
		await bot.load_extension("cogs.notifications")

	except commands.errors.ExtensionAlreadyLoaded:
		main.logger.info(f"Cog already loaded.\n")
	except commands.errors.ExtensionNotFound:
		main.logger.error(f"Cog not found.\n")
	except Exception as e:
		raise e

#
#	Discord bot events & startup
#

@bot.event
async def on_ready() -> None:
	global bluesky_task
	global youtube_task
	# Connect to home (debug) server and channel
	try:
		homeGuild = discord.utils.get(bot.guilds, id=main.HOME_SERVER_ID)
		if not homeGuild:
			main.logger.info(f"Home server not found! Please check the server ID in the .env file.\n")
		homeChannel = await bot.fetch_channel(main.HOME_CHANNEL_ID)
		if not homeChannel:
			main.logger.info(f"Home channel not found! Please check the channel ID in the .env file.\n")
		else:
			main.logger.info(f"Connected to home channel: {homeChannel.name}\n")
			await homeChannel.send(f"Dreamcatcher is now online! 💭")
			main.logger.info(f"Bot is ready! Logged in as {bot.user.name}#{bot.user.discriminator}\n")

		# Loads the slash commands
		await load_cogs()

		# Start the Bluesky post sharing task
		if bluesky_task is None or bluesky_task.done():
			bluesky_task = asyncio.create_task(blsky.share_bluesky_posts())
			#bluesky_task = bot.loop.create_task(blsky.share_bluesky_posts())
		
		if youtube_task is None or youtube_task.done():
			youtube_task = asyncio.create_task(youtube.check_for_youtube_activities())

	except Exception as e:
		main.logger.error(f"Error connecting to home server: {e}\n")

@bot.event
async def on_resumed():
	global bluesky_task
	global youtube_task

	if bluesky_task is None or bluesky_task.done():
		try:
			bluesky_task = asyncio.create_task(blsky.share_bluesky_posts())
			#await bot_internal_message(f"Bot resumed, spinning bluesky task back up again...\n")
		except Exception as e:
			main.logger.error(f"Error resuming Bluesky task by Discord bot: {e}\n")

	if youtube_task is None or youtube_task.done():
		try:
			youtube_task = asyncio.create_task(youtube.check_for_youtube_activities())
			#await bot_internal_message(f"Bot resumed, spinning youtube task back up again...\n")
		except Exception as e:
			main.logger.error(f"Error resuming Youtube task by Discord bot: {e}\n")


@bot.event
async def on_disconnect():
	global bluesky_task
	global youtube_task
	main.logger.info(f"Bot is disconnecting... cleaning up tasks.\n")

	# cancel Bluesky task if its running
	if bluesky_task and not bluesky_task.done():
		bluesky_task.cancel()
		try:
			await bluesky_task
		except asyncio.CancelledError:
			main.logger.error("Bluesky task cancelled.\n")
	
	if youtube_task and not youtube_task.done():
		youtube_task.cancel()
		try:
			await youtube_task
		except asyncio.CancelledError:
			main.logger.error("Youtube task cancelled.\n")

@bot.event
async def on_shutdown():
	global bluesky_task
	global youtube_task
	main.logger.info(f"Bot shutdown requested, cleaning up resources...\n")

	# cancel Bluesky task if its running
	if bluesky_task and not bluesky_task.done():
		bluesky_task.cancel()
		try:
			await bluesky_task
		except asyncio.CancelledError:
			main.logger.error("Bluesky task cancelled.\n")
	
	if youtube_task and not youtube_task.done():
		youtube_task.cancel()
		try:
			await youtube_task
		except asyncio.CancelledError:
			main.logger.error("Youtube task cancelled.\n")

	await bot.close()

#
#	Discord bot notification functions
#

async def notify_youtube_activity(target_channel: str, activity_type: str, channel_name: str, video_id: str) -> None:
	channel = await bot.fetch_channel(int(target_channel))
	if channel and channel.permissions_for(channel.guild.me).send_messages:
		# Use channel.id instead of channel.guild.id
		notify_role = sql.get_notification_role(channel.id)
		ping_role = ""
		if notify_role:
			main.logger.info(f"Notification role found: {notify_role}\n")
			ping_role = f"<@&{notify_role}> "
		try:
			video_url = f"https://www.youtube.com/watch?v={video_id}"
			if activity_type == "upload":
				await channel.send(
					f"{ping_role}**{channel_name} just uploaded a new video!** 💭\n"
					f"{video_url}"
				)
			elif activity_type == "liveStreamSchedule":
				await channel.send(
					f"{ping_role}**{channel_name} just scheduled a new stream!** 🔔\n"
					f"{video_url}"
				)
			elif activity_type == "liveStreamNow":
				await channel.send(
					f"{ping_role}**{channel_name} is now live!** 🔴\n"
					f"{video_url}"
				)	
		except Exception as e:
			main.logger.error(f"Error sending message to channel {channel.name}: {e}\n")
	else:
		main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}\n")

async def notify_bluesky_activity(target_channel: str, post_uri: str, content: str, images: list, links: list) -> None:
	channel = await bot.fetch_channel(int(target_channel))
	# check if the bot has permission to send messages in the channel
	if channel and channel.permissions_for(channel.guild.me).send_messages:
		notify_role = sql.get_notification_role(channel.id)
		ping_role = ""
		if notify_role:
			ping_role = f"<@&{notify_role}> "
		try:
			# Create embed for better formatting
			post_url = blsky.convert_bluesky_uri_to_url(post_uri)
			embed = discord.Embed(
				title="🦋 New Bluesky Post!",
				description=content,
				color=discord.Color.blue(),
				url=post_url,
				timestamp = discord.utils.utcnow()
			)
			embed.set_author(name="Nimi Nightmare 💭",
				icon_url="https://cdn.bsky.app/img/avatar/plain/did:plc:mqa7bk3vtcfkh4y6xzpxivy6/bafkreicg73sfqnrrasx6xprjxkl2evhz3qmzpchhafesw6mnscxrp45g2q@jpeg"
			)
			embed.set_thumbnail(
				url="https://cdn.bsky.app/img/avatar/plain/did:plc:mqa7bk3vtcfkh4y6xzpxivy6/bafkreicg73sfqnrrasx6xprjxkl2evhz3qmzpchhafesw6mnscxrp45g2q@jpeg"
			)
			if images:
				# Show the first image in the embed post
				embed.set_image(url=images[0])
				await channel.send(
					embed=embed
				)
			# Send the actual embed image
			await channel.send(
				content=f"{ping_role}",
				embed=embed
			)
			# If multiple images exist, send them separately, ignoring the first one
			if len(images) > 1:
				for image in images[1:]:
					# Send additional images as normal messages
					await channel.send(image)
			# Post extracted links after embed message to generate previews correctly
			if links:
				for link in links:
					await channel.send(f"🔗{link}")

		except Exception as e:
			main.logger.info(f"Error sending Bluesky post to channel {channel.name}: {e}\n")
	else:
		main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}\n")
