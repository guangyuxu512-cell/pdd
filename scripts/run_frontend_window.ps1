param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"

Set-Location $Frontend
Write-Host "Frontend: $Frontend"
Write-Host "URL:      http://127.0.0.1:$Port"
Write-Host ""

npm install
npm run dev -- --host 127.0.0.1 --port $Port

Write-Host ""
Write-Host "Frontend process exited. Press Enter to close this window."
Read-Host | Out-Null
