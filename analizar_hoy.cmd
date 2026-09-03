@echo off
set "PROJECT_DIR=%~dp0"
set "PYTHONPATH=%PROJECT_DIR%src"
"%PROJECT_DIR%.venv\Scripts\python.exe" -m jarvis_bambu.main --mode today --config "%PROJECT_DIR%config.yaml"
