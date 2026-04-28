#!/bin/bash
set -e
cd "$(dirname "$0")"

DEV_MODE=0
if [ "${1:-}" = "--dev" ]; then
    DEV_MODE=1
fi

# Check prerequisites
missing=""

if ! command -v python3 &> /dev/null; then
    missing="$missing python3"
fi

if ! command -v yt-dlp &> /dev/null; then
    missing="$missing yt-dlp"
fi

if ! command -v ffmpeg &> /dev/null; then
    missing="$missing ffmpeg"
fi

if [ -n "$missing" ]; then
    echo "Missing required tools:$missing"
    echo ""
    if command -v brew &> /dev/null; then
        echo "Install with:  brew install$missing"
    elif command -v apt &> /dev/null; then
        echo "Install with:  sudo apt install$missing"
    else
        echo "Please install:$missing"
    fi
    exit 1
fi

# Set up venv and install Python deps
if [ ! -d "venv" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q flask yt-dlp
else
    source venv/bin/activate
fi

PORT="${PORT:-8899}"
export PORT

if [ "$DEV_MODE" = "1" ]; then
    export RECLIP_DEV_RELOAD=1

    if command -v lsof &> /dev/null; then
        existing_pids="$(lsof -ti tcp:"$PORT" -sTCP:LISTEN || true)"
        if [ -n "$existing_pids" ]; then
            echo "Stopping existing server on port $PORT..."
            kill $existing_pids || true
            sleep 0.4
        fi
    fi

    if command -v open &> /dev/null; then
        (sleep 1.2 && open "http://localhost:$PORT") &
    fi
fi

echo ""
echo "  ReClip is running at http://localhost:$PORT"
if [ "$DEV_MODE" = "1" ]; then
    echo "  Dev mode: Flask reload + browser auto-refresh enabled"
fi
echo ""
python3 app.py
