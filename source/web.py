from fastapi import FastAPI
import os
import uvicorn

global fastAPIapp
fastAPIapp = FastAPI()

PUBLIC_WEBHOOK_IP = os.getenv("PUBLIC_WEBHOOK_IP")

#
#	Setup the FastAPI web server
#

async def run_web_server():
	"""
	Run the FastAPI web server, Uvicorn is needed for that. / could also be its own separate systemD service.
	"""
	config = uvicorn.Config(fastAPIapp, host="0.0.0.0", port=8000)
	server = uvicorn.Server(config)
	await server.serve()
