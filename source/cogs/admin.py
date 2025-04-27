import discord
from discord.ext import commands
from discord import app_commands

import main
import sql
import bot

class Admin(commands.Cog):
	def __init__(self, _bot):
		self._bot = _bot

	@app_commands.command(name="sync", description="Sync commands (dev only)")
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

	@app_commands.command(name="print_sql", description="Print out the SQL database")
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
			bot.bot_internal_message(f"{sql.read_table_contents()}")

		except Exception as e:
			await interaction.response.send_message(f"❌ Printing SQL contents failed: {e}",
				ephemeral=True)

async def setup(_bot):
	await _bot.add_cog(Admin(_bot))
	main.logger.info(f"Admin cog loaded!\n")
