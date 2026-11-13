@echo off
REM Runs all backend (pytest) and frontend (vitest) tests. Run setup.bat once first.
cd /d %~dp0
echo ===== Backend tests (pytest) =====
cd backend
.venv\Scripts\python -m pytest -v
set BACK=%ERRORLEVEL%
cd ..\frontend
echo.
echo ===== Frontend tests (vitest) =====
call npm test
set FRONT=%ERRORLEVEL%
cd ..
echo.
if %BACK%==0 if %FRONT%==0 (echo ALL TESTS PASSED & exit /b 0)
echo SOME TESTS FAILED (backend=%BACK%, frontend=%FRONT%)
exit /b 1
