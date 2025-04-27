import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from atproto import Client
from atproto import exceptions

import main
import sql
import youtube
import twitch

class Notifications(commands.Cog):
	def __init__(self, _bot):
		self._bot = _bot

	client = Client()

	def text_channel_only():
		def predicate(interaction: discord.Interaction) -> bool:
			if not isinstance(interaction.channel, discord.TextChannel):
				raise app_commands.CheckFailure("This command can only be used in text channels.")
			return True
		return app_commands.check(predicate)



	@app_commands.command(name="add_bluesky_subscription", description="Subscribe a discord channel to receive notifications from a Bluesky profile.")
	@app_commands.describe(bluesky_channel_id="The ID of the Bluesky profile. This is usually in the format of 'username.bsky.social'", channel="Optional: The Discord text channel to unsubscribe. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
	async def subscribe_bluesky_channel(self, interaction: discord.Interaction, bluesky_channel_id: str, channel: discord.TextChannel=None):
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
					# Use the Atproto client to check if the Bluesky channel ID is valid
					# basic resolve_handle() call shouldn't need login/auth
					try:
						is_valid_channel = self.client.resolve_handle(bluesky_channel_id)
						if is_valid_channel is None:
							await interaction.response.send_message(f"Invalid Bluesky channel ID. Please try again.",
								ephemeral=True)
							return
					except exceptions.AtProtocolError as e:
						await interaction.response.send_message(f"Invalid Bluesky channel ID. Please try again.",
							ephemeral=True)
						return

					# Check if this Discord channel is already in the SQL database.
					sql.add_discord_channel(targetChannel.id, targetChannel.name)

					# Check if the given Bluesky channel already has stored ID in database and if its already linked.
					internal_social_media_channel = sql.get_id_for_channel_url(bluesky_channel_id)
					if internal_social_media_channel is not None:
						# Bluesky channel is already in database, and is already linked to this Discord channel.
						if sql.is_discord_channel_subscribed(targetChannel.id, internal_social_media_channel) is True:
							await interaction.response.send_message(f"This channel already has a subscription to the given channel.",
								ephemeral=True)
						# Bluesky channel is already in database, but not linked to this Discord channel.
						else:
							try:
								sql.add_subscription(targetChannel.id, internal_social_media_channel)
							except Exception as e:
								main.logger.error(f"Error adding subscription to database: {e}\n")
								await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
									ephemeral=True)
					# Bluesky channel is not in database yet, add it.
					else:
						internal_social_media_channel = sql.add_social_media_channel("Bluesky", bluesky_channel_id, bluesky_channel_id)
						try:
							sql.add_subscription(targetChannel.id, internal_social_media_channel)
						except Exception as e:
							main.logger.error(f"Error adding subscription to database: {e}\n")
							await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
								ephemeral=True)
				except Exception as e:
					await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding Bluesky channel subscription to given channel: {e}\n")
			
			# Everything went ok, confirm to user
			await interaction.response.send_message(f"{targetChannel.name} will now receive notifications for Bluesky channel *{bluesky_channel_id}*!",
				ephemeral=True)
			main.logger.info(f"[BOT.COMMAND] Bluesky channel [{bluesky_channel_id}] subscribed to {targetChannel.name}...\n")
		
		except Exception as e:
			main.logger.error(f"Error subscribing Bluesky channel for bot notifications: {e}\n")



	@app_commands.command(name="add_twitch_subscription", description="Subscribe a discord channel to receive notifications from a Twitch channel.")
	@app_commands.describe(twitch_channel_name="Channel name (http:://www.twitch.tv/[channel])", channel="Optional: The Discord text channel to unsubscribe. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
	async def subscribe_twitch_channel(self, interaction: discord.Interaction, twitch_channel_name: str, channel: discord.TextChannel=None):
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
					# Twitch verification logic here
					twitch_channel_id = None
					twitch_channel_id = await twitch.verify_twitch_channel(twitch_channel_name)
					if twitch_channel_id is None:
						await interaction.response.send_message(f"Invalid Twitch channel ID. Please try again.",
							ephemeral=True)
						return

					# Check if this Discord channel is already in the SQL database.
					sql.add_discord_channel(targetChannel.id, targetChannel.name)

					# Check if the given Twitch channel already has stored ID in database and if its already linked.
					internal_social_media_channel = sql.get_id_for_channel_url(twitch_channel_id)
					if internal_social_media_channel is not None:
						# Twitch channel is already in database, and is already linked to this Discord channel.
						if sql.is_discord_channel_subscribed(targetChannel.id, internal_social_media_channel) is True:
							await interaction.response.send_message(f"This channel already has a subscription to the given channel.",
								ephemeral=True)
						# Twitch channel is already in database, but not linked to this Discord channel.
						else:
							try:
								sql.add_subscription(targetChannel.id, internal_social_media_channel)
							except Exception as e:
								main.logger.error(f"Error adding subscription to database: {e}\n")
								await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
									ephemeral=True)
					# Twitch channel is not in database yet, add it.
					else:
						internal_social_media_channel = sql.add_social_media_channel("Twitch", twitch_channel_id, twitch_channel_name)
						try:
							sql.add_subscription(targetChannel.id, internal_social_media_channel)
						except Exception as e:
							main.logger.error(f"Error adding subscription to database: {e}\n")
							await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
								ephemeral=True)

				except Exception as e:
					await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding Twitch channel subscription to given channel: {e}\n")
		except Exception as e:
			main.logger.error(f"Error subscribing Twitch channel for bot notifications: {e}\n")


	@app_commands.command(name="add_youtube_subscription", description="Subscribe a discord channel to receive notifications from a YouTube channel.")
	@app_commands.describe(youtube_channel_id="ID of the YT channel. Use 'Copy channel ID' inside YT channel descriptions' 'Share channel' button.", channel="Optional: The Discord text channel to unsubscribe. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
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
				await interaction.response.send_message(f"{targetChannel.name} will now receive notifications for YouTube channel *{youtube_channel_name}*!",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] YouTube channel '{youtube_channel_name}' subscribed to {targetChannel.name}...\n")

		except Exception as e:
			main.logger.error(f"Error subscribing YouTube channel for bot notifications: {e}\n")



	@app_commands.command(name="remove_subscription", description="Unsubscribe the given discord channel from a social media channel or all subscribed channels.")
	@app_commands.describe(social_media_channel="Optional: Name of the social media subscription. If empty, clears all active subscriptions.", channel="Optional: The Discord text channel to unsubscribe the channel from. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
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

			# Cleanup, If no Discord channels are subscribed to the social media channel, remove it from the database
			if sql.get_discord_channels_for_social_channel(internal_social_media_channel) is None:
				sql.remove_social_media_channel(internal_social_media_channel)
				sql.remove_latest_post(internal_social_media_channel)
				main.logger.info(f"Removing social media channel '{target_social_media_name}' and its stored post from database...\n")

		except Exception as e:
			main.logger.error(f"Error unsubscribing Discord channel from YouTube notifications: {e}\n")

	# Autocomplete handler for unsubscribe
	@unsubscribe_channel.autocomplete("social_media_channel")
	@text_channel_only()
	async def autocomplete_social_media_channel(self, interaction: discord.Interaction, current: str):
		channel = interaction.channel

		subscriptions = sql.list_social_media_subscriptions_for_discord_channel(channel.id)
		if not subscriptions:
			return []
		
		choices = []
		for internal_id in subscriptions:
			name = sql.get_channel_name(internal_id)
			url = sql.get_channel_url(internal_id)

			if name is None or url is None:
				# don't add broken data
				continue
			# convert to lowercase, compare against channel name
			if current.lower() in name.lower():
				choices.append(discord.app_commands.Choice(name=f"{name}", value=url))
		return choices[:25] # Limit to 25 choices (Discord's limit)



	@app_commands.command(name="list_subscriptions", description="Returns the list of social media subscriptions for the given channel, and the notification role.")
	@app_commands.describe(channel="Optional: The Discord text channel to check. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
	async def check_channel_status(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			notification_role = sql.get_notification_role(targetChannel.id)

			subscriptions = sql.list_social_media_subscriptions_for_discord_channel(targetChannel.id)
			if subscriptions is not None:
				output = ""
				for channel_id in subscriptions:
					channel_name = sql.get_channel_name(channel_id)
					# add each channel_id, join them into a string delimited by a line break
					output += f"{channel_name}\n"
				
				message = f"{targetChannel.name} is currently subscribed to receive upcoming stream notifications from the following channels:\n{output}"
				if notification_role is not None:
					role = interaction.guild.get_role(int(notification_role))
					if role is not None:
						# Check if the bot has permission to mention roles
						if interaction.guild.me.guild_permissions.mention_everyone:
							main.logger.info(f"notification role found... {notification_role}\n")
							message += f"\nDreamcatcher will ping {role.mention} on new activity."
						else:
							main.logger.warning(f"Bot lacks permission to mention roles in guild {interaction.guild.name}.\n")
							message += f"\nDreamcatcher cannot mention the notification role due to insufficient permissions."
					else:
						main.logger.warning(f"Invalid or missing role for ID {notification_role} in guild {interaction.guild.name}.\n")
						message += f"\nDreamcatcher could not find the notification role. Please update it using the appropriate command."
				await interaction.response.send_message(message, ephemeral=True)
			else:
				await interaction.response.send_message(f"{targetChannel.name} is not subscribed to any channels.",
					ephemeral=True)

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error checking discord channel status: {e}\n")

#
#	Discord channel notification functions
#
	@app_commands.command(name="set_notification_role", description="Add or update the role that will be pinged when a new notification is sent.")
	@app_commands.describe(role="The role that will be notified whenever new content is posted.", channel="Optional: The Discord text channel to unsubscribe. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
	async def add_notification_role(self, interaction: discord.Interaction, role: discord.Role, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			sql.add_notification_role(targetChannel.id, role.id)
			await interaction.response.send_message(f"Notification role for channel {targetChannel.name} updated to {role.name}.",
				ephemeral=True)
			main.logger.info(f"[BOT.COMMAND] Notification role updated to {role.name}...\n")

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error updating notification role: {e}\n")

	@app_commands.command(name="remove_notification_role", description="Remove the role that will be pinged when a new notification is sent.")
	@app_commands.describe(channel="Optional: The Discord text channel to unsubscribe. Defaults to current.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	@text_channel_only()
	async def remove_notification_role(self, interaction: discord.Interaction, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel

			if (sql.get_notification_role(targetChannel.id) is None):
				await interaction.response.send_message(f"No notification role set for channel {targetChannel.name}.",
					ephemeral=True)
				return

			sql.remove_notification_role(targetChannel.id)
			await interaction.response.send_message(f"Notification role for channel {targetChannel.name} removed.",
				ephemeral=True)
			main.logger.info(f"[BOT.COMMAND] Notification role removed...\n")

		except Exception as e:
			main.logger.error(f"[BOT.COMMAND.ERROR] Error removing notification role: {e}\n")

#
#	SETUP
#

async def setup(_bot):
	await _bot.add_cog(Notifications(_bot))
	main.logger.info(f"Notifications cog loaded!\n")
