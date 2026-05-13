@echo off
setlocal EnableExtensions
cd /d "%~dp0"
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\start_shell.ps1" -Port 8800
exit /b 0
