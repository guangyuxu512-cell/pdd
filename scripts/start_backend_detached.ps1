param(
    [int]$Port = 8800
)

$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root ".runlogs"
$LogFile = Join-Path $LogDir "backend.detached.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
"Starting backend at $(Get-Date -Format o)" | Set-Content -LiteralPath $LogFile -Encoding UTF8
"Root=$Root" | Add-Content -LiteralPath $LogFile -Encoding UTF8
"Backend=$Backend" | Add-Content -LiteralPath $LogFile -Encoding UTF8
"Python=$Python" | Add-Content -LiteralPath $LogFile -Encoding UTF8

Set-Location $Backend
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port *> $LogFile
