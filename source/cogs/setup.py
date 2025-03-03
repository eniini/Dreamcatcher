import discord
from discord import app_commands
from discord.ext import commands

import bot
import main

#
# Discord bot setup (server-specific roles that have access to manage the bot)
#

class Setup(commands.Cog):
	def __init__(self, _bot):
		self._bot = _bot

	@app_commands.command(name="setup", description="Set a role that will have permission to manage the bot.")
	@app_commands.checks.has_permissions(manage_guild=True)
	async def setup_role(self, interaction: discord.Interaction, role: discord.Role):
		guild_id = interaction.guild.id

		# Check if the role is already set
		if await bot.get_manager_role(guild_id):
			try:
				await bot.set_manager_role(guild_id, role.id, update=True)
			except Exception as e:
				await interaction.response.send_message(f"❌ Failed to update the role in the database. Please try again later.", ephemeral=True)
				return
		else:
			try:
				await bot.set_manager_role(guild_id, role.id)
			except Exception as e:
				await interaction.response.send_message(f"❌ Failed to save the role to the database. Please contact the bot owner!", ephemeral=True)
				return

		await interaction.response.send_message(f"✅ Role {role.name} has been set as the bot manager role.", ephemeral=True)
		return
	
	@commands.Cog.listener()
	async def on_guild_join(self, guild: discord.Guild):
		# when bot joins a new server, prompt setup
		if guild.system_channel:
			await guild.system_channel.send("Hello! Please set a role that will have permission to manage the bot by typing `/setup @role`.")

async def setup(_bot):
	await _bot.add_cog(Setup(_bot))
	main.logger.info(f"Setup cog loaded!\n")
