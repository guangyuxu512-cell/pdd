@echo off
ping 127.0.0.1 -n 4 >nul
start "" "http://127.0.0.1:8800/"
