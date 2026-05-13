param(
    [int]$Port = 8800
)

$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Set-Location $Backend
Write-Host "Backend: $Backend"
Write-Host "Python:  $Python"
Write-Host "URL:     http://127.0.0.1:$Port"
Write-Host ""

& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port

Write-Host ""
Write-Host "Backend process exited. Press Enter to close this window."
Read-Host | Out-Null
