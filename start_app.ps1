$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendScript = Join-Path $Root "scripts\backend_server.cmd"
$LogDir = Join-Path $Root ".runlogs"
$Log = Join-Path $LogDir "launcher-ps.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

"[$(Get-Date -Format o)] Starting UniversalShell backend-only mode" | Set-Content -LiteralPath $Log -Encoding UTF8
"Root=$Root" | Add-Content -LiteralPath $Log -Encoding UTF8

if (-not (Test-Path -LiteralPath $BackendScript)) {
    throw "Backend script was not found: $BackendScript"
}

Start-Process -FilePath cmd.exe -ArgumentList @("/k", "`"$BackendScript`" 8800") -WindowStyle Normal
Start-Sleep -Seconds 5
Start-Process "http://127.0.0.1:8800/"

"Started backend window." | Add-Content -LiteralPath $Log -Encoding UTF8
