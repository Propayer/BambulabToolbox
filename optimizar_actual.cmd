@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
if "%~3"=="" (
  echo Uso: optimizar_actual.cmd simple^|advanced low^|medium^|high^|MINUTOS ask^|same^|separate [preview] [pc^|echo_show] [improvements^|debug]
  pause
  exit /b 2
)
if /I "%~4"=="preview" (
  if "%~5"=="" (
    ".venv\Scripts\python.exe" -m jarvis_bambu.optimize_current --mode "%~1" --effort "%~2" --after "%~3" --preview
  ) else if "%~6"=="" (
    ".venv\Scripts\python.exe" -m jarvis_bambu.optimize_current --mode "%~1" --effort "%~2" --after "%~3" --preview --preview-target "%~5"
  ) else (
    ".venv\Scripts\python.exe" -m jarvis_bambu.optimize_current --mode "%~1" --effort "%~2" --after "%~3" --preview --preview-target "%~5" --preview-mode "%~6"
  )
) else (
  ".venv\Scripts\python.exe" -m jarvis_bambu.optimize_current --mode "%~1" --effort "%~2" --after "%~3"
)
if errorlevel 1 pause
