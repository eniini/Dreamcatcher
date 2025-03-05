# Dreamcatcher 🎐

Locally hosted Discord bot for keeping up with content creator's socials and streams.

## Features
- Active YouTube and Bluesky monitoring that respects API quotas
- SQLite Database for content tracking

## Prerequisites
- Bluesky, Discord and Google accounts
- Python 3.8+
- pip

## Getting Started
1. Setup Discord Bot:
	- Create a new application inside [Discord Developer Portal](https://discord.com/developers/applications)
	- Save generated bot token to the `.env` file (use `.env.example` as reference)
	- Set up a new Discord server for your bot's development, then use OAuth2 tab to generate a link for adding the bot to the created channel.
2. Setup Youtube API:
	- Create New [Google Cloud Console project](https://console.cloud.google.com)
	- Enable YouTube Data API 3.0
	- Create API Credentials and save them into the `.env` file
3. Find Youtube Channel ID and playlist ID
	- The format for ID is `UC_x5XG1OV2P6uZZ5FSM9Ttw`. There are [multiple ways](https://stackoverflow.com/questions/14366648/how-can-i-get-a-channel-id-from-youtube/18665812#18665812) to search for target channel's ID.
	- The Playlist ID is similar to the Channel ID, but the first two letters are `UU_` instead of `UC_`
4. Run the app:
	- Run the follow command to install required libraries:
		`pip install -r requirements.txt`
	- Run the bot with either:
		`python source/main.py` or `./dreamcatcher`
	- use `/Sync` command to synchronize bot's slash commands with discord.
	- use available slash commands to define bot behavior
