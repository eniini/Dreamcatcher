import discord
from discord.ext import commands

import main
import blsky
import youtube

# Discord bot setup
intents = discord.Intents.default()
intents.messages = True # allow bot to read messages
intents.message_content = True # allow bot to read message content
bot = commands.Bot(command_prefix='!', intents=intents)

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
		bot.loop.create_task(blsky.share_bluesky_posts())

		# Start the YT activity checking task
		bot.loop.create_task(youtube.check_for_youtube_activities())

	except Exception as e:
		main.logger.error(f"Error connecting to home server: {e}\n")

#
#	Discord bot notification functions
#

async def notify_youtube_activity(activity_type: str, title: str, published_at: str, video_id: str, post_text: str) -> None:
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
						f"🔗 Check it out: https://www.youtube.com/channel/{main.TARGET_YOUTUBE_ID}/community"
					)
			except Exception as e:
				main.logger.error(f"Error sending message to channel {channel.name}: {e}\n")
		else:
			main.logger.info(f"Bot does not have permission to send messages in channel: {channel.name}\n")

async def notify_bluesky_activity(post_uri: str, content: str, images: list, links: list) -> None:
	whitelisted_channels = main.get_whitelisted_channels()
	
	for channel_id in whitelisted_channels:
		channel = await bot.fetch_channel(int(channel_id))
		# check if the bot has permission to send messages in the channel
		if channel and channel.permissions_for(channel.guild.me).send_messages:
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
