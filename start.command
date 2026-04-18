#!/bin/bash
set -e
cd "$(dirname "$0")"

echo ""
echo "  ┌───────────────────────────────────────┐"
echo "  │           Feedscript — Launch         │"
echo "  └───────────────────────────────────────┘"
echo ""

if [[ -f /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
if [[ -f /usr/local/bin/brew ]]; then eval "$(/usr/local/bin/brew shellenv)"; fi

if ! command -v brew &>/dev/null; then
  echo "→ Installing Homebrew (you may be asked for your Mac password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -f /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
fi

if ! command -v python3 &>/dev/null; then
  echo "→ Installing Python 3.11"
  brew install python@3.11
fi
echo "✓ Python: $(python3 --version)"

if ! command -v ffmpeg &>/dev/null; then
  echo "→ Installing ffmpeg"
  brew install ffmpeg
fi
echo "✓ ffmpeg ready"

if [ ! -d venv ]; then
  echo "→ Creating Python environment"
  python3 -m venv venv
fi
PY="$(pwd)/venv/bin/python3"
echo "✓ venv ready"

if ! "$PY" -c "import fastapi, instaloader, whisper" &>/dev/null; then
  echo "→ Installing Python packages (first run can take a few minutes)"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
fi
echo "✓ Packages installed"

echo ""
echo "Starting server at http://127.0.0.1:8765"
echo "Press Ctrl+C to stop."
echo ""

sleep 1
( sleep 1.5 && open "http://127.0.0.1:8765" ) &

exec "$PY" -m uvicorn app:app --host 127.0.0.1 --port 8765 --reload
