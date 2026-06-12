#!/usr/bin/env bash

# Deploy script - push to GitHub and update the production server
# Usage: ./deploy.sh

set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-10.0.0.181}"
REMOTE_USER="${REMOTE_USER:-pdesjardins}"
REMOTE_DIR="${REMOTE_DIR:-/home/pdesjardins/code/audio-stream-google-home}"

echo "Pushing to GitHub..."
git push origin main

echo "Deploying to ${REMOTE_USER}@${REMOTE_HOST}..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "bash -lc '${REMOTE_DIR}/update.sh'"

echo ""
echo "Deploy complete!"
echo "Dashboard: http://${REMOTE_HOST}:8801/telemetry/dashboard"
