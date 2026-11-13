#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)
echo "Setup done. Now run ./start.sh"
