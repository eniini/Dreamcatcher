from fastapi import FastAPI
import os
import uvicorn

import main

global fastAPIapp
fastAPIapp = FastAPI()

#
#	Setup the FastAPI web server
#

async def run_web_server():
	"""
	Run the FastAPI web server, Uvicorn is needed for that. / could also be its own separate systemD service.
	"""
	try:
		config = uvicorn.Config(fastAPIapp, host="0.0.0.0", port=8000)
		server = uvicorn.Server(config)
		main.logger.info(f"Starting FastAPI web server at http://{main.PUBLIC_WEBHOOK_IP}:8000\n")
		await server.serve()
	except Exception as e:
		main.logger.error(f"Error starting FastAPI web server: {e}\n")