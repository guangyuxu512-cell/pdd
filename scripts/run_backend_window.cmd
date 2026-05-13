@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\run_backend_window.ps1" -Port 8800
