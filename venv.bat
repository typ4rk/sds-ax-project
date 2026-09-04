@echo off
cd /d "%~dp0"
powershell -NoExit -ExecutionPolicy Bypass -Command "& .\.venv\Scripts\Activate.ps1"