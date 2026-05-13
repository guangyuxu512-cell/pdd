$ErrorActionPreference = "Stop"
$ElectronPath = Resolve-Path (Join-Path $PSScriptRoot "..\electron")
Set-Location $ElectronPath

npm install
npm run dev
