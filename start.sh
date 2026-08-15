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

cd "$ROOT_DIR/backend"
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo "Press Ctrl+C to stop."
echo ""

wait
