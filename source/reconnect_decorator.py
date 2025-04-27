import asyncio
import functools

import main
import bot

def reconnect_api_with_backoff(client_initialize_func, client_name: str, max_retries=5, base_delay=2):
	"""
	Tries to re-establish given API connection with exponential falloff.
	Parameters:
		client_initialize_func: function to initialize the API client
		client_name: name of the API client (for logging purposes)
		max_retries: maximum number of retries before giving up
		base_delay: base delay in seconds for exponential backoff
	"""
	def decorator(api_func):
		@functools.wraps(api_func)
		async def wrapper(*args, **kwargs):
			attempt = 0
			while attempt < max_retries:
				try:
					return await api_func(*args, **kwargs)
				except Exception as e:
					attempt += 1
					main.logger.warning(f"{client_name} API call failed! (attempt {attempt}/{max_retries}): {e}")

					if "quotaExceeded" in str(e) or "403" in str(e):
						main.logger.critical(f"Bot has exceeded {client_name} API quota.")
						await bot.bot_internal_message("Bot has exceeded {client_name} API quota!")
						return None
					if attempt == max_retries:
						main.logger.error(f"Max retries reached. Could not recover API connection.")
						await bot.bot_internal_message("Bot failed to connect to {client_name} API after max retries...")

					wait_time = base_delay * pow(2, attempt - 1)
					main.logger.info(f"Reinitializing {client_name} API client in {wait_time:.2f} seconds...")

					await asyncio.sleep(wait_time)
					# try to reconnect API
					await client_initialize_func()
		return wrapper
	return decorator
