@echo off
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m jarvis_bambu.optimize_current --open-ready separate
if errorlevel 1 pause
