import discord
from discord.ext import commands
from discord import app_commands

import main

class Notifications(commands.Cog):
	def __init__(self, _bot):
		self._bot = _bot



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
					await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding channel to whitelist: {e}\n")

				await interaction.response.send_message(f"{targetChannel.name} will now receive upcoming stream notifications!",
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
				await interaction.response.send_message(f"Failed to unsubscribe {targetChannel.name}. Please check that the channel ID is valid.",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] Error removing channel from whitelist: Channel ID {targetChannel.id} not found.\n")
			else:
				await interaction.response.send_message(f"{targetChannel.name} will no longer receive upcoming stream notifications!",
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
				await interaction.response.send_message(f"{targetChannel.name} is currently subscribed to receive upcoming stream notifications!",
					ephemeral=True)
			else:
				await interaction.response.send_message(f"{targetChannel.name} is not subscribed to receive upcoming stream notifications.",
					ephemeral=True)

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error checking discord channel status: {e}\n")

async def setup(_bot):
	await _bot.add_cog(Notifications(_bot))
	main.logger.info(f"Notifications cog loaded!\n")
