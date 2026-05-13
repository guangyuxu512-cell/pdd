$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Stopping backend port 8800..."
$connections = Get-NetTCPConnection -LocalPort 8800 -ErrorAction SilentlyContinue
foreach ($connection in $connections) {
    if ($connection.OwningProcess) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Stopping Electron processes for this project..."
$electronPath = Join-Path $Root "electron\node_modules\electron\dist\electron.exe"
Get-Process electron -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -eq $electronPath -or $_.Path -like (Join-Path $Root "*")
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Done."
