#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load environment variables
if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
else
    echo "ERROR: .env file not found. Copy .env.example to .env and add your API keys."
    exit 1
fi

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg is required. Install with: brew install ffmpeg"
    exit 1
fi

# Backend setup
echo "=== Setting up backend ==="
cd "$ROOT_DIR/backend"
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

# Frontend setup
echo "=== Setting up frontend ==="
cd "$ROOT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

# Start both services
echo "=== Starting services ==="
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

# Which interface to listen on. Loopback by default: every route but the admin
# wipes is unauthenticated, so reaching CleanCut from another machine has to be
# something an operator typed. Set CLEANCUT_HOST=0.0.0.0 in .env to open it up.
BIND_HOST="${CLEANCUT_HOST:-127.0.0.1}"
if [ "$BIND_HOST" != "127.0.0.1" ] && [ "$BIND_HOST" != "::1" ] && [ "$BIND_HOST" != "localhost" ]; then
    echo ""
    echo "WARNING: CLEANCUT_HOST=$BIND_HOST - CleanCut will be reachable from other machines."
    echo "         Uploads, transcripts and exports are served without authentication."
fi

cd "$ROOT_DIR/backend"
source .venv/bin/activate
uvicorn app.main:app --host "$BIND_HOST" --port 8000 &
BACKEND_PID=$!

cd "$ROOT_DIR/frontend"
npm run dev -- --hostname "$BIND_HOST" &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo "Press Ctrl+C to stop."
echo ""

wait
