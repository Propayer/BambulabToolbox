@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: No existe .venv. Ejecuta setup_dev.cmd primero.
    exit /b 1
)

echo Comprobando PyInstaller...
".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias de build...
    ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
    if errorlevel 1 exit /b 1
)

if exist "build" rmdir /s /q "build"
if exist "dist\BambuLabToolbox" rmdir /s /q "dist\BambuLabToolbox"

echo Construyendo BambuLabToolbox...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean BambuLabToolbox.spec
if errorlevel 1 exit /b 1

echo.
echo Build completada:
echo %CD%\dist\BambuLabToolbox\BambuLabToolbox.exe
endlocal
