$ErrorActionPreference = "Stop"
$FrontendPath = Resolve-Path (Join-Path $PSScriptRoot "..\frontend")
Set-Location $FrontendPath

npm install
npm run dev
