import discord
from discord.ext import commands
from discord import app_commands

import main
import bot

class Notifications(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	@app_commands.command(name="subscribe", description="Subscribe the current or given channel to receive upcoming stream notifications.")
	async def add_channel_notifications(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			try:
				moderation_role = await bot.get_manager_role(targetChannel.guild.id)
				if moderation_role is None:
					await interaction.response.send_message(f"Please set a role that will have permission to manage the bot by typing `/setup @role`.")
					main.logger.info(f"[BOT.COMMAND] Tried to set channel subscription without moderation role in {targetChannel.name}\n",
					  ephemeral=True)
					return
				user_role_ids = [role.id for role in interaction.user.roles]
				if moderation_role not in user_role_ids:
					await interaction.response.send_message(f"Only users with the {moderation_role} role can subscribe channels.")
					main.logger.info(f"[BOT.COMMAND] User {interaction.user.id} tried to set channel subscription without moderation role in {targetChannel.name}\n",
					  ephemeral=True)
					return

			except Exception as e:
				main.logger.error(f"[BOT.COMMAND.ERROR] Error getting moderation role: {e}\n")

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

async def setup(bot):
	await bot.add_cog(Notifications(bot))
	main.logger.info(f"Notifications cog loaded!\n")
