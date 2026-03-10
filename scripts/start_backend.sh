#!/usr/bin/env bash
# Start the Vestige backend server
set -e
cd "$(dirname "$0")/../backend"
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
