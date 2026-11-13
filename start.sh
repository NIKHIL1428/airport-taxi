#!/usr/bin/env bash
cd "$(dirname "$0")"
(cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
BACK=$!
trap "kill $BACK" EXIT
cd frontend && npm run dev
