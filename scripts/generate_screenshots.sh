#!/usr/bin/env bash
# ==============================================================================
# KestrelCOP - Automated Tactical UI Screenshot Generator
# ==============================================================================
# Launches local frontend server and captures high-resolution headless browser
# screenshots of the tactical Common Operating Picture dashboard in various
# operational states:
#   1. Overview: Full COP layout, dark basemap, and tracked assets drawer.
#   2. Tracking: Focused operator track with real-time biometric vitals popup.
#   3. ISR Detection: Drone computer-vision target identification overwatch.
#   4. TCCC Alert: Tactical Combat Casualty Care life-safety triage state.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_DIR="${ROOT_DIR}/docs/screenshots"

mkdir -p "${OUTPUT_DIR}"

# Locate Chrome / Chromium binary
CHROME_BIN=""
if [[ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif command -v google-chrome &>/dev/null; then
    CHROME_BIN="$(command -v google-chrome)"
elif command -v chromium &>/dev/null; then
    CHROME_BIN="$(command -v chromium)"
elif command -v chromium-browser &>/dev/null; then
    CHROME_BIN="$(command -v chromium-browser)"
else
    echo "❌ Error: Google Chrome or Chromium binary not found." >&2
    exit 1
fi

echo "🦅 KestrelCOP Screenshot Automation"
echo "Using Browser: ${CHROME_BIN}"
echo "Output Directory: ${OUTPUT_DIR}"

SERVER_PORT=3000
SERVER_URL="http://127.0.0.1:${SERVER_PORT}"
SERVER_PID=""

# Check if Vite server is already responding
if curl -s -I "${SERVER_URL}" | grep -q "200 OK"; then
    echo "✅ Frontend server is already active on ${SERVER_URL}."
else
    echo "🚀 Starting Vite dev server on port ${SERVER_PORT}..."
    cd "${ROOT_DIR}/frontend"
    npm run dev -- --host 127.0.0.1 --port ${SERVER_PORT} &
    SERVER_PID=$!
    cd "${ROOT_DIR}"

    # Wait for server readiness
    MAX_RETRIES=20
    COUNT=0
    until curl -s -I "${SERVER_URL}" | grep -q "200 OK"; do
        sleep 0.5
        COUNT=$((COUNT + 1))
        if [[ ${COUNT} -ge ${MAX_RETRIES} ]]; then
            echo "❌ Timed out waiting for Vite server." >&2
            if [[ -n "${SERVER_PID}" ]]; then kill -9 "${SERVER_PID}" 2>/dev/null || true; fi
            exit 1
        fi
    done
    echo "✅ Vite server is ready."
fi

cleanup() {
    if [[ -n "${SERVER_PID}" ]]; then
        echo "🛑 Terminating temporary Vite server (PID: ${SERVER_PID})..."
        kill "${SERVER_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

CAPTURE() {
    local NAME="$1"
    local URL_PARAMS="$2"
    local TARGET_FILE="${OUTPUT_DIR}/${NAME}.png"

    echo "📸 Capturing: ${NAME}.png (${URL_PARAMS})..."
    "${CHROME_BIN}" \
        --headless=new \
        --screenshot="${TARGET_FILE}" \
        --window-size=1440,900 \
        --virtual-time-budget=6000 \
        "${SERVER_URL}/?${URL_PARAMS}" 2>/dev/null || true

    if [[ -f "${TARGET_FILE}" ]]; then
        local SIZE_KB
        SIZE_KB="$(du -k "${TARGET_FILE}" | cut -f1)"
        echo "   -> Saved: ${TARGET_FILE} (${SIZE_KB} KB)"
    else
        echo "   ⚠️ Warning: Failed writing ${TARGET_FILE}"
    fi
}

# 1. Full Dashboard Overview
CAPTURE "kestrelcop_overview" "sim=true"

# 2. Operator Tracking with Biometric Popup
CAPTURE "kestrelcop_tactical_tracking" "sim=true&selected=kestrel-scout-alpha"

# 3. ISR Drone Object Detection View
CAPTURE "kestrelcop_drone_detection" "sim=true&selected=target-overwatch-01"

# 4. Tactical Combat Casualty Care (TCCC) Alert State
CAPTURE "kestrelcop_tccc_alert" "sim=true&alert=true&selected=kestrel-scout-alpha"

echo "✨ Screenshot generation complete. All images saved to docs/screenshots/."
