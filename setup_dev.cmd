@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo ERROR: No se encontro Python 3.10 o posterior.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creando .venv...
    %PYTHON_CMD% -m venv .venv || exit /b 1
)

echo Actualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
echo Instalando el proyecto en modo editable...
".venv\Scripts\python.exe" -m pip install -e . --no-deps || exit /b 1

if not exist config.yaml copy /Y config.example.yaml config.yaml >nul
echo.
echo Entorno de desarrollo preparado correctamente.
exit /b 0
