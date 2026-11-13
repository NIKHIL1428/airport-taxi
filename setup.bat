@echo off
REM One-time setup (Windows): Python venv + backend deps, then frontend deps.
cd /d %~dp0
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend
call npm install
cd ..
echo Setup done. Now run start.bat
