@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "LOGDIR=%ROOT%\.runlogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\backend-window.log"
echo [%date% %time%] backend_server.cmd > "%LOG%"
echo ROOT=%ROOT% >> "%LOG%"

cd /d "%ROOT%\backend" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Failed to enter backend directory: "%ROOT%\backend"
  echo Failed to enter backend directory. >> "%LOG%"
  pause
  exit /b 1
)

echo Backend: http://127.0.0.1:8800/docs
echo.
"%ROOT%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8800
echo.
echo Backend exited.
pause
