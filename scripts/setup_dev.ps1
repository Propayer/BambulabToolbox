param([switch]$SkipBambuStudio)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDir = Split-Path -Parent $PSScriptRoot
$AppDataDir = Join-Path $env:LOCALAPPDATA "CajaHerramientasBambuLab"
$StateRoot = Join-Path $AppDataDir "installer"
$StatePath = Join-Path $StateRoot "install_state.json"
$BackupRoot = Join-Path $StateRoot "backup"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\BambuLabToolbox"
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopDir "BambuLab Toolbox.lnk"
$PythonPackageId = "Python.Python.3.13"
$PythonFallbackVersion = "3.13.15"
$PythonFallbackUrl = "https://www.python.org/ftp/python/$PythonFallbackVersion/python-$PythonFallbackVersion-amd64.exe"
$BambuPackageId = "Bambulab.Bambustudio"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}
function Save-State($State) {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $State | ConvertTo-Json -Depth 6 | Set-Content -Path $StatePath -Encoding UTF8
}
function Get-CompatiblePython {
    $paths = New-Object System.Collections.Generic.List[string]
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($version in @("3.14","3.13","3.12","3.11","3.10")) {
            try {
                $exe = & $py.Source "-$version" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { $paths.Add(($exe | Select-Object -First 1).Trim()) }
            } catch {}
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { $paths.Add($python.Source) }
    foreach ($root in @("HKCU:\Software\Python\PythonCore","HKLM:\Software\Python\PythonCore","HKLM:\Software\WOW6432Node\Python\PythonCore")) {
        if (Test-Path $root) {
            Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
                try {
                    $install = (Get-ItemProperty (Join-Path $_.PSPath "InstallPath") -ErrorAction Stop)."(default)"
                    if ($install) { $paths.Add((Join-Path $install "python.exe")) }
                } catch {}
            }
        }
    }
    $paths.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"))
    $paths.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\BambuToolbox313\python.exe"))
    foreach ($candidate in ($paths | Select-Object -Unique)) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            $versionText = & $candidate -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))" 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $parts = $versionText.Trim().Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -eq 3 -and $minor -ge 10 -and $minor -lt 15) { return (Resolve-Path $candidate).Path }
        } catch {}
    }
    return $null
}
function Find-BambuStudio {
    $programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $candidates = @(
        @(
            (Join-Path $env:ProgramFiles "Bambu Studio\bambu-studio.exe"),
            (Join-Path $programFilesX86 "Bambu Studio\bambu-studio.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Bambu Studio\bambu-studio.exe")
        ) | Where-Object { $_ -and (Test-Path $_) }
    )
    if ($candidates.Count -gt 0) { return $candidates[0] }
    return $null
}
function Backup-Path([string]$Path,[string]$Name) {
    if (-not (Test-Path $Path)) { return }
    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
    $destination = Join-Path $BackupRoot $Name
    if (Test-Path $destination) { throw "Ya existe un backup pendiente: $destination" }
    Move-Item -Path $Path -Destination $destination
}
function Install-Python {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Step "Instalando Python 3.13 con winget"
        & $winget.Source install --id $PythonPackageId --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget no pudo instalar Python. Codigo: $LASTEXITCODE" }
        return @{ method = "winget"; installer = "" }
    }
    Write-Step "winget no esta disponible; descargando Python oficial $PythonFallbackVersion"
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $installer = Join-Path $StateRoot "python-$PythonFallbackVersion-amd64.exe"
    Invoke-WebRequest -Uri $PythonFallbackUrl -OutFile $installer -UseBasicParsing
    $target = Join-Path $env:LOCALAPPDATA "Programs\Python\BambuToolbox313"
    $args = @("/quiet","InstallAllUsers=0","PrependPath=0","Include_launcher=0","Include_test=0","SimpleInstall=1","TargetDir=$target")
    $process = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "El instalador oficial de Python fallo. Codigo: $($process.ExitCode)" }
    return @{ method = "direct"; installer = $installer }
}
function Get-BambuStudioUninstaller {
    $roots = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($key in Get-ChildItem $root -ErrorAction SilentlyContinue) {
            try {
                $p = Get-ItemProperty $key.PSPath -ErrorAction Stop
                if ($p.DisplayName -and $p.DisplayName -like "Bambu Studio*") {
                    if ($p.QuietUninstallString) { return [string]$p.QuietUninstallString }
                    if ($p.UninstallString) { return [string]$p.UninstallString }
                }
            } catch {}
        }
    }
    return ""
}

function Install-BambuStudioIfNeeded($State) {
    if ($SkipBambuStudio) { return }
    if (Find-BambuStudio) {
        Write-Host "Bambu Studio ya estaba instalado; se conserva." -ForegroundColor DarkGray
        return
    }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Step "Instalando Bambu Studio con winget"
        & $winget.Source install --id $BambuPackageId --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0 -and (Find-BambuStudio)) {
            $State.bambu_installed_by_setup = $true
            $State.bambu_install_method = "winget"
            $State.bambu_uninstall_command = Get-BambuStudioUninstaller
            Save-State $State
            return
        }
        Write-Warning "winget no pudo completar Bambu Studio. Se intentara descarga oficial directa."
    }

    Write-Step "Descargando la ultima version oficial de Bambu Studio"
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/bambulab/BambuStudio/releases/latest" -Headers @{ "User-Agent" = "BambuLabToolbox-Setup" }
    $asset = $release.assets | Where-Object { $_.name -match '^Bambu_Studio_win-.*\.exe$' } | Select-Object -First 1
    if (-not $asset) { throw "No se encontro un instalador Windows .exe en la ultima release oficial de Bambu Studio." }

    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $bambuInstaller = Join-Path $StateRoot $asset.name
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $bambuInstaller -UseBasicParsing

    Write-Step "Instalando Bambu Studio desde el instalador oficial"
    $proc = Start-Process -FilePath $bambuInstaller -ArgumentList "/S" -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "El instalador oficial de Bambu Studio fallo. Codigo: $($proc.ExitCode)" }

    Start-Sleep -Seconds 2
    if (-not (Find-BambuStudio)) { throw "Bambu Studio termino de instalarse, pero no se encontro bambu-studio.exe." }

    $State.bambu_installed_by_setup = $true
    $State.bambu_install_method = "direct"
    $State.bambu_installer = $bambuInstaller
    $State.bambu_uninstall_command = Get-BambuStudioUninstaller
    Save-State $State
}

function New-DesktopShortcut {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = Join-Path $InstallDir "BambuLabToolbox.exe"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = (Join-Path $InstallDir "BambuLabToolbox.exe") + ",0"
    $shortcut.Description = "Caja de herramientas BambuLab"
    $shortcut.Save()
}

$firstManagedInstall = -not (Test-Path $StatePath)
$appDataExistedBefore = Test-Path $AppDataDir
if ($firstManagedInstall) {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $pythonBefore = Get-CompatiblePython
    $bambuBefore = Find-BambuStudio
    $state = [ordered]@{
        schema_version = 1
        installed_at = (Get-Date).ToString("o")
        project_dir = $ProjectDir
        app_data_dir_existed_before = $appDataExistedBefore
        python_present_before = [bool]$pythonBefore
        python_path_before = if ($pythonBefore) { $pythonBefore } else { "" }
        python_installed_by_setup = $false
        python_install_method = ""
        python_installer = ""
        python_package_id = $PythonPackageId
        bambu_present_before = [bool]$bambuBefore
        bambu_installed_by_setup = $false
        bambu_package_id = $BambuPackageId
        bambu_install_method = ""
        bambu_installer = ""
        bambu_uninstall_command = ""
        venv_existed_before = Test-Path (Join-Path $ProjectDir ".venv")
        build_existed_before = Test-Path (Join-Path $ProjectDir "build")
        dist_existed_before = Test-Path (Join-Path $ProjectDir "dist")
        config_existed_before = Test-Path (Join-Path $ProjectDir "config.yaml")
        install_dir_existed_before = Test-Path $InstallDir
        shortcut_existed_before = Test-Path $ShortcutPath
        install_dir = $InstallDir
        shortcut_path = $ShortcutPath
        last_completed_at = ""
        python_used = ""
        installed_exe = ""
    }
    Save-State $state
    Copy-Item (Join-Path $ProjectDir "scripts\uninstall.ps1") (Join-Path $StateRoot "uninstall.ps1") -Force
    Backup-Path (Join-Path $ProjectDir ".venv") "venv"
    Backup-Path (Join-Path $ProjectDir "build") "build"
    Backup-Path (Join-Path $ProjectDir "dist") "dist"
    Backup-Path $InstallDir "installed_app"
    Backup-Path $ShortcutPath "desktop_shortcut.lnk"
} else {
    $state = Get-Content $StatePath -Raw | ConvertFrom-Json
    Write-Host "Se detecto una instalacion gestionada anterior; se actualizara conservando el estado previo original." -ForegroundColor DarkGray
}

try {
    $pythonExe = Get-CompatiblePython
    if (-not $pythonExe) {
        $installInfo = Install-Python
        $state.python_installed_by_setup = $true
        $state.python_install_method = $installInfo.method
        $state.python_installer = $installInfo.installer
        Save-State $state
        Start-Sleep -Seconds 2
        $pythonExe = Get-CompatiblePython
        if (-not $pythonExe) { throw "Python se instalo, pero no se pudo localizar un Python compatible 3.10-3.14." }
    } else {
        Write-Host "Python compatible detectado: $pythonExe" -ForegroundColor DarkGray
    }

    Write-Step "Creando entorno virtual limpio"
    $venvDir = Join-Path $ProjectDir ".venv"
    if (Test-Path $venvDir) { Remove-Item $venvDir -Recurse -Force }
    & $pythonExe -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear .venv." }
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    Write-Step "Instalando dependencias runtime y de build"
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar pip." }
    & $venvPython -m pip install -r (Join-Path $ProjectDir "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }
    & $venvPython -m pip install -e $ProjectDir --no-deps
    if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar el proyecto en modo editable." }

    $configPath = Join-Path $ProjectDir "config.yaml"
    if (-not (Test-Path $configPath)) { Copy-Item (Join-Path $ProjectDir "config.example.yaml") $configPath }

    Install-BambuStudioIfNeeded $state

    Write-Step "Compilando BambuLabToolbox.exe"
    $buildCmd = Join-Path $ProjectDir "build_exe.cmd"
    & cmd.exe /d /c ('"' + $buildCmd + '"')
    if ($LASTEXITCODE -ne 0) { throw "La compilacion del EXE fallo." }

    $builtDir = Join-Path $ProjectDir "dist\BambuLabToolbox"
    $builtExe = Join-Path $builtDir "BambuLabToolbox.exe"
    if (-not (Test-Path $builtExe)) { throw "La build termino sin generar $builtExe" }

    Write-Step "Instalando la aplicacion"
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item (Join-Path $builtDir "*") $InstallDir -Recurse -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "scripts") | Out-Null
    Copy-Item (Join-Path $ProjectDir "uninstall.cmd") (Join-Path $InstallDir "uninstall.cmd") -Force
    Copy-Item (Join-Path $ProjectDir "scripts\uninstall.ps1") (Join-Path $InstallDir "scripts\uninstall.ps1") -Force
    Copy-Item (Join-Path $ProjectDir "scripts\uninstall.ps1") (Join-Path $StateRoot "uninstall.ps1") -Force

    Write-Step "Creando acceso directo en el Escritorio"
    New-DesktopShortcut

    $state.last_completed_at = (Get-Date).ToString("o")
    $state.python_used = $pythonExe
    $state.installed_exe = (Join-Path $InstallDir "BambuLabToolbox.exe")
    Save-State $state

    Write-Host ""
    Write-Host "INSTALACION COMPLETADA" -ForegroundColor Green
    Write-Host "Aplicacion: $InstallDir\BambuLabToolbox.exe"
    Write-Host "Acceso directo: $ShortcutPath"
    Write-Host "Desinstalador: $InstallDir\uninstall.cmd"
    Write-Host "Para volver al estado anterior de la maquina, ejecuta uninstall.cmd." -ForegroundColor Yellow
} catch {
    Write-Host ""
    Write-Host "LA INSTALACION HA FALLADO" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "El estado se conserva para que uninstall.cmd pueda revertir lo creado." -ForegroundColor Yellow
    exit 1
}
