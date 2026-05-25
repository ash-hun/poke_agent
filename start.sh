#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROM="$SCRIPT_DIR/Pokemon - Gold Version (K).gbc"
LUA="$SCRIPT_DIR/.local-tools/mgba-http/mGBASocketServer.lua"
MGBA_HTTP="$SCRIPT_DIR/.local-tools/mgba-http/mGBA-http"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV="$SCRIPT_DIR/.venv"

MGBA_HTTP_PID=""
UVICORN_PID=""

cleanup() {
  echo ""
  echo "Shutting down…"
  [[ -n "$UVICORN_PID"   ]] && kill "$UVICORN_PID"   2>/dev/null || true
  [[ -n "$MGBA_HTTP_PID" ]] && kill "$MGBA_HTTP_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Kill leftovers ────────────────────────────────────────────────────────────
echo "Cleaning up previous processes…"
pkill -f "uvicorn backend.main"  2>/dev/null || true
pkill -f "tsx src/index"         2>/dev/null || true
pkill -f "mGBA-http"             2>/dev/null || true
sleep 1

# ── Python venv + deps ────────────────────────────────────────────────────────
if [[ ! -d "$VENV" ]]; then
  echo "Creating Python venv…"
  python3 -m venv "$VENV"
fi

echo "Installing Python dependencies…"
"$VENV/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"

# ── mGBA ─────────────────────────────────────────────────────────────────────
echo "Starting mGBA…"
open -a mGBA "$ROM"
sleep 3

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " mGBA에서 Lua 스크립트를 수동으로 로드하세요:"
echo "  Tools → Scripting → Open Script"
echo "  파일: $LUA"
echo "  커맨드: dofile($LUA)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -r -p "스크립트 로드 완료 후 Enter를 누르세요… "

# ── mGBA-http bridge ──────────────────────────────────────────────────────────
echo "Starting mGBA-http bridge (port 5123)…"
cd "$SCRIPT_DIR/.local-tools/mgba-http"
./mGBA-http &
MGBA_HTTP_PID=$!
cd "$SCRIPT_DIR"
sleep 1

# ── FastAPI backend ───────────────────────────────────────────────────────────
echo ""
echo "Starting FastAPI backend…"
echo "  Controller UI → http://localhost:8000/dashboard/"
echo "  API docs      → http://localhost:8000/docs"
echo ""

cd "$SCRIPT_DIR"
PYTHONPATH="$BACKEND_DIR" "$VENV/bin/uvicorn" main:app \
  --app-dir "$BACKEND_DIR" \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info &
UVICORN_PID=$!
sleep 2

# Open browser
open "http://localhost:8000/dashboard/" 2>/dev/null || true

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Agent is ready. Use the Controller UI to start."
echo " Press Ctrl-C to stop everything."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

wait "$UVICORN_PID"
