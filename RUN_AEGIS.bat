@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0RUN_AEGIS.ps1"
pause
