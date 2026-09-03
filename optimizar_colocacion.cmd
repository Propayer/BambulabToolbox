@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
if "%~1"=="" (
  echo Uso: optimizar_colocacion.cmd archivo.3mf simple^|advanced low^|medium^|high same^|separate^|none
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -m jarvis_bambu.optimize_main "%~1" --mode "%~2" --effort "%~3" --open "%~4"
if errorlevel 1 pause
