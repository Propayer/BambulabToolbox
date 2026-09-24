$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppDataDir = Join-Path $env:LOCALAPPDATA "CajaHerramientasBambuLab"
$StateRoot = Join-Path $AppDataDir "installer"
$StatePath = Join-Path $StateRoot "install_state.json"
$BackupRoot = Join-Path $StateRoot "backup"

if (-not (Test-Path $StatePath)) {
    Write-Host "No existe una instalacion gestionada por setup_dev.cmd." -ForegroundColor Yellow
    exit 0
}

$state = Get-Content $StatePath -Raw | ConvertFrom-Json
$ProjectDir = [string]$state.project_dir
$InstallDir = [string]$state.install_dir
$ShortcutPath = [string]$state.shortcut_path

function Restore-Backup([string]$BackupName,[string]$Destination,[bool]$ExistedBefore) {
    $backup = Join-Path $BackupRoot $BackupName
    if (Test-Path $Destination) {
        Remove-Item $Destination -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($ExistedBefore -and (Test-Path $backup)) {
        $parent = Split-Path -Parent $Destination
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        Move-Item $backup $Destination
    }
}

Write-Host ""
Write-Host "Revirtiendo la instalacion de Caja de herramientas BambuLab..." -ForegroundColor Cyan

Get-Process BambuLabToolbox -ErrorAction SilentlyContinue | ForEach-Object {
    try { $_.CloseMainWindow() | Out-Null } catch {}
}
Start-Sleep -Milliseconds 500
Get-Process BambuLabToolbox -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Restore-Backup "desktop_shortcut.lnk" $ShortcutPath ([bool]$state.shortcut_existed_before)
Restore-Backup "installed_app" $InstallDir ([bool]$state.install_dir_existed_before)

if ($ProjectDir -and (Test-Path $ProjectDir)) {
    Restore-Backup "venv" (Join-Path $ProjectDir ".venv") ([bool]$state.venv_existed_before)
    Restore-Backup "build" (Join-Path $ProjectDir "build") ([bool]$state.build_existed_before)
    Restore-Backup "dist" (Join-Path $ProjectDir "dist") ([bool]$state.dist_existed_before)

    if (-not [bool]$state.config_existed_before) {
        Remove-Item (Join-Path $ProjectDir "config.yaml") -Force -ErrorAction SilentlyContinue
    }
}

if ([bool]$state.bambu_installed_by_setup -and -not [bool]$state.bambu_present_before) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Desinstalando Bambu Studio instalado por setup..." -ForegroundColor Cyan
        & $winget.Source uninstall --id ([string]$state.bambu_package_id) --exact --silent --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "winget no pudo desinstalar Bambu Studio automaticamente."
        }
    }
}

$removePython = [bool]$state.python_installed_by_setup -and -not [bool]$state.python_present_before
$pythonMethod = [string]$state.python_install_method
$pythonInstaller = [string]$state.python_installer
$pythonPackageId = [string]$state.python_package_id
$appDataExistedBefore = [bool]$state.app_data_dir_existed_before

if ($removePython) {
    Write-Host "Desinstalando Python instalado por setup..." -ForegroundColor Cyan
    if ($pythonMethod -eq "winget") {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if ($winget) {
            & $winget.Source uninstall --id $pythonPackageId --exact --silent --accept-source-agreements
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "winget no pudo desinstalar Python automaticamente."
            }
        } else {
            Write-Warning "Python fue instalado con winget, pero winget ya no esta disponible."
        }
    } elseif ($pythonMethod -eq "direct") {
        if (Test-Path $pythonInstaller) {
            $process = Start-Process -FilePath $pythonInstaller -ArgumentList @("/uninstall","/quiet") -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                Write-Warning "El instalador de Python devolvio codigo $($process.ExitCode) al desinstalar."
            }
        } else {
            Write-Warning "No se conserva el instalador con el que setup instalo Python."
        }
    }
}

if ($appDataExistedBefore) {
    Remove-Item $StateRoot -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Remove-Item $AppDataDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "DESINSTALACION COMPLETADA" -ForegroundColor Green
Write-Host "Se han restaurado los elementos que existian antes de setup_dev.cmd."
