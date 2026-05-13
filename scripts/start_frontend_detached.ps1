param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"
$LogDir = Join-Path $Root ".runlogs"
$LogFile = Join-Path $LogDir "frontend.detached.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
"Starting frontend at $(Get-Date -Format o)" | Set-Content -LiteralPath $LogFile -Encoding UTF8
"Root=$Root" | Add-Content -LiteralPath $LogFile -Encoding UTF8
"Frontend=$Frontend" | Add-Content -LiteralPath $LogFile -Encoding UTF8

Set-Location $Frontend
npm install *>> $LogFile
npm run dev -- --host 127.0.0.1 --port $Port *>> $LogFile
