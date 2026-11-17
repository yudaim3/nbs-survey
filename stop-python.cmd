@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-python.ps1"
if errorlevel 1 pause
