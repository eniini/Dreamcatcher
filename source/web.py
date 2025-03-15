from fastapi import FastAPI
import os
import uvicorn

import main

global fastAPIapp
fastAPIapp = FastAPI()

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
	except Exception as e:
		main.logger.error(f"Error starting FastAPI web server: {e}\n")