# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based service that streams MP3 files to Google Home/Chromecast devices over the local network. It's part of a larger audiobook streaming system (see AudioBookArchitecture.png) that includes ESP-32 hardware components and TFT displays.

## Development Commands

### Running the Server

```bash
make server
```

This starts the FastAPI server with hot-reload enabled (runs `uv run ./src/audio-stream-google-home/main.py --reload`).

### Manual Server Start

```bash
uv run ./src/audio-stream-google-home/main.py
```

### Testing the API

```bash
# List available tracks
curl http://localhost:8801/list

# List available devices
curl http://localhost:8801/listdevices

# Play a track on a specific device
curl -X POST http://localhost:8801/play \
     -H "Content-Type: application/json" \
     -d '{"track": "Adventure_05_Tom_Sawyer", "device": "Jacob"}'
```

## Architecture

### Single-File Application

The entire backend is contained in `src/audio-stream-google-home/main.py` - a self-contained FastAPI application (~200 lines).

### Key Components

1. **FastAPI Server**: Serves both the API endpoints and static MP3 files
2. **PyChromecast Integration**: Uses `pychromecast` library to discover and control Chromecast/Google Home devices
3. **Static File Serving**: MP3 files are mounted at `/mp3` route and served directly to cast devices
4. **Device Registry**: Hardcoded `DEVICE_IPS` dictionary maps device names to IP addresses

### Configuration via Environment Variables

All configuration is loaded from `.env` file (see `.env.example`):

- `AB_ENV`: Environment mode (development/production)
- `AB_PORT_SERVER`: Server port (default: 8801)
- `AB_IP_SERVER`: Server IP that Google Home devices will use to download MP3s
- `AB_MP3_FOLDER`: Directory containing MP3 files (defaults to `./mp3`)

The code explicitly loads `.env` from the repository root regardless of current working directory using `Path(__file__).resolve().parents[2] / ".env"`.

### Playback Flow

1. Client POSTs to `/play` with `{"track": "filename", "device": "DeviceName"}`
2. Server validates track exists in MP3 folder
3. Server connects to specific Chromecast device using IP from `DEVICE_IPS`
4. Server stops any currently playing media
5. Server sends MP3 URL (`http://{IP_SERVER}:{PORT}/mp3/{track}.mp3`) to the device's media controller
6. Device fetches and plays the MP3 directly from the FastAPI static file server

### Connection Handling

The server uses `get_chromecast_from_host()` for each play request rather than maintaining persistent connections. After getting the cast object, it:
1. Calls `cast.wait()` to ensure connection
2. Calls `mc.block_until_active(timeout=10)` to wait for media controller readiness
3. Implements retry logic (5 attempts) for the `play_media()` call

### Telemetry System

The service includes a built-in telemetry system that tracks all playback events:

**Database**: SQLite database (`telemetry.db`) automatically created on first startup
- Tracks: track name, device name/IP, timestamp (UTC), status (success/failed), error messages
- Indexed for fast queries on timestamp, track name, and device name

**Web Dashboard**: Interactive visualization at `/telemetry/dashboard`
- Daily, weekly, and monthly playback charts (Chart.js)
- Top tracks table with play counts
- Auto-refresh capability
- Responsive dark theme design

**API Endpoints**:
```bash
# System health
curl http://localhost:8801/telemetry/health

# Recent playback events
curl http://localhost:8801/telemetry/events/recent?limit=10

# Statistics (daily/weekly/monthly)
curl http://localhost:8801/telemetry/stats/daily?limit=30
curl http://localhost:8801/telemetry/stats/weekly?limit=12
curl http://localhost:8801/telemetry/stats/monthly?limit=12

# Most popular tracks
curl http://localhost:8801/telemetry/stats/top-tracks?limit=10&days=30
```

**Implementation**:
- Module: `src/audio-stream-google-home/telemetry.py`
- Dashboard: `src/audio-stream-google-home/templates/telemetry_dashboard.html`
- Async operations ensure telemetry never blocks playback
- All telemetry errors are caught and logged without affecting core functionality

## WSL Development Setup

When developing on WSL, the Google Home devices need network access to the WSL instance:

1. Get Windows host IP: `ipconfig` in CMD
2. Get WSL IP: `ip addr show eth0` in WSL
3. Set up port forwarding in PowerShell (admin):
   ```powershell
   netsh interface portproxy add v4tov4 listenaddress=<HOST_IP> listenport=8801 connectaddress=<WSL_IP> connectport=8801
   New-NetFirewallRule -DisplayName "WSL FastAPI" -Direction Inbound -LocalPort 8801 -Protocol TCP -Action Allow
   ```

## Production Deployment

### Quick Update Script

The `update.sh` script handles the complete update process:

```bash
./update.sh
```

This script will:
1. Pull the latest git changes
2. Update dependencies with `uv sync`
3. Verify telemetry database exists (creates on first startup if missing)
4. Restart the systemd service
5. Display service status and recent logs

**Note:** The script requires `sudo` access to restart the service.

### Manual Deployment

#### Systemd Service

The service is deployed using systemd. Template is in `systemd/audio-book.service`:

```bash
# Install service
sudo cp systemd/audio-book.service /etc/systemd/system/audio-book.service
sudo systemctl daemon-reload
sudo systemctl enable --now audio-book.service

# Manage service
sudo systemctl start audio-book.service
sudo systemctl stop audio-book.service
sudo systemctl restart audio-book.service

# View logs
sudo journalctl -u audio-book -n 100 -f
```

### Firewall Configuration

```bash
sudo ufw allow 8801/tcp
sudo ufw reload
```

## Device Registry

To add a new Google Home/Chromecast device, update the `DEVICE_IPS` dictionary in `main.py:39-45` with the device name and its static IP address.

## Debugging Network Issues

```bash
# Check if Google Home is reachable
ping <GOOGLE_HOME_IP>

# Check if Chromecast port is accessible
nc -zv <GOOGLE_HOME_IP> 8009
```
