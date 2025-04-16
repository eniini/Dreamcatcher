import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

import main
import sql
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
					# Easiest way to check if the given YouTube channel ID is valid is to check if the channel name can be fetched.
					# If the channel name is None, the ID is invalid.
					youtube_channel_name = await youtube.get_channel_name(youtube_channel_id)
					if youtube_channel_name is None:
						await interaction.response.send_message(f"Invalid YouTube channel ID. Please try again.",
							ephemeral=True)
						return

					# Check if this Discord channel is already in the SQL database.
					sql.add_discord_channel(targetChannel.id, targetChannel.name)

					# Check if the given YT channel already has stored ID in database and if its already linked.
					internal_social_media_channel = sql.get_id_for_channel_url(youtube_channel_id)
					if internal_social_media_channel is not None:
						# YT channel is already in database, and is already linked to this Discord channel.
						if sql.is_discord_channel_subscribed(targetChannel.id, internal_social_media_channel) is True:
							await interaction.response.send_message(f"This channel already has a subscription to the given channel.",
								ephemeral=True)
						# YT channel is already in database, but not linked to this Discord channel.
						else:
							try:
								sql.add_subscription(targetChannel.id, internal_social_media_channel)
							except Exception as e:
								main.logger.error(f"Error adding subscription to database: {e}\n")
								await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
									ephemeral=True)
					# YT channel is not in database yet, add it.
					else:
						internal_social_media_channel = sql.add_social_media_channel("YouTube", youtube_channel_id, youtube_channel_name)
						try:
							sql.add_subscription(targetChannel.id, internal_social_media_channel)
						except Exception as e:
							main.logger.error(f"Error adding subscription to database: {e}\n")
							await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
								ephemeral=True)

				except Exception as e:
					await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding YouTube channel subscription to given channel: {e}\n")

				# Everything went ok, confirm to user
				await interaction.response.send_message(f"{targetChannel.name} will now receive notifications for YouTube channel '{youtube_channel_name}'!",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] YouTube channel '{youtube_channel_name}' subscribed to {targetChannel.name}...\n")

		except Exception as e:
			main.logger.error(f"Error subscribing YouTube channel for bot notifications: {e}\n")

	# TODO: This shouldn't require user to input the subscribed social media channel. Instead, the user should see a list of
	# active subscriptions and input all values as a reply corresponding to the list to the bot's ephemeral message.

	@app_commands.command(name="unsubscribe_channel", description="Unsubscribe a discord channel from receiving notifications from a YouTube channel.")
	@app_commands.describe(social_media_channel="The URL of the social media channel (e.g., YouTube)",
		channel="Optional: The Discord text channel to unsubscribe. Defaults to current."
	)
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def unsubscribe_channel(self, interaction: discord.Interaction, social_media_channel: Optional[str]=None, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			# If social_media_channel is provided, validate it
			if social_media_channel:
				internal_social_media_channel = sql.get_id_for_channel_url(social_media_channel)
				if internal_social_media_channel is None:
					await interaction.response.send_message(f"Invalid social media channel URL. Please try again.",
						ephemeral=True)
					return
				target_social_media_name = sql.get_channel_name(internal_social_media_channel)

				# Check if the subscription exists and remove it
				if sql.is_discord_channel_subscribed(targetChannel.id, internal_social_media_channel):
					main.logger.info(f"Removing subscription of {target_social_media_name} for channel {targetChannel.name}...\n")
					sql.remove_subscription(targetChannel.id, internal_social_media_channel)
					await interaction.response.send_message(f"Channel {targetChannel.name} subscription for {target_social_media_name} removed.",
						ephemeral=True)
				else:
					await interaction.response.send_message(f"No subscription found for {target_social_media_name} in {targetChannel.name}.",
						ephemeral=True)
			else:
				# If no social_media_channel is provided, remove all subscriptions
				main.logger.info(f"Checking for all active subscriptions for channel {targetChannel.name}...\n")
				subscriptions = sql.list_social_media_subscriptions_for_discord_channel(targetChannel.id, "Youtube")
				if subscriptions:
					main.logger.info(f"Removing all active subscriptions for channel {targetChannel.name}...\n")
					sql.remove_subscription(targetChannel.id, None)
					await interaction.response.send_message(f"All channel {targetChannel.name} subscriptions for YouTube channels removed.",
						ephemeral=True)
				else:
					await interaction.response.send_message(f"No YouTube channel subscriptions found for {targetChannel.name}.",
						ephemeral=True)
		except Exception as e:
			main.logger.error(f"Error unsubscribing Discord channel from YouTube notifications: {e}\n")

#
#	Query Discord channel subscriptions status
#

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

			subscriptions = sql.list_social_media_subscriptions_for_discord_channel(targetChannel.id)
			if subscriptions is not None:
				output = ""
				for channel_id in subscriptions:
					channel_name = sql.get_channel_name(channel_id)
					# add each channel_id, join them into a string delimited by a line break
					output += f"{channel_name}\n"
				await interaction.response.send_message(f"{targetChannel.name} is currently subscribed to receive upcoming stream notifications from the following channels:\n{output}",
					ephemeral=True)
			else:
				await interaction.response.send_message(f"{targetChannel.name} is not subscribed to any channels.",
					ephemeral=True)

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error checking discord channel status: {e}\n")

#
#	SETUP
#

async def setup(_bot):
	await _bot.add_cog(Notifications(_bot))
	main.logger.info(f"Notifications cog loaded!\n")
