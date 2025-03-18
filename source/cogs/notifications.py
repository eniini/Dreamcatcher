import discord
from discord.ext import commands
from discord import app_commands

import main
import youtube
import sql

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
					# Check if this Discord channel is already in the SQL database.
					sql.add_discord_channel(targetChannel.id, targetChannel.name)
					#main.add_youtube_channel_to_whitelist(youtube_channel_id, targetChannel.id)
					# Check if the given YT channel already has stored ID in database and if its already linked.
					internal_id = sql.get_id_for_channel_url(youtube_channel_id)
					if internal_id is not None:
						# YT channel is already in database, and is already linked to this Discord channel.
						if sql.is_discord_channel_subscribed(targetChannel.id, internal_id) is True:
							await interaction.response.send_message(f"This channel already has a subscription to the given channel.",
								ephemeral=True)
						# YT channel is already in database, but not linked to this Discord channel.
						else:
							sql.add_subscription(targetChannel, internal_id)
					# YT channel is new, call YT webhook subscription...
					else:

						# TODO: Need dedicated way to track YT subscriptions!!!

						status_code = youtube.subscribe_to_channel(youtube_channel_id, youtube.public_webhook_address)
						# if status_code is not 404, 502 etc.., save activated YouTube subscription to SQL Database.
						# else log an error for YT webhook failure.
						# otherwise...
						internal_id = sql.add_social_media_channel("YouTube", youtube_channel_id, None)
						sql.add_subscription(targetChannel, internal_id)

				except Exception as e:
					await interaction.response.send_message(f"Command failed due to an internal error. Please try again later.",
						ephemeral=True)
					main.logger.error(f"[BOT.COMMAND.ERROR] Error adding YouTube channel subscription to given channel: {e}\n")

				# Everything went ok, confirm to user
				await interaction.response.send_message(f"{targetChannel.name} will now receive notifications for YouTube channel ID {youtube_channel_id}!",
					ephemeral=True)
				main.logger.info(f"[BOT.COMMAND] YouTube channel ID {youtube_channel_id} subscribed to {targetChannel.name}...\n")

		except Exception as e:
			main.logger.error(f"Error subscribing YouTube channel for bot notifications: {e}\n")

	# TODO: This shouldn't require user to input the subscribed social media channel. Instead, the user should see a list of
	# active subscriptions and input all values as a reply corresponding to the list to the bot's ephemeral message.

	@app_commands.command(name="unsubscribe_channel", description="Unsubscribe a discord channel from receiving notifications from a YouTube channel.")
	@app_commands.default_permissions(manage_guild=True)	# Hides command from users without this permission
	@app_commands.checks.has_permissions(manage_guild=True)	# Checks if the user has the manage_guild permission
	async def unsubscribe_channel(self, interaction: discord.Interaction, channel_id: str=None, channel: discord.TextChannel=None):
		try:
			# if no given channel, defaults to the context
			if channel is None:
				targetChannel = interaction.channel
			else:
				targetChannel = channel
			
			# if no given youtube channel, recursively unsubscribe all YouTube channel subscriptions from the target Discord channel
			# else just unsubscribe the given YouTube channel from the target Discord channel
			if channel_id is None:
				# get all the YouTube channel subscriptions for the target Discord channel
				subscriptions = sql.list_social_media_subscriptions_for_discord_channel(targetChannel.id)
				if subscriptions is not None:
					# call remove_subscription without target subscription, removing all active subscriptions
					sql.remove_subscription(targetChannel.id)
				else:
					await interaction.response.send_message(f"No YouTube channel subscriptions found for {targetChannel.name}.",
						ephemeral=True)
			else:
				subscriptions = sql.list_social_media_subscriptions_for_discord_channel(targetChannel.id)
				if subscriptions is not None:
					sql.remove_subscription(targetChannel.id, channel_id)
				else:
					await interaction.response.send_message(f"No YouTube channel subscriptions found for {targetChannel.name}.",
						ephemeral=True)
				pass
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
					# add each channel_id, join them into a string delimited by a line break
					output += f"{sql.get_channel_url(channel_id)}\n"
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
