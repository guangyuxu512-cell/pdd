@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "LOGDIR=%ROOT%\.runlogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\frontend-window.log"
echo [%date% %time%] frontend_server.cmd > "%LOG%"
echo ROOT=%ROOT% >> "%LOG%"

subst X: /D >nul 2>nul
subst X: "%ROOT%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Failed to map X: to "%ROOT%"
  echo Failed to map X:. >> "%LOG%"
  pause
  exit /b 1
)

cd /d X:\frontend
if errorlevel 1 (
  echo Failed to enter frontend directory.
  echo Failed to enter frontend directory. >> "%LOG%"
  pause
  exit /b 1
)

echo Frontend: http://127.0.0.1:5173
echo.
if not exist node_modules call npm install
call npm run dev -- --host 127.0.0.1 --port 5173
echo.
echo Frontend exited.
pause
