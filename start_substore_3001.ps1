$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$subStoreDir = Join-Path $root "tools\sub-store"
$bundle = Join-Path $subStoreDir "sub-store.bundle.js"
$dataDir = Join-Path $root "data\sub-store"
$logFile = Join-Path $subStoreDir "sub-store-3001.log"

if (-not (Test-Path $bundle)) {
    throw "Sub-Store bundle not found: $bundle"
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$env:SUB_STORE_BACKEND_API_HOST = "0.0.0.0"
$env:SUB_STORE_BACKEND_API_PORT = "3001"
$env:SUB_STORE_FRONTEND_BACKEND_PATH = "http://127.0.0.1:3001"
$env:SUB_STORE_DATA_BASE_PATH = $dataDir

Set-Location $subStoreDir
node .\sub-store.bundle.js *> $logFile
