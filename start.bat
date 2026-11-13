@echo off
REM Starts the backend (port 8000) in a new window and the frontend (port 5173) here.
cd /d %~dp0
start "taxi-backend" cmd /k "cd backend && .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
cd frontend
call npm run dev
