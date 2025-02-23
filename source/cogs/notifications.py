import discord
from discord.ext import commands
from discord import app_commands

import main

class Notifications(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	@app_commands.command(name="subscribe", description="Subscribe the current or given channel to receive upcoming stream notifications.")
	async def add_channel_notifications(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if (channel == None):
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			# check if the bot has permission to send messages to the target channel
			if (targetChannel.permissions_for(targetChannel.guild.me).send_messages == False):
				await interaction.response.send_message(f"I don't have permission to send messages in {targetChannel.name}. Please try subscribing again after granting the necessary permissions.")
				main.logger.info(f"[BOT.COMMAND] Bot does not have permission to send messages in {targetChannel.name}\n")
			else:
				try:
					main.add_channel_to_whitelist(targetChannel.id)
				except Exception as e:
					await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.")
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding channel to whitelist: {e}\n")
				await interaction.response.send_message(f"{targetChannel.name} will now receive upcoming stream notifications!")
				main.logger.info(f"[BOT.COMMAND] Channel {targetChannel.name} subscribed...\n")
		except Exception as e:
			main.logger.error(f"Error subscribing discord channel for bot notifications: {e}\n")

	@app_commands.command(name="unsubscribe", description="Unsubscribe the current or given channel from receiving upcoming stream notifications.")
	async def remove_channel_notifications(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		targetChannel = None
		try:
			# if no given channel, defaults to the context
			if (channel == None):
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			if (main.remove_channel_from_whitelist(targetChannel.id) != True):
				await interaction.response.send_message(f"Failed to unsubscribe {targetChannel.name}. Please check that the channel ID is valid.")
				main.logger.info(f"[BOT.COMMAND] Error removing channel from whitelist: Channel ID {targetChannel.id} not found.\n")
			else:
				await interaction.response.send_message(f"{targetChannel.name} will no longer receive upcoming stream notifications!")
				main.logger.info(f"[BOT.COMMAND] Channel {targetChannel.name} unsubscribed...")

		except Exception as e:
			main.logger.error(f"Error unsubscribing discord channel from bot notifications: {e}\n")

	@app_commands.command(name="check_status", description="Check if the current or given channel is receiving notifications.")
	async def check_channel_status(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if (channel == None):
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			whitelisted_channels = main.get_whitelisted_channels()
			if str(targetChannel.id) in whitelisted_channels:
				await interaction.response.send_message(f"{targetChannel.name} is currently subscribed to receive upcoming stream notifications!")
			else:
				await interaction.response.send_message(f"{targetChannel.name} is not subscribed to receive upcoming stream notifications.")

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error checking discord channel status: {e}\n")

async def setup(bot):
	await bot.add_cog(Notifications(bot))
	main.logger.info(f"Notifications cog loaded!\n")
