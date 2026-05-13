param(
    [int]$Port = 8800
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Electron = Join-Path $Root "electron"
$Python = Join-Path $Root "python\python.exe"
$SitePackages = Join-Path $Root ".venv\Lib\site-packages"
$LogDir = Join-Path $Root ".runlogs"
$BackendPidFile = Join-Path $LogDir "backend.pid"
$LauncherErrorLog = Join-Path $LogDir "launcher.err.log"
$Url = "http://127.0.0.1:$Port/"
$HealthUrl = "http://127.0.0.1:$Port/api/health"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null

function Fail-Launch {
    param([string]$Message)
    $Message | Set-Content -LiteralPath $LauncherErrorLog -Encoding UTF8
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Message, "Taobao Toolbox launch failed", "OK", "Error") | Out-Null
    exit 1
}

if (-not (Test-Path -LiteralPath $Python)) {
    Fail-Launch "Bundled Python not found: $Python"
}
if (-not (Test-Path -LiteralPath $SitePackages)) {
    Fail-Launch "Bundled Python dependencies not found: $SitePackages"
}

function Test-BackendReady {
    try {
        Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Quote-Arg {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Start-AppProcess {
    param(
        [string]$FileName,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [bool]$Hidden = $true
    )
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $FileName
    $info.Arguments = ($Arguments | ForEach-Object { Quote-Arg $_ }) -join " "
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $Hidden
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    [void]$process.Start()
    return $process
}

if (-not (Test-BackendReady)) {
    $bootstrap = "import sys; sys.path.insert(0, r'$SitePackages'); import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=$Port)"
    $backendProcess = Start-AppProcess `
        -FileName $Python `
        -Arguments @("-c", $bootstrap) `
        -WorkingDirectory $Backend `
        -Hidden $true
    $backendProcess.Id | Set-Content -LiteralPath $BackendPidFile -Encoding ASCII
}

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    if (Test-BackendReady) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    Fail-Launch "Backend did not start on port $Port. Check whether the port is already in use."
}

$ElectronBin = Join-Path $Electron "node_modules\electron\dist\electron.exe"
if (-not (Test-Path -LiteralPath $ElectronBin)) {
    Fail-Launch "Electron runtime not found: $ElectronBin"
}

Start-AppProcess `
    -FileName $ElectronBin `
    -Arguments @(".", "--port=$Port", "--backend-pid-file=$BackendPidFile") `
    -WorkingDirectory $Electron `
    -Hidden $false | Out-Null
