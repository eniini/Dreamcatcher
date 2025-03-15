from fastapi import FastAPI
import asyncio
import uvicorn

import main

global fastAPIapp
fastAPIapp = FastAPI()

global server
server = uvicorn.Server()

#
#	The web stack of the app is FastAPI with Uvicorn interacting with a Nginx reverse proxy.
#	Youtube PubSubHubbub will call the generated webhook URL {PUBLIC_WEBHOOK_IP}:8000/youtube-webhook
#	which will be handled by Nginx and forwarded to the FastAPI server.
#

async def run_web_server():
	"""
	Run the internal FastAPI web server with uvicorn.
	"""
	try:
		config = uvicorn.Config(fastAPIapp, host="0.0.0.0", port=8001)
		server = uvicorn.Server(config)
		main.logger.info(f"Starting FastAPI internal server at http://{main.PUBLIC_WEBHOOK_IP}:8001. Expecting Nginx forward to port 8000...\n")
		await server.serve()
	except asyncio.CancelledError:
		main.logger.info("FastAPI server shutdown requested.\n")
	except Exception as e:
		main.logger.error(f"Error starting FastAPI web server: {e}\n")

async def close_web_server():
	"""
	Close the internal FastAPI web server.
	"""
	if server and server.should_exit is False:
		try:
			main.logger.info(f"Shutting down FastAPI internal server...\n")
			server.should_exit = True
			# wait until server shutdown is complete.
			await server.shutdown()
		except Exception as e:
			main.logger.error(f"Error shutting down FastAPI web server: {e}\n")
