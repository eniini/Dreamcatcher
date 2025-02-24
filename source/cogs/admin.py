import discord
from discord.ext import commands
from discord import app_commands

import main

class Admin(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	@app_commands.command(name="sync", description="Sync commands (dev only)")
	async def sync_commands(self, interaction: discord.Interaction):
		"""
		Allowed to be called only by the server owner in the home/dev server. That means you!
		"""
		if interaction.user.id != interaction.guild.owner_id or interaction.guild.id != main.HOME_SERVER_ID:
			await interaction.response.send_message("You do not have permission to perform this action.", ephemeral=True)
			return
		try:
			synced = await self.bot.tree.sync()
			await interaction.response.send_message(f"✅ Synced {len(synced)} commands successfully!", ephemeral=True)
		except Exception as e:
			await interaction.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)

async def setup(bot):
	await bot.add_cog(Admin(bot))
	main.logger.info(f"Admin cog loaded!\n")
