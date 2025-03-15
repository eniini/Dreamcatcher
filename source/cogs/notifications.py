import discord
from discord.ext import commands
from discord import app_commands

import main
import youtube

class Notifications(commands.Cog):
	def __init__(self, _bot):
		self._bot = _bot

#
# Webhook-based subscription
#
	@app_commands.command(name="subscribe_youtube_channel", description="Subscribe a discord channel to receive notifications from a YouTube channel.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def subscribe_youtube_channel(self, interaction: discord.Interaction, youtube_channel_id: str, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			# check if the bot has permission to send messages to the target channel
			if not targetChannel.permissions_for(targetChannel.guild.me).send_messages:
				await interaction.response.send_message(f"I don't have permission to send messages in {targetChannel.name}. Please try subscribing again after granting the necessary permissions.",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] Bot does not have permission to send messages in {targetChannel.name}\n")
			else:
				try:
					_targetChannel = str(targetChannel.id)
					#main.add_youtube_channel_to_whitelist(youtube_channel_id, targetChannel.id)
					if youtube.is_discord_channel_subscribed(_targetChannel) is True:
						await interaction.followup.send(f"This channel already has a YouTube channel subscribed to it. Please unsubscribe the current channel before subscribing a new one.",
							ephemeral=True)
					else:
						# Check if the YouTube channel is already subscribed to the bot, otherwise call subscription endpoint
						if youtube.get_all_subscribed_channels(_targetChannel) is not None:
							youtube.subscribe_to_channel(youtube_channel_id, youtube.public_webhook_address)
						# store the [channel, subscription] tuple in the database
						youtube.save_discord_subscription(_targetChannel, youtube_channel_id)
				except Exception as e:
					await interaction.followup.send(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding YouTube channel subscription to given channel: {e}\n")

				await interaction.followup.send(f"{targetChannel.name} will now receive notifications for YouTube channel ID {youtube_channel_id}!",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] YouTube channel ID {youtube_channel_id} subscribed to {targetChannel.name}...\n")

		except Exception as e:
			main.logger.error(f"Error subscribing YouTube channel for bot notifications: {e}\n")

	@app_commands.command(name="unsubscribe_youtube_channel", description="Unsubscribe a discord channel from receiving notifications from a YouTube channel.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def unsubscribe_youtube_channel(self, interaction: discord.Interaction, youtube_channel_id: str=None, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel
			
			# if no given youtube channel, recursively unsubscribe all YouTube channel subscriptions from the target Discord channel
			# else just unsubscribe the given YouTube channel from the target Discord channel
			if youtube_channel_id is None:
				pass
				# get all the YouTube channel subscriptions for the target Discord channel
				# subscriptions = youtube.get_all_channel_subscriptions(targetChannel.id)
				#if subscriptions is not None:
				#	for subscription in subscriptions:
				#	await youtube.remove_discord_subscription(targetChannel.id)
				#else:
				#	await interaction.response.send_message(f"No YouTube channel subscriptions found for {targetChannel.name}.",
				#		ephemeral=True)
			else:
				# await youtube.remove_discord_subscription(targetChannel.id, youtube_channel_id)
				pass
		except Exception as e:
			main.logger.error(f"Error unsubscribing Discord channel from YouTube notifications: {e}\n")


#
#	Whitelist-based subscription
#
	@app_commands.command(name="subscribe", description="Subscribe the current or given channel to receive upcoming stream notifications.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def add_channel_notifications(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			# check if the bot has permission to send messages to the target channel
			if not targetChannel.permissions_for(targetChannel.guild.me).send_messages:
				await interaction.response.send_message(f"I don't have permission to send messages in {targetChannel.name}. Please try subscribing again after granting the necessary permissions.",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] Bot does not have permission to send messages in {targetChannel.name}\n")
			else:
				try:
					main.add_channel_to_whitelist(targetChannel.id)

				except Exception as e:
					await interaction.followup.send(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding channel to whitelist: {e}\n")

				await interaction.followup.send(f"{targetChannel.name} will now receive upcoming stream notifications!",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] Channel {targetChannel.name} subscribed...\n")

		except Exception as e:
			main.logger.error(f"Error subscribing discord channel for bot notifications: {e}\n")



	@app_commands.command(name="unsubscribe", description="Unsubscribe the current or given channel from receiving upcoming stream notifications.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def remove_channel_notifications(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		targetChannel = None
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			if not main.remove_channel_from_whitelist(targetChannel.id):
				await interaction.followup.send(f"Failed to unsubscribe {targetChannel.name}. Please check that the channel ID is valid.",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] Error removing channel from whitelist: Channel ID {targetChannel.id} not found.\n")
			else:
				await interaction.followup.send(f"{targetChannel.name} will no longer receive upcoming stream notifications!",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] Channel {targetChannel.name} unsubscribed...")

		except Exception as e:
			main.logger.error(f"Error unsubscribing discord channel from bot notifications: {e}\n")



	@app_commands.command(name="check_status", description="Check if the current or given channel is receiving notifications.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def check_channel_status(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			whitelisted_channels = main.get_whitelisted_channels()
			if str(targetChannel.id) in whitelisted_channels:
				await interaction.followup.send(f"{targetChannel.name} is currently subscribed to receive upcoming stream notifications!",
					ephemeral=True)
			else:
				await interaction.followup.send(f"{targetChannel.name} is not subscribed to receive upcoming stream notifications.",
					ephemeral=True)

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error checking discord channel status: {e}\n")

async def setup(_bot):#
	await _bot.add_cog(Notifications(_bot))
	main.logger.info(f"Notifications cog loaded!\n")
