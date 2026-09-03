@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Falta .venv. Ejecuta primero setup_dev.cmd.
    exit /b 1
)
".venv\Scripts\python.exe" -m jarvis_bambu.gui
exit /b %ERRORLEVEL%
