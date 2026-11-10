# ============================================================
# Stop the ERP -> Feishu direct sync consumer.
#
#   powershell -ExecutionPolicy Bypass -File "C:\insurance-automation\一键停止直连同步.ps1"
#
# Finds the pythonw.exe process running erp_feishu_direct\consumer.py
# and terminates it.
# ============================================================

$ErrorActionPreference = "Continue"
$workDir  = "C:\insurance-automation"
$logFile  = Join-Path $workDir "direct_sync.log"

function Log($msg, $color = "White") {
    Write-Host $msg -ForegroundColor $color
    $msg | Out-File -FilePath $logFile -Append -Encoding utf8
}

Log "=== Direct Sync Stop at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $logFile -Encoding utf8

# Find the process by its command line
$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like "*erp_feishu_direct*consumer*" }

if (-not $procs) {
    Log "  - No direct sync process found (already stopped)" Yellow
    exit 0
}

foreach ($p in $procs) {
    Log "  - Stopping PID $($p.ProcessId)..." Gray
    try {
        Stop-Process -Id $p.ProcessId -Force -Confirm:$false
        Log "  - Stopped PID $($p.ProcessId)" Green
    } catch {
        Log "  - FAIL to stop PID $($p.ProcessId): $($_.Exception.Message)" Red
    }
}

Log ""
Log "=== Direct Sync stopped ===" Green
