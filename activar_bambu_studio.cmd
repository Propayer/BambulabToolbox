@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m jarvis_bambu.activate_bambu --debug
if errorlevel 1 pause
