#!/usr/bin/env bash
set -euo pipefail

echo "Creating virtual environment..."
python3 -m venv .venv

echo "Installing Python dependencies..."
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -e .

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo ""
  echo "FFmpeg was not found in PATH."
  echo "macOS:  brew install ffmpeg"
  echo "Ubuntu: sudo apt update && sudo apt install ffmpeg"
fi

echo "Running environment check..."
./.venv/bin/python scripts/check_environment.py
