import discord
from discord.ext import commands
from discord import app_commands

import main
import sql
import bot

class Admin(commands.Cog):
	def __init__(self, _bot):
		self._bot = _bot

	@app_commands.command(name="sync", description="[dev only]")
	@app_commands.default_permissions(administrator=True)		# Hides command from users without this permission
	@app_commands.checks.has_permissions(administrator=True)	# Checks if the user has the manage_guild permission
	async def sync_commands(self, interaction: discord.Interaction):
		"""
		Allowed to be called only by the server owner in the home/dev server. That means you!
		"""
		if interaction.user.id != interaction.guild.owner_id or interaction.guild.id != main.HOME_SERVER_ID:
			await interaction.response.send_message("You do not have permission to perform this action.",
				ephemeral=True)
			return
		try:
			synced = await self._bot.tree.sync()
			await interaction.response.send_message(f"✅ Synced {len(synced)} commands successfully!",
				ephemeral=True)
		except Exception as e:
			await interaction.response.send_message(f"❌ Sync failed: {e}",
				ephemeral=True)

	@app_commands.command(name="print_sql", description="[dev only]")
	@app_commands.default_permissions(administrator=True)		# Hides command from users without this permission
	@app_commands.checks.has_permissions(administrator=True)	# Checks if the user has the manage_guild permission
	async def print_sql(self, interaction: discord.Interaction):
		"""
		Allowed to be called only by the server owner in the home/dev server. That means you!
		"""
		if interaction.user.id != interaction.guild.owner_id or interaction.guild.id != main.HOME_SERVER_ID:
			await interaction.response.send_message("You do not have permission to perform this action.",
				ephemeral=True)
			return
		try:
			await interaction.response.send_message("✅ Printing SQL contents to home channel...\n",
				ephemeral=True)
			await bot.bot_internal_message(f"{sql.read_table_contents()}")

		except Exception as e:
			await interaction.response.send_message(f"❌ Printing SQL contents failed: {e}",
				ephemeral=True)

	@app_commands.command(name="manage_subscriptions", description="List and remove Discord channel to social media channel subscriptions. (dev only)")
	@app_commands.default_permissions(administrator=True)
	@app_commands.checks.has_permissions(administrator=True)
	@app_commands.describe(subscription="Select a subscription to remove.")
	async def manage_subscriptions(self, interaction: discord.Interaction, subscription: str):
		"""
		Admin-only: List all Discord channel to social media channel subscriptions and remove one.
		"""
		if interaction.user.id != interaction.guild.owner_id or interaction.guild.id != main.HOME_SERVER_ID:
			await interaction.response.send_message("You do not have permission to perform this action.",
				ephemeral=True)
			return

		try:
			# subscription is a string in the format: "{discord_channel_id}|{social_media_channel_id}"
			discord_channel_id, social_media_channel_id = subscription.split("|")
			social_media_channel_id = int(social_media_channel_id)
			channel_name = sql.get_channel_name(social_media_channel_id)
			discord_channel_name = None
			# Try to get channel name from Discord, fallback to SQL
			channel_obj = interaction.guild.get_channel(int(discord_channel_id))
			if channel_obj:
				discord_channel_name = channel_obj.name
			else:
				# fallback: try to get from SQL
				discord_channel_name = discord_channel_id

			# Remove the subscription
			sql.remove_subscription(discord_channel_id, social_media_channel_id)

			# Cleanup: If no Discord channels are subscribed to the social media channel, remove it from the database
			remaining = sql.get_discord_channels_for_social_channel(social_media_channel_id)
			if not remaining:
				sql.remove_social_media_channel(social_media_channel_id)
				sql.remove_latest_post(social_media_channel_id)
				if sql.get_channel_platform(social_media_channel_id) == "YouTube":
					# If you want to update wait time, import youtube and call update_yt_wait_time if needed
					pass

			await interaction.response.send_message(
				f"Removed subscription: Discord channel `{discord_channel_name}` from social media channel `{channel_name}`.",
				ephemeral=True
			)
			main.logger.info(f"[ADMIN] Removed subscription: Discord channel {discord_channel_id} from social media channel {social_media_channel_id}\n")
		except Exception as e:
			await interaction.response.send_message(f"❌ Failed to remove subscription: {e}", ephemeral=True)
			main.logger.error(f"[ADMIN] Failed to remove subscription: {e}\n")

	@manage_subscriptions.autocomplete("subscription")
	async def autocomplete_subscription(self, interaction: discord.Interaction, current: str):
		# List all subscriptions in the format: "{discord_channel_id}|{social_media_channel_id}"
		choices = []
		try:
			conn = sql.get_connection()
			if conn is None:
				return []
			cursor = conn.cursor()
			cursor.execute('''
				SELECT s.discord_channel_id, s.social_media_channel_id, d.channel_name, m.channel_name as sm_name, m.platform
				FROM Subscriptions s
				LEFT JOIN DiscordChannels d ON s.discord_channel_id = d.channel_id
				LEFT JOIN SocialMediaChannels m ON s.social_media_channel_id = m.id
			''')
			rows = cursor.fetchall()
			for row in rows:
				discord_channel_id = row['discord_channel_id']
				social_media_channel_id = row['social_media_channel_id']
				discord_channel_name = row['channel_name'] or discord_channel_id
				sm_name = row['sm_name'] or "Unknown"
				platform = row['platform'] or "Unknown"
				label = f"{discord_channel_name} → [{platform}] {sm_name}"
				value = f"{discord_channel_id}|{social_media_channel_id}"
				if current.lower() in label.lower():
					choices.append(discord.app_commands.Choice(name=label, value=value))
			return choices[:25]
		except Exception as e:
			main.logger.error(f"[ADMIN] Autocomplete error: {e}\n")
			return []
		finally:
			if 'conn' in locals() and conn:
				conn.close()

async def setup(_bot):
	await _bot.add_cog(Admin(_bot))
	main.logger.info(f"Admin cog loaded!\n")
