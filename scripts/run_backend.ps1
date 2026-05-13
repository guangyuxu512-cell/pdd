param(
    [int]$Port = 8800
)

$ErrorActionPreference = "Stop"
$RootPath = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendPath = Join-Path $RootPath "backend"
$VenvPython = Join-Path $RootPath ".venv\Scripts\python.exe"
Set-Location $RootPath

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& $VenvPython -m pip install -r (Join-Path $BackendPath "requirements.txt")
Set-Location $BackendPath
& $VenvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
