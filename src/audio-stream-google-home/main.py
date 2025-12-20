import threading
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
import pychromecast
from pydantic import BaseModel
import os
import time
import zeroconf
import logging
from urllib.parse import quote
from dotenv import load_dotenv
import socket
# Load the .env file
load_dotenv()
import uvicorn

ENV = os.getenv("ENV", "production")
PORT_SERVER = int(os.getenv("PORT", "8801"))
IP_SERVER = os.getenv("IP_SERVER", "127.0.0.1")
MP3_FOLDER = os.getenv("MP3_FOLDER", "/mp3")
GOOGLE_HOME_IP = os.getenv("GOOGLE_HOME_IP", "192.168.1.50")  # replace with your device IP
GOOGLE_HOME_PORT = 8009
MP3_ROUTE = "/mp3"
print(f"Starting in {ENV} mode on {IP_SERVER}:{PORT_SERVER}, serving MP3s from {MP3_FOLDER}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Chromecast globals (populated on startup)
cast = None
mc = None

def startup_event():
    """Discover Chromecast using CastBrowser at startup."""
    global cast, mc
      
    try:
        cast = pychromecast.get_chromecast_from_host((GOOGLE_HOME_IP, GOOGLE_HOME_PORT, None, None, None), tries=3, retry_wait=10)  # blocking=True waits for connection
        mc = cast.media_controller
        logger.info(f"Connected to Chromecast at {GOOGLE_HOME_IP} ({cast.cast_info})")
    except Exception:
        logger.exception(f"Failed to connect to Chromecast at {GOOGLE_HOME_IP}")
        cast = None
        mc = None
            

# Ensure MP3 folder exists (create if possible)
if not os.path.isdir(MP3_FOLDER):
    try:
        os.makedirs(MP3_FOLDER, exist_ok=True)
        logger.info("Created MP3 folder %s", MP3_FOLDER)
    except Exception as e:
        logger.warning("MP3 folder %s missing and could not be created: %s", MP3_FOLDER, e)

app = FastAPI()
app.mount(MP3_ROUTE, StaticFiles(directory=MP3_FOLDER), name="mp3")

class PlayRequest(BaseModel):
    track: str

logger.info(f"Determined LAN IP address: {IP_SERVER}")
@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/play")
def play(req: PlayRequest, request: Request):
    """Play an MP3 file by filename (track).

    Validates the requested filename, checks it exists in `MP3_FOLDER`,
    and sends the URL to the Chromecast media controller.
    """
    track = req.track
    safe_filename = os.path.basename(track)
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid track name")

    local_path = os.path.join(MP3_FOLDER, safe_filename)
    logger.info(f"Requested track: {track}, safe filename: {safe_filename}, local path: {local_path}")
    if not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail="Track not found")



    track_url = f"http://{IP_SERVER.rstrip('/')}:{PORT_SERVER}{MP3_ROUTE}/{quote(safe_filename)}"

    if mc is None:
        raise HTTPException(status_code=503, detail="Cast device not ready")
    logger.info("Waiting to play media %s", track_url)
    # mc.block_until_active()  # Wait until the media controller is ready
    MAX_RETRIES = 5
    for _ in range(MAX_RETRIES):
        try:
            logger.info("Attempting to play media %s", track_url)
            mc.play_media(track_url, "audio/mp3")
            break
        except pychromecast.error.NotConnected:
            logger.info("Cast not ready, retrying...")
            time.sleep(10)
    else:
        raise HTTPException(status_code=503, detail="Cast device not ready")
    try:
        mc.play_media(track_url, "audio/mp3")
    except Exception:
        logger.exception("Failed to play media %s", track_url)
        raise HTTPException(status_code=500, detail="Failed to play media")

    return {"status": "ok", "track_url": track_url}


startup_event()
if __name__ == "__main__":

    # Run in development mode, reload allows hot-reload when you change the code
    uvicorn.run("main:app", host="0.0.0.0", port=PORT_SERVER, reload=True)