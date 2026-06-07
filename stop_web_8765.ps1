$port = 8765
$connections = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port }
$pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique

if (-not $pids) {
    Write-Host "No Huage web listener found on port $port."
    exit 0
}

foreach ($processId in $pids) {
    try {
        $process = Get-Process -Id $processId -ErrorAction Stop
        Stop-Process -Id $processId -Force
        Write-Host "Stopped process $processId ($($process.ProcessName)) on port $port."
    } catch {
        Write-Host "Failed to stop process $processId: $($_.Exception.Message)"
    }
}
