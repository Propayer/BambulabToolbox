$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"
$InstallationFailed = $false

try {
    Write-Host "Comprobando Python..."
    $SystemPython = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Python\pythoncore-*\python.exe") -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName

    if (-not $SystemPython) {
        throw "No se encuentra Python instalado en AppData\Local\Python."
    }

    & $SystemPython --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python devolvio el codigo de error $LASTEXITCODE."
    }

    if (-not (Test-Path $VenvDir)) {
        Write-Host "Creando el entorno virtual..."
        & $SystemPython -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo crear el entorno virtual. Codigo: $LASTEXITCODE."
        }
    }

    $PythonExe = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) {
        throw "No se encuentra el Python del entorno virtual en: $PythonExe"
    }

    Write-Host "Actualizando pip..."
    & $PythonExe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la actualizacion de pip. Codigo: $LASTEXITCODE."
    }

    Write-Host "Instalando dependencias..."
    & $PythonExe -m pip install -r (Join-Path $ProjectDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la instalacion de dependencias. Codigo: $LASTEXITCODE."
    }

    $ConfigPath = Join-Path $ProjectDir "config.yaml"
    if (-not (Test-Path $ConfigPath)) {
        Copy-Item (Join-Path $ProjectDir "config.example.yaml") $ConfigPath
    }

    Write-Host ""
    Write-Host "Instalacion completada. Revisa config.yaml antes de la primera ejecucion." -ForegroundColor Green
}
catch {
    $InstallationFailed = $true
    Write-Host ""
    Write-Host "LA INSTALACION HA FALLADO" -ForegroundColor Red
    Write-Host "Detalle del error:" -ForegroundColor Yellow
    Write-Host $_.Exception.Message -ForegroundColor Red

    if ($_.InvocationInfo.PositionMessage) {
        Write-Host ""
        Write-Host $_.InvocationInfo.PositionMessage -ForegroundColor DarkGray
    }
}
finally {
    Write-Host ""
    Read-Host "Pulsa Intro para cerrar esta ventana"
}

if ($InstallationFailed) {
    exit 1
}
