#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SERVICE_NAME="${SERVICE_NAME:-audio-book.service}"
SERVICE_USER="${SERVICE_USER:-$USER}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_step() {
  echo -e "${YELLOW}$1${NC}"
}

log_ok() {
  echo -e "${GREEN}$1${NC}"
}

log_err() {
  echo -e "${RED}$1${NC}" >&2
}

if [[ "${EUID}" -eq 0 ]]; then
  log_err "Do not run scripts/install-prod.sh via sudo."
  log_err "Run it as ${SERVICE_USER} from the app checkout; the script uses sudo only for system packages and systemd."
  exit 1
fi

check_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    log_err "Required command missing: $name"
    exit 1
  fi
}

require_file() {
  local path="$1"
  local description="$2"
  if [[ ! -f "${path}" ]]; then
    log_err "Missing ${description}: ${path}"
    exit 1
  fi
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi
  if ! command -v curl >/dev/null 2>&1; then
    log_err "uv is required and curl is not installed to bootstrap it"
    exit 1
  fi
  log_step "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  if ! command -v uv >/dev/null 2>&1; then
    log_err "uv installation completed but uv is still not on PATH"
    exit 1
  fi
}

ensure_system_packages() {
  if command -v avahi-browse >/dev/null 2>&1; then
    log_ok "avahi-browse is installed"
    return
  fi
  if command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
    log_step "Installing avahi-utils for Google Cast discovery..."
    sudo apt-get update
    sudo apt-get install -y avahi-utils
  else
    log_err "Missing avahi-browse. Install avahi-utils on the production host."
    exit 1
  fi
}

ensure_env_file() {
  if [[ ! -f "${APP_DIR}/.env" ]]; then
    if [[ -f "${APP_DIR}/.env.example" ]]; then
      log_step "Creating .env from .env.example..."
      cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    else
      log_err "Missing .env and .env.example in ${APP_DIR}"
      exit 1
    fi
  fi

  local env_file="${APP_DIR}/.env"
  local ip_server port_server mp3_folder

  ip_server="$(awk -F= '/^AB_IP_SERVER=/{print $2}' "${env_file}" | tail -n 1 | tr -d '[:space:]"')"
  port_server="$(awk -F= '/^AB_PORT_SERVER=/{print $2}' "${env_file}" | tail -n 1 | tr -d '[:space:]"')"
  mp3_folder="$(awk -F= '/^AB_MP3_FOLDER=/{sub(/^AB_MP3_FOLDER=/,""); print}' "${env_file}" | tail -n 1 | tr -d '[:space:]"')"

  if [[ -z "${ip_server}" || "${ip_server}" == "0.0.0.0" || "${ip_server}" == "127.0.0.1" ]]; then
    local host_ip
    host_ip="$(hostname -I | awk '{print $1}')"
    if [[ -n "${host_ip}" ]]; then
      log_step "Setting AB_IP_SERVER=${host_ip} in .env"
      if grep -q '^AB_IP_SERVER=' "${env_file}"; then
        sed -i "s|^AB_IP_SERVER=.*|AB_IP_SERVER=${host_ip}|" "${env_file}"
      else
        echo "AB_IP_SERVER=${host_ip}" >> "${env_file}"
      fi
      ip_server="${host_ip}"
    fi
  fi

  if [[ -z "${port_server}" ]]; then
    log_step "Setting AB_PORT_SERVER=8801 in .env"
    echo "AB_PORT_SERVER=8801" >> "${env_file}"
    port_server="8801"
  fi

  if [[ -z "${mp3_folder}" ]]; then
    mp3_folder="${APP_DIR}/mp3"
    log_step "Setting AB_MP3_FOLDER=${mp3_folder} in .env"
    echo "AB_MP3_FOLDER=${mp3_folder}" >> "${env_file}"
  fi

  if ! grep -q '^AB_ENV=' "${env_file}"; then
    echo "AB_ENV=production" >> "${env_file}"
  fi

  mkdir -p "${mp3_folder}"
  log_ok ".env configured (AB_IP_SERVER=${ip_server}, AB_PORT_SERVER=${port_server})"
}

render_system_unit() {
  local template_path="${APP_DIR}/systemd/${SERVICE_NAME}"
  local output_path="$1"
  require_file "${template_path}" "systemd unit template"
  local uv_bin
  uv_bin="$(command -v uv)"
  if [[ -z "${uv_bin}" ]]; then
    log_err "uv is required to render the systemd unit"
    exit 1
  fi
  sed \
    -e "s|__APP_DIR__|${APP_DIR}|g" \
    -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
    -e "s|__SERVICE_GROUP__|${SERVICE_GROUP}|g" \
    -e "s|__UV_BIN__|${uv_bin}|g" \
    "${template_path}" > "${output_path}"
}

install_system_service() {
  local rendered_unit
  rendered_unit="$(mktemp)"
  trap 'rm -f "${rendered_unit}"' RETURN
  render_system_unit "${rendered_unit}"

  sudo mkdir -p /etc/systemd/system
  sudo install -m 0644 "${rendered_unit}" "/etc/systemd/system/${SERVICE_NAME}"

  rm -f "${HOME}/.config/systemd/user/${SERVICE_NAME}" || true
  systemctl --user disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
  systemctl --user daemon-reload >/dev/null 2>&1 || true

  sudo systemctl daemon-reload
  sudo systemctl enable --now "${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  sudo systemctl --no-pager --full status "${SERVICE_NAME}" | head -20
}

configure_firewall() {
  if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
    log_step "Allowing port 8801/tcp through ufw..."
    sudo ufw allow 8801/tcp
    sudo ufw reload
    log_ok "Firewall updated"
  else
    echo "ufw is not active; skipping firewall configuration"
  fi
}

verify_service() {
  local port
  port="$(awk -F= '/^AB_PORT_SERVER=/{print $2}' "${APP_DIR}/.env" | tail -n 1 | tr -d '[:space:]"')"
  port="${port:-8801}"

  for _ in {1..15}; do
    if curl -sf "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
      log_ok "Service health check passed on port ${port}"
      return
    fi
    sleep 2
  done

  log_err "Service did not respond on port ${port}"
  echo "Check logs with: sudo journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
}

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}Audio Stream Google Home - Production Install${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "App directory: ${APP_DIR}"
echo "Service user:  ${SERVICE_USER}"
echo ""

cd "${APP_DIR}"

if [[ ! -d "${APP_DIR}/.git" ]]; then
  log_err "Not a git repository: ${APP_DIR}"
  echo "Clone first, then rerun:"
  echo "  git clone git@github.com:MrDesjardins/audio-stream-google-home.git"
  echo "  cd audio-stream-google-home"
  echo "  ./scripts/install-prod.sh"
  exit 1
fi

log_step "[1/7] Checking prerequisites..."
ensure_uv
ensure_system_packages
check_command systemctl
check_command sudo
check_command curl
log_ok "Prerequisites ready"
echo ""

log_step "[2/7] Installing Python dependencies..."
uv sync
log_ok "Dependencies installed"
echo ""

log_step "[3/7] Configuring environment..."
ensure_env_file
echo ""

log_step "[4/7] Verifying telemetry database..."
if [[ -f "${APP_DIR}/telemetry.db" ]]; then
  log_ok "Telemetry database exists ($(du -h "${APP_DIR}/telemetry.db" | cut -f1))"
else
  echo "Telemetry database will be created on first startup"
fi
echo ""

log_step "[5/7] Installing systemd service (${SERVICE_NAME})..."
install_system_service
echo ""

log_step "[6/7] Configuring firewall..."
configure_firewall
echo ""

log_step "[7/7] Verifying service..."
verify_service
echo ""

host_ip="$(hostname -I | awk '{print $1}')"
port="$(awk -F= '/^AB_PORT_SERVER=/{print $2}' "${APP_DIR}/.env" | tail -n 1 | tr -d '[:space:]"')"
port="${port:-8801}"

echo -e "${GREEN}Production install complete.${NC}"
echo ""
echo "API:       http://${host_ip}:${port}/"
echo "Dashboard: http://${host_ip}:${port}/telemetry/dashboard"
echo ""
echo "Manage service:"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "Deploy updates from your dev machine with:"
echo "  ./deploy.sh"
