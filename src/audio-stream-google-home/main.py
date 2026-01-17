from fastapi import FastAPI, Request, HTTPException
from fastapi.concurrency import asynccontextmanager
from fastapi.staticfiles import StaticFiles
import pychromecast
from pydantic import BaseModel
import os
import time
import logging
from urllib.parse import quote
import uvicorn
from dotenv import load_dotenv
from pathlib import Path

# Load the .env file explicitly from the repository root (works regardless of CWD).
# File location: src/audio-stream-google-home/main.py -> parents[2] is the repo root.
env_path = Path(__file__).resolve().parents[2] / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, verbose=True)
else:
    # Fallback to default search behavior
    load_dotenv(verbose=True)

ENV = os.getenv("AB_ENV", "production")
PORT_SERVER = int(os.getenv("AB_PORT_SERVER", "8801"))
IP_SERVER = os.getenv("AB_IP_SERVER", "127.0.0.1") # IP that the Google Home will reach to download the MP3s

# Determine MP3 folder: prefer `AB_MP3_FOLDER` from env; otherwise use repo-relative `mp3`.
repo_root = Path(__file__).resolve().parents[2]
default_mp3 = repo_root / "mp3"
MP3_FOLDER = os.getenv("AB_MP3_FOLDER")
if MP3_FOLDER:
    MP3_FOLDER = MP3_FOLDER
else:
    MP3_FOLDER = str(default_mp3)
GOOGLE_HOME_IP = os.getenv("AB_GOOGLE_HOME_IP", "192.168.1.50")  # replace with your device IP
GOOGLE_HOME_PORT = 8009
MP3_ROUTE = "/mp3"


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"Starting in {ENV} mode on {IP_SERVER}:{PORT_SERVER}, serving MP3s from {MP3_FOLDER}")
# Chromecast globals (populated on startup)
cast = None
mc = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init
    startup_event(app)
    yield
    # Clean up
    # Nothing for now

def startup_event(app: FastAPI):
    """Discover Chromecast using CastBrowser at startup."""
    global cast, mc, MP3_FOLDER
      
    try:
        cast = pychromecast.get_chromecast_from_host((GOOGLE_HOME_IP, GOOGLE_HOME_PORT, None, None, None), tries=3, retry_wait=10)  # blocking=True waits for connection
        cast.wait()
        mc = cast.media_controller
        # Wait a moment for the connection to fully establish
        time.sleep(2)
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
        except PermissionError:
            # If we can't create the requested folder (e.g., '/mp3'), fall back to repo-relative mp3
            try:
                MP3_FOLDER = str(default_mp3)
                os.makedirs(MP3_FOLDER, exist_ok=True)
                logger.warning("Permission denied creating requested MP3 folder; using %s instead", MP3_FOLDER)
            except Exception as e:
                logger.exception("Failed to create fallback MP3 folder %s: %s", MP3_FOLDER, e)
        except Exception as e:
            logger.exception("MP3 folder %s missing and could not be created: %s", MP3_FOLDER, e)
    app.mount(MP3_ROUTE, StaticFiles(directory=MP3_FOLDER), name="mp3")

app = FastAPI(lifespan=lifespan)

class PlayRequest(BaseModel):
    track: str
    
def get_mp3_file_names():
    try:
        files = [f[:-4] for f in os.listdir(MP3_FOLDER) if os.path.isfile(os.path.join(MP3_FOLDER, f)) and f.lower().endswith('.mp3')]
        return files
    except Exception as e:
        logger.exception("Failed to list tracks in %s: %s", MP3_FOLDER, e)
        return []
    
@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/list")
def list_tracks():
    """List available MP3 files in the MP3_FOLDER."""
    try:
        files = get_mp3_file_names()
        # Order alphabetically
        files.sort()
        return {"tracks": files}
    except Exception as e:
        logger.exception("Failed to list tracks in %s: %s", MP3_FOLDER, e)
        raise HTTPException(status_code=500, detail="Failed to list tracks")

@app.post("/play") 
def play(req: PlayRequest, request: Request):
    """Play an MP3 file by filename (track).

    Validates the requested filename, checks it exists in `MP3_FOLDER`,
    and sends the URL to the Chromecast media controller.
    """
    track = req.track
    safe_filename = os.path.basename(track)
    safe_filename_with_ext = safe_filename + ".mp3"
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid track name")
    files = get_mp3_file_names()
    if safe_filename not in files:
        raise HTTPException(status_code=404, detail="Track not found")
    local_path = os.path.join(MP3_FOLDER, safe_filename_with_ext)
    logger.info(f"Requested track: {track}, safe filename: {safe_filename_with_ext}, local path: {local_path}")
        
    if not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail="Track not found")

    track_url = f"http://{IP_SERVER.rstrip('/')}:{PORT_SERVER}{MP3_ROUTE}/{quote(safe_filename_with_ext)}"

    if mc is None or cast is None:
        raise HTTPException(status_code=503, detail="Cast device not ready")
    
    logger.info("Waiting to play media %s", track_url)
    MAX_RETRIES = 5
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Attempting to play media {track_url} (attempt {attempt + 1}/{MAX_RETRIES})")
            mc.play_media(track_url, "audio/mp3", title=f"Playing {safe_filename}", subtitles=f"From audio Stream Server")
            logger.info(f"Successfully sent play command for {safe_filename}")
            break
        except pychromecast.error.NotConnected as e:
            logger.error("Cast not ready, retrying...")
            if attempt < MAX_RETRIES - 1:
                time.sleep(3)
            else:
                logger.exception("Failed to play media %s after retries", track_url)
                raise HTTPException(status_code=503, detail="Cast device not ready")

    return {"status": "ok", "track_url": track_url}

if __name__ == "__main__":

    # Run in development mode, reload allows hot-reload when you change the code
    uvicorn.run("main:app", host="0.0.0.0", port=PORT_SERVER, reload=ENV=="development")