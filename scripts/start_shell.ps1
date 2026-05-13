param(
    [int]$Port = 8800
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$Electron = Join-Path $Root "electron"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root ".runlogs"
$BackendLog = Join-Path $LogDir "backend.detached.log"
$BackendErrorLog = Join-Path $LogDir "backend.detached.err.log"
$RunStamp = Get-Date -Format "yyyyMMddHHmmss"
$ElectronLog = Join-Path $LogDir "electron.$RunStamp.log"
$ElectronErrorLog = Join-Path $LogDir "electron.$RunStamp.err.log"
$LauncherLog = Join-Path $LogDir "shell-launcher.log"
$Url = "http://127.0.0.1:$Port/"
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$BackendPidFile = Join-Path $LogDir "backend.pid"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
"[$(Get-Date -Format o)] Starting shell" | Set-Content -LiteralPath $LauncherLog -Encoding UTF8
"Root=$Root" | Add-Content -LiteralPath $LauncherLog -Encoding UTF8

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python venv not found: $Python"
}
if (-not (Test-Path -LiteralPath (Join-Path $Backend "app\main.py"))) {
    throw "Backend entry not found: $Backend\app\main.py"
}
if (-not (Test-Path -LiteralPath (Join-Path $Electron "package.json"))) {
    throw "Electron package not found: $Electron\package.json"
}

function Test-BackendReady {
    try {
        Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-BackendReady)) {
    "[$(Get-Date -Format o)] Starting backend" | Set-Content -LiteralPath $BackendLog -Encoding UTF8
    "[$(Get-Date -Format o)] Backend stderr" | Set-Content -LiteralPath $BackendErrorLog -Encoding UTF8
    Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $Backend `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError $BackendErrorLog `
        -WindowStyle Hidden `
        -PassThru | ForEach-Object { $_.Id | Set-Content -LiteralPath $BackendPidFile -Encoding ASCII }
}

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Test-BackendReady) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    throw "Backend did not become ready: $HealthUrl"
}

$env:SHELL_FRONTEND_URL = $Url
$env:SHELL_BACKEND_PID_FILE = $BackendPidFile
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if (-not $Npm) {
    $Npm = Get-Command npm -ErrorAction Stop
}

$ElectronBin = Join-Path $Electron "node_modules\electron\dist\electron.exe"
if (-not (Test-Path -LiteralPath $ElectronBin)) {
    "[$(Get-Date -Format o)] Installing Electron dependencies" | Add-Content -LiteralPath $LauncherLog -Encoding UTF8
    Push-Location $Electron
    try {
        & $Npm.Source install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $ElectronBin)) {
    throw "Electron binary not found after install: $ElectronBin"
}

"[$(Get-Date -Format o)] Starting Electron" | Set-Content -LiteralPath $ElectronLog -Encoding UTF8
"[$(Get-Date -Format o)] Electron stderr" | Set-Content -LiteralPath $ElectronErrorLog -Encoding UTF8
$ElectronProcess = Start-Process -FilePath $ElectronBin `
    -ArgumentList @(".") `
    -WorkingDirectory $Electron `
    -RedirectStandardOutput $ElectronLog `
    -RedirectStandardError $ElectronErrorLog `
    -WindowStyle Normal `
    -PassThru

Start-Sleep -Seconds 2
if ($ElectronProcess.HasExited) {
    $errorText = ""
    if (Test-Path -LiteralPath $ElectronErrorLog) {
        $errorText = Get-Content -Raw -LiteralPath $ElectronErrorLog
    }
    throw "Electron exited immediately. $errorText"
}

"[$(Get-Date -Format o)] Shell launched: $Url" | Add-Content -LiteralPath $LauncherLog -Encoding UTF8
