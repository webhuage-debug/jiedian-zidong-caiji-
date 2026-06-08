$env:HUAGE_ROOT = $PSScriptRoot
$env:HUAGE_HOST = "0.0.0.0"
$env:HUAGE_PORT = "8765"
$env:HUAGE_ADMIN_BASE_PATH = "/adminhuage"

Set-Location $PSScriptRoot
$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

Write-Host "Starting Huage web dashboard from $PSScriptRoot"
Write-Host "URL: http://127.0.0.1:8765/adminhuage"
Write-Host "LAN: http://10.10.10.58:8765/adminhuage"
Write-Host ""

if (Test-Path -LiteralPath $python) {
    & $python web_app.py
} else {
    & python web_app.py
}

Write-Host ""
Write-Host "Web server stopped. Press Enter to close this window."
Read-Host | Out-Null
