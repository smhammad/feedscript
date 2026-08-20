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

# Python 3.10+ is required: yt-dlp dropped 3.9, and on 3.9 pip silently
# resolves it to a release Instagram has since broken. macOS ships 3.9 as
# /usr/bin/python3, so "is python3 installed" is not a sufficient check.
MIN_MINOR=10

py_minor() { "$1" -c 'import sys; print(sys.version_info[1] if sys.version_info[0] == 3 else -1)' 2>/dev/null; }
py_is_new_enough() {
  local m
  m="$(py_minor "$1")"
  [ -n "$m" ] && [ "$m" -ge "$MIN_MINOR" ] 2>/dev/null
}
find_python() {
  local cand resolved v candidates
  candidates="python3.14 python3.13 python3.12 python3.11 python3.10 python3"
  for v in 3.14 3.13 3.12 3.11 3.10; do
    candidates="$candidates /opt/homebrew/bin/python$v /usr/local/bin/python$v"
    candidates="$candidates /Library/Frameworks/Python.framework/Versions/$v/bin/python3"
    candidates="$candidates $HOME/.local/bin/python$v"
  done
  candidates="$candidates /opt/homebrew/bin/python3 /usr/local/bin/python3 $HOME/.pyenv/shims/python3"
  for cand in $candidates; do
    resolved="$(command -v "$cand" 2>/dev/null)" || continue
    [ -n "$resolved" ] || continue
    if py_is_new_enough "$resolved"; then echo "$resolved"; return 0; fi
  done
  return 1
}

# A venv that is already new enough is self-sufficient — no system Python has
# to be found (or installed) at all.
if py_is_new_enough venv/bin/python3; then
  PY="$(pwd)/venv/bin/python3"
  echo "✓ Using existing environment: $("$PY" --version)"
else
  PYTHON="$(find_python || true)"
  if [ -z "$PYTHON" ]; then
    echo "→ Installing Python 3.12 (the system Python is too old for yt-dlp)"
    brew install python@3.12
    # Homebrew lives in /usr/local on Intel Macs, which the shellenv at the
    # top of this script only picked up if brew was already installed.
    if [[ -f /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
    if [[ -f /usr/local/bin/brew ]]; then eval "$(/usr/local/bin/brew shellenv)"; fi
    hash -r
    PYTHON="$(find_python || true)"
  fi
  if [ -z "$PYTHON" ]; then
    echo "✗ Could not find or install Python 3.$MIN_MINOR or newer. Install it from python.org and re-run."
    exit 1
  fi
  echo "✓ Python: $("$PYTHON" --version) ($PYTHON)"

  # Whatever is there is too old or broken; only the search above could fail,
  # and it already succeeded.
  if [ -d venv ]; then
    echo "→ Rebuilding venv (it is not usable with Python 3.$MIN_MINOR+)"
    rm -rf venv
  fi
  echo "→ Creating Python environment"
  "$PYTHON" -m venv venv
  PY="$(pwd)/venv/bin/python3"
fi
echo "✓ venv ready"

if ! command -v ffmpeg &>/dev/null; then
  echo "→ Installing ffmpeg"
  brew install ffmpeg
fi
echo "✓ ffmpeg ready"

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
( sleep 2.5 && open "http://127.0.0.1:8765" ) &

exec "$PY" -m uvicorn app:app --host 127.0.0.1 --port 8765 --reload
