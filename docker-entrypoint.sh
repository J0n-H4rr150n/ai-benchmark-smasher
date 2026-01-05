#!/usr/bin/env sh
set -eu

# If Playwright is running headed, provide a virtual display + VNC/noVNC
# so the browser is observable when running inside Docker.
#
# Enable by setting PLAYWRIGHT_HEADLESS=0 (recommended) or ENABLE_NOVNC=1.

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

falsy() {
  case "${1:-}" in
    0|false|FALSE|no|NO|n|N|off|OFF) return 0 ;;
    *) return 1 ;;
  esac
}

ENABLE_NOVNC="${ENABLE_NOVNC:-}"
PLAYWRIGHT_HEADLESS="${PLAYWRIGHT_HEADLESS:-1}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1280x800x24}"

RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
MIGRATION_MAX_RETRIES="${MIGRATION_MAX_RETRIES:-30}"
MIGRATION_RETRY_SLEEP_SECS="${MIGRATION_RETRY_SLEEP_SECS:-2}"

if truthy "$RUN_MIGRATIONS"; then
  echo "[migrations] Running alembic upgrade head"
  i=1
  while :; do
    if alembic upgrade head; then
      echo "[migrations] OK"
      break
    fi
    if [ "$i" -ge "$MIGRATION_MAX_RETRIES" ]; then
      echo "[migrations] Failed after ${MIGRATION_MAX_RETRIES} attempts" >&2
      exit 1
    fi
    echo "[migrations] Retry ${i}/${MIGRATION_MAX_RETRIES} in ${MIGRATION_RETRY_SLEEP_SECS}s..." >&2
    i=$((i + 1))
    sleep "$MIGRATION_RETRY_SLEEP_SECS"
  done
fi

if truthy "$ENABLE_NOVNC" || falsy "$PLAYWRIGHT_HEADLESS"; then
  export DISPLAY=":${DISPLAY_NUM}"
  echo "[noVNC] Starting Xvfb on $DISPLAY ($SCREEN_GEOMETRY)"
  Xvfb "$DISPLAY" -screen 0 "$SCREEN_GEOMETRY" -ac +extension RANDR &

  # Lightweight WM helps some sites behave normally
  if command -v fluxbox >/dev/null 2>&1; then
    echo "[noVNC] Starting fluxbox window manager"
    fluxbox >/dev/null 2>&1 &
  fi

  echo "[noVNC] Starting x11vnc on :$VNC_PORT"
  # no password by default (local dev). Add -passwdfile if you need one.
  x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -forever -shared -nopw -bg -o /tmp/x11vnc.log

  NOVNC_WEB_DIR="${NOVNC_WEB_DIR:-/usr/share/novnc}"
  if [ ! -d "$NOVNC_WEB_DIR" ]; then
    # Debian package sometimes uses /usr/share/novnc
    NOVNC_WEB_DIR="/usr/share/novnc"
  fi

  echo "[noVNC] Starting websockify on :$NOVNC_PORT (serving $NOVNC_WEB_DIR)"
  # websockify provided by the novnc package
  websockify --web="$NOVNC_WEB_DIR" "0.0.0.0:$NOVNC_PORT" "127.0.0.1:$VNC_PORT" &

  echo "[noVNC] Open: http://localhost:${NOVNC_PORT}/vnc.html?autoconnect=1&resize=scale"
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
