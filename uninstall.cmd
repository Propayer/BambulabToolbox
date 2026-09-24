@echo off
setlocal
set "LOCAL_PS=%~dp0scripts\uninstall.ps1"
set "STATE_PS=%LOCALAPPDATA%\CajaHerramientasBambuLab\installer\uninstall.ps1"

if exist "%LOCAL_PS%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LOCAL_PS%"
    exit /b %ERRORLEVEL%
)

if exist "%STATE_PS%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STATE_PS%"
    exit /b %ERRORLEVEL%
)

echo ERROR: No se encuentra el desinstalador de BambuLab Toolbox.
exit /b 1
