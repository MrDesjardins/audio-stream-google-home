#!/bin/bash

# Audio Stream Google Home - Update and Restart Script
# This script pulls the latest code, updates dependencies, and restarts the service

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}Audio Stream Update Script${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check if we're in a git repository
if [ ! -d "$SCRIPT_DIR/.git" ]; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

cd "$SCRIPT_DIR"

# Show current status
echo -e "${YELLOW}[1/6] Current Status${NC}"
echo "Repository: $(pwd)"
echo "Current branch: $(git branch --show-current)"
echo "Current commit: $(git log -1 --oneline)"
echo ""

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${YELLOW}Warning: You have uncommitted changes:${NC}"
    git status --short
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Update cancelled${NC}"
        exit 1
    fi
fi

# Pull latest changes
echo -e "${YELLOW}[2/6] Pulling Latest Changes${NC}"
git fetch origin
BEFORE_COMMIT=$(git rev-parse HEAD)
git pull origin $(git branch --show-current)
AFTER_COMMIT=$(git rev-parse HEAD)

if [ "$BEFORE_COMMIT" = "$AFTER_COMMIT" ]; then
    echo -e "${GREEN}Already up to date${NC}"
else
    echo -e "${GREEN}Updated to:${NC}"
    git log --oneline $BEFORE_COMMIT..$AFTER_COMMIT
fi
echo ""

# Update dependencies
echo -e "${YELLOW}[3/6] Updating Dependencies${NC}"
if command -v uv &> /dev/null; then
    uv sync
    echo -e "${GREEN}Dependencies updated${NC}"
else
    echo -e "${RED}Error: uv not found. Please install uv first.${NC}"
    echo "Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo ""

# Initialize/verify telemetry database
echo -e "${YELLOW}[4/6] Verifying Telemetry Database${NC}"
if [ -f "$SCRIPT_DIR/telemetry.db" ]; then
    echo -e "${GREEN}Telemetry database exists ($(du -h "$SCRIPT_DIR/telemetry.db" | cut -f1))${NC}"
else
    echo "Telemetry database will be created on first startup"
fi
echo ""

# Restart service
echo -e "${YELLOW}[5/6] Restarting Service${NC}"
if systemctl is-active --quiet audio-book.service 2>/dev/null; then
    echo "Stopping audio-book.service..."
    sudo systemctl stop audio-book.service
    echo "Starting audio-book.service..."
    sudo systemctl start audio-book.service
    echo -e "${GREEN}Service restarted${NC}"
elif [ -f /etc/systemd/system/audio-book.service ]; then
    echo "Service is not running. Starting audio-book.service..."
    sudo systemctl start audio-book.service
    echo -e "${GREEN}Service started${NC}"
else
    echo -e "${YELLOW}Warning: systemd service not found${NC}"
    echo "To install the service, run:"
    echo "  sudo cp systemd/audio-book.service /etc/systemd/system/"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now audio-book.service"
    echo ""
    echo -e "${BLUE}Skipping service restart (not installed)${NC}"
fi
echo ""

# Show service status and logs
echo -e "${YELLOW}[6/6] Service Status${NC}"
if systemctl is-active --quiet audio-book.service 2>/dev/null; then
    sudo systemctl status audio-book.service --no-pager -l | head -20
    echo ""
    echo -e "${BLUE}Recent logs:${NC}"
    sudo journalctl -u audio-book -n 20 --no-pager
    echo ""
    echo -e "${GREEN}✓ Update completed successfully!${NC}"
    echo ""
    echo "Service is running at: http://$(hostname -I | awk '{print $1}'):8801"
    echo "Telemetry dashboard: http://$(hostname -I | awk '{print $1}'):8801/telemetry/dashboard"
else
    echo -e "${YELLOW}Service is not running via systemd${NC}"
    echo ""
    echo -e "${GREEN}✓ Update completed!${NC}"
    echo ""
    echo "To start the server manually, run:"
    echo "  cd $SCRIPT_DIR"
    echo "  make server"
fi

echo ""
echo -e "${BLUE}======================================${NC}"
