@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Caja de herramientas BambuLab - Setup autonomo Windows
echo ============================================================
echo.

where powershell.exe >nul 2>nul
if errorlevel 1 (
    echo ERROR: Windows PowerShell no esta disponible.
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_dev.ps1" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo El setup termino con errores. Puedes ejecutar uninstall.cmd para revertir lo creado.
    exit /b %RC%
)

echo.
echo Setup completado. Usa el acceso directo "BambuLab Toolbox" del Escritorio.
exit /b 0
