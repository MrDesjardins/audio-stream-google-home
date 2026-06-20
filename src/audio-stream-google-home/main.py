from fastapi import FastAPI, Request, HTTPException
from fastapi.concurrency import asynccontextmanager
from fastapi.staticfiles import StaticFiles
import pychromecast
from pydantic import BaseModel
import asyncio
import functools
import os
import time
import logging
import subprocess
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import uvicorn
from dotenv import load_dotenv
from pathlib import Path
try:
    from .telemetry import TelemetryService, get_telemetry_router
except ImportError:
    from telemetry import TelemetryService, get_telemetry_router

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

GOOGLE_HOME_PORT = 8009
MP3_ROUTE = "/mp3"
CAST_CONNECT_TRIES = int(os.getenv("AB_CAST_CONNECT_TRIES", "2"))
CAST_CONNECT_RETRY_WAIT = float(os.getenv("AB_CAST_CONNECT_RETRY_WAIT", "2"))
CAST_CONNECT_TIMEOUT = float(os.getenv("AB_CAST_CONNECT_TIMEOUT", "5"))
CAST_WAIT_TIMEOUT = float(os.getenv("AB_CAST_WAIT_TIMEOUT", "8"))
CAST_CONTROLLER_TIMEOUT = float(os.getenv("AB_CAST_CONTROLLER_TIMEOUT", "8"))
CAST_REQUEST_TIMEOUT = float(os.getenv("AB_CAST_REQUEST_TIMEOUT", "35"))
CAST_PLAY_RETRIES = int(os.getenv("AB_CAST_PLAY_RETRIES", "3"))
CAST_PLAY_RETRY_WAIT = float(os.getenv("AB_CAST_PLAY_RETRY_WAIT", "2"))
CAST_WORKERS = int(os.getenv("AB_CAST_WORKERS", "2"))
DEVICE_REFRESH_TIMEOUT = float(os.getenv("AB_DEVICE_REFRESH_TIMEOUT", "12"))

DEFAULT_DEVICE_IPS = {
    "Jacob": "10.0.0.55",
    "Alicia": "10.0.0.200",
    "Master Bedroom": "10.0.0.200",
    "Living Room Speaker": "10.0.0.236",
    "Kitchen Speaker": "10.0.0.51",
}
DEVICE_IPS = dict(DEFAULT_DEVICE_IPS)


def discover_device_ips_from_avahi():
    """Discover Google Cast devices from avahi-browse output.

    Uses avahi-browse on _googlecast._tcp and returns a dict
    of {friendly_device_name: ip_address}.
    """
    cmd = ["avahi-browse", "-rt", "_googlecast._tcp"]
    discovered = {}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError:
        logger.warning("avahi-browse not found; using fallback static DEVICE_IPS")
        return {}
    except subprocess.TimeoutExpired:
        logger.warning("avahi-browse timed out; using fallback static DEVICE_IPS")
        return {}
    except Exception as e:
        logger.exception("Unexpected error while running avahi-browse: %s", e)
        return {}

    if result.returncode != 0:
        logger.warning(
            "avahi-browse returned non-zero exit code %s; stderr=%s",
            result.returncode,
            result.stderr.strip(),
        )
        return {}

    def _normalize_name(value):
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _parse_txt_kv(txt_line):
        # Example:
        # txt = ["...","fn=Kitchen speaker","md=Google Home","id=..."]
        pairs = re.findall(r'"([^"]*)"', txt_line)
        txt = {}
        for pair in pairs:
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            txt[key.strip()] = value.strip()
        return txt

    # Track best address by friendly name, preferring IPv4 if available.
    # Value format: {"ip": "...", "is_ipv4": bool}
    candidates = {}
    current = None

    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("="):
            # Example:
            # = enp1s0 IPv4 Google-Home-... _googlecast._tcp local
            parts = stripped.split()
            if len(parts) >= 6:
                current = {
                    "proto": parts[2].strip(),
                    "service_name": parts[3].strip(),
                    "service_type": parts[4].strip(),
                    "address": "",
                    "port": "",
                    "txt": {},
                }
            else:
                current = None
            continue

        if not current:
            continue

        if "address =" in stripped:
            m = re.search(r"address\s*=\s*\[(.*?)\]", stripped)
            if m:
                current["address"] = m.group(1).strip()
            continue

        if "port =" in stripped:
            m = re.search(r"port\s*=\s*\[(.*?)\]", stripped)
            if m:
                current["port"] = m.group(1).strip()
            continue

        if stripped.startswith("txt ="):
            current["txt"] = _parse_txt_kv(stripped)

            if current.get("service_type") != "_googlecast._tcp":
                current = None
                continue

            # Ignore groups and non-standard Cast service ports.
            if current.get("port") != "8009":
                current = None
                continue

            address = current.get("address")
            if not address:
                current = None
                continue

            txt = current.get("txt", {})
            model = txt.get("md", "")
            if model == "Google Cast Group":
                current = None
                continue

            friendly_name = txt.get("fn") or current.get("service_name", "")
            if not friendly_name:
                current = None
                continue

            is_ipv4 = current.get("proto", "").upper() == "IPV4"
            existing = candidates.get(friendly_name)
            if (not existing) or (is_ipv4 and not existing["is_ipv4"]):
                candidates[friendly_name] = {"ip": address, "is_ipv4": is_ipv4}

            current = None

    for name, entry in candidates.items():
        discovered[name] = entry["ip"]

    # Keep compatibility with existing short aliases in requests.
    normalized_discovered = {_normalize_name(k): v for k, v in discovered.items()}
    
    if normalized_discovered:
        return normalized_discovered

    for alias in DEFAULT_DEVICE_IPS.keys():
        key = _normalize_name(alias)
        if key in normalized_discovered:
            discovered[alias] = normalized_discovered[key]
            continue
        alias_tokens = key.split()
        for d_name, d_ip in discovered.items():
            d_key = _normalize_name(d_name)
            if all(token in d_key for token in alias_tokens if token):
                discovered[alias] = d_ip
                break

    return discovered


def refresh_device_ips():
    """Refresh DEVICE_IPS from Avahi; keep static fallback when needed."""
    global DEVICE_IPS
    discovered = discover_device_ips_from_avahi()
    if discovered:
        DEVICE_IPS = discovered
        logger.info("Discovered %d Google Cast devices via Avahi", len(DEVICE_IPS))
    else:
        DEVICE_IPS = dict(DEFAULT_DEVICE_IPS)
        logger.warning(
            "No Google Cast devices discovered via Avahi; using fallback static DEVICE_IPS"
        )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"Starting in {ENV} mode on {IP_SERVER}:{PORT_SERVER}, serving MP3s from {MP3_FOLDER}")
# Chromecast globals (populated on startup)
cast = None
mc = None
cast_executor = ThreadPoolExecutor(max_workers=CAST_WORKERS, thread_name_prefix="cast")
cast_lock = threading.Lock()
active_casts = set()


class CastPlaybackError(RuntimeError):
    """Raised when a bounded Chromecast operation fails."""


def _disconnect_cast_client(cast_client, timeout=2):
    if not cast_client:
        return
    try:
        cast_client.disconnect(timeout=timeout)
    except TypeError:
        try:
            cast_client.disconnect()
        except Exception:
            logger.exception("Failed to disconnect Chromecast client")
    except Exception:
        logger.exception("Failed to disconnect Chromecast client")


def _replace_active_cast(cast_client):
    global cast, mc
    stale_casts = []
    with cast_lock:
        if cast and cast is not cast_client:
            stale_casts.append(cast)
            active_casts.discard(cast)
        cast = cast_client
        mc = cast_client.media_controller if cast_client else None
        if cast_client:
            active_casts.add(cast_client)

    for stale_cast in stale_casts:
        _disconnect_cast_client(stale_cast)


def _disconnect_all_casts():
    global cast, mc
    with cast_lock:
        casts_to_disconnect = list(active_casts)
        if cast and cast not in active_casts:
            casts_to_disconnect.append(cast)
        active_casts.clear()
        cast = None
        mc = None

    for cast_client in casts_to_disconnect:
        _disconnect_cast_client(cast_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init
    await startup_event(app)
    try:
        yield
    finally:
        _disconnect_all_casts()
        cast_executor.shutdown(wait=False, cancel_futures=True)

async def startup_event(app: FastAPI):
    """Discover Chromecast using CastBrowser at startup."""
    global cast, mc, MP3_FOLDER
      
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
    refresh_device_ips()

    # Initialize telemetry
    telemetry = TelemetryService()
    await telemetry.initialize()
    app.telemetry = telemetry
    app.include_router(get_telemetry_router(telemetry), prefix="/telemetry", tags=["telemetry"])

app = FastAPI(lifespan=lifespan)

class PlayRequest(BaseModel):
    track: str
    device: str
    
def get_mp3_file_names():
    try:
        files = [f[:-4] for f in os.listdir(MP3_FOLDER) if os.path.isfile(os.path.join(MP3_FOLDER, f)) and f.lower().endswith('.mp3')]
        return files
    except Exception as e:
        logger.exception("Failed to list tracks in %s: %s", MP3_FOLDER, e)
        return []


def _play_on_cast_blocking(device_ip: str, track_url: str, safe_filename: str):
    """Run pychromecast operations off the event loop with explicit timeouts."""
    local_cast = None
    local_mc = None
    try:
        local_cast = pychromecast.get_chromecast_from_host(
            (device_ip, GOOGLE_HOME_PORT, None, None, None),
            tries=CAST_CONNECT_TRIES,
            retry_wait=CAST_CONNECT_RETRY_WAIT,
            timeout=CAST_CONNECT_TIMEOUT,
        )
        local_cast.wait(timeout=CAST_WAIT_TIMEOUT)
        local_mc = local_cast.media_controller
        logger.info("Connected to Chromecast at %s (%s)", device_ip, local_cast.cast_info)
        local_mc.block_until_active(timeout=CAST_CONTROLLER_TIMEOUT)
        logger.info("Media controller ready for %s", device_ip)
    except Exception as e:
        _disconnect_cast_client(local_cast)
        raise CastPlaybackError(f"Connection failed: {e}") from e

    _replace_active_cast(local_cast)

    try:
        local_mc.stop()
        logger.info("Stopped any existing playback on %s", device_ip)
        time.sleep(1)
    except Exception as e:
        logger.warning("Could not stop existing playback (may not be playing anything): %s", e)

    logger.info("Waiting to play media %s", track_url)
    for attempt in range(CAST_PLAY_RETRIES):
        try:
            logger.info(
                "Attempting to play media %s (attempt %s/%s)",
                track_url,
                attempt + 1,
                CAST_PLAY_RETRIES,
            )
            local_mc.play_media(
                track_url,
                "audio/mp3",
                title=f"Playing {safe_filename}",
                subtitles="From audio Stream Server",
            )
            logger.info("Successfully sent play command for %s", safe_filename)
            return
        except pychromecast.error.NotConnected as e:
            logger.warning("Cast not ready, retrying...")
            if attempt < CAST_PLAY_RETRIES - 1:
                time.sleep(CAST_PLAY_RETRY_WAIT)
                continue
            raise CastPlaybackError(
                f"Cast not ready after {CAST_PLAY_RETRIES} retries"
            ) from e
        except Exception as e:
            raise CastPlaybackError(f"Playback failed: {e}") from e
    
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

@app.get("/listdevices")
def list_tracks():
    """List of device available."""
    try:
        refresh_device_ips()
        device_names = list(DEVICE_IPS.keys())
        return {"devices": device_names}
    except Exception as e:
        logger.exception("Failed to list devices: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list devices")
    
@app.post("/play")
async def play(req: PlayRequest, request: Request):
    """Play an MP3 file by filename (track)."""
    track = req.track
    safe_filename = os.path.basename(track)
    safe_filename_with_ext = safe_filename + ".mp3"
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid track name")

    files = get_mp3_file_names()
    if safe_filename not in files:
        raise HTTPException(status_code=404, detail="Track not found")

    local_path = os.path.join(MP3_FOLDER, safe_filename_with_ext)
    logger.info(
        "Requested track: %s, safe filename: %s, local path: %s",
        track,
        safe_filename_with_ext,
        local_path,
    )
    if not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail="Track not found")

    try:
        await asyncio.wait_for(
            asyncio.to_thread(refresh_device_ips),
            timeout=DEVICE_REFRESH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Device discovery timed out after %ss; using cached device list",
            DEVICE_REFRESH_TIMEOUT,
        )

    device_ip = DEVICE_IPS.get(req.device)
    if not device_ip:
        raise HTTPException(status_code=400, detail="Invalid device name")

    logger.info(
        "Play request received for track: %s on device: %s (%s)",
        track,
        req.device,
        device_ip,
    )
    track_url = f"http://{IP_SERVER.rstrip('/')}:{PORT_SERVER}{MP3_ROUTE}/{quote(safe_filename_with_ext)}"

    loop = asyncio.get_running_loop()
    play_job = functools.partial(
        _play_on_cast_blocking,
        device_ip,
        track_url,
        safe_filename,
    )
    try:
        await asyncio.wait_for(
            loop.run_in_executor(cast_executor, play_job),
            timeout=CAST_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        message = f"Cast operation timed out after {CAST_REQUEST_TIMEOUT:g}s"
        logger.exception(message)
        try:
            await app.telemetry.record_playback(
                track_name=safe_filename,
                device_name=req.device,
                device_ip=device_ip,
                status="failed",
                error_message=message,
            )
        except Exception:
            logger.exception("Failed to record telemetry for cast timeout")
        raise HTTPException(status_code=504, detail=message)
    except CastPlaybackError as e:
        message = str(e)
        logger.exception("Cast playback failed for %s on %s", safe_filename, device_ip)
        try:
            await app.telemetry.record_playback(
                track_name=safe_filename,
                device_name=req.device,
                device_ip=device_ip,
                status="failed",
                error_message=message,
            )
        except Exception:
            logger.exception("Failed to record telemetry for playback failure")
        raise HTTPException(status_code=503, detail=message)

    try:
        await app.telemetry.record_playback(
            track_name=safe_filename,
            device_name=req.device,
            device_ip=device_ip,
            status="success",
        )
    except Exception:
        logger.exception("Failed to record telemetry for successful playback")

    return {"status": "ok", "track_url": track_url}

if __name__ == "__main__":

    # Run in development mode, reload allows hot-reload when you change the code
    uvicorn.run("main:app", host="0.0.0.0", port=PORT_SERVER, reload=ENV=="development")