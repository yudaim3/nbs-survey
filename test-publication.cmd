@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-publication.ps1"
if errorlevel 1 echo TEST FAILED. Please keep the error message and test-results log.
pause
