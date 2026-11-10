# ============================================================
# ERP -> Feishu Bitable Direct Sync (background, one-shot start)
#
# Starts erp_feishu_direct.consumer detached (via pythonw.exe) so it
# keeps running after this script exits.
#
# Run in admin PowerShell:
#   powershell -ExecutionPolicy Bypass -File "C:\insurance-automation\一键启动直连同步.ps1"
#
# This consumer is INDEPENDENT of the insurance AI service (port 8765):
#   - It does NOT require the 8765 service to be running
#   - It does NOT write to the local SQLite database
#   - It uses its OWN consumer group (feishu-direct-sync), so it does
#     NOT steal messages from the existing MQ bridge
#
# Logs:
#   - erp_feishu_direct.log   (rotating application log)
#   - direct_sync.log         (this script's lifecycle)
# ============================================================

$ErrorActionPreference = "Continue"
$workDir  = "C:\insurance-automation"
$logFile  = Join-Path $workDir "direct_sync.log"
$venvPy   = "C:\insurance-automation\H-AGENT\.venv\Scripts\pythonw.exe"
$script   = "C:\insurance-automation\erp_feishu_direct\consumer.py"

Set-Location $workDir

function Log($msg, $color = "White") {
    Write-Host $msg -ForegroundColor $color
    $msg | Out-File -FilePath $logFile -Append -Encoding utf8
}

"=== Direct Sync Start at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $logFile -Encoding utf8

Log "============================================" Cyan
Log "  ERP -> Feishu Direct Sync" Cyan
Log "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" Cyan
Log "============================================" Cyan
Log ""

# 1. Check python venv (mq_http_sdk lives in H-AGENT venv)
Log "[1/3] Verifying Python venv..."
if (Test-Path $venvPy) {
    Log "  - OK: $venvPy" Gray
} else {
    Log "  - FAIL: $venvPy not found (mq_http_sdk is required)" Red
    Log "  - Install it: C:\insurance-automation\H-AGENT\.venv\Scripts\pip.exe install mq_http_sdk" Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Log ""

# 2. Check config file
Log "[2/3] Checking config..."
$cfgFile = Join-Path $workDir "erp_feishu_direct_config.json"
if (Test-Path $cfgFile) {
    Log "  - OK: $cfgFile" Gray
} else {
    Log "  - WARN: $cfgFile not found, using built-in defaults" Yellow
    Log "  - Copy erp_feishu_direct_config.json.example to get started" Yellow
}
Log ""

# 3. Check credentials in .env
Log "[3/3] Checking credentials..."
$envFile = Join-Path $workDir ".env"
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw
    foreach ($key in @("ROCKETMQ_ACCESS_KEY", "ROCKETMQ_SECRET_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN")) {
        if ($envContent -match "$key\s*=\s*\S") {
            Log "  - OK: $key" Gray
        } else {
            Log "  - MISSING: $key" Yellow
        }
    }
} else {
    Log "  - WARN: .env not found" Yellow
}
Log ""

# Launch detached
$stdout = Join-Path $workDir "direct_sync_stdout.log"
$stderr = Join-Path $workDir "direct_sync_stderr.log"

try {
    $p = Start-Process -FilePath $venvPy `
                      -ArgumentList $script `
                      -WorkingDirectory $workDir `
                      -RedirectStandardOutput $stdout `
                      -RedirectStandardError $stderr `
                      -WindowStyle Hidden `
                      -PassThru
    Log "  - Started PID: $($p.Id)" Green
    Log ""
    Log "  Check status: Get-Content 'C:\insurance-automation\erp_feishu_direct.log' -Tail 20" Gray
    Log "  Stop: taskkill /PID $($p.Id) /F" Gray
    Log ""
    Log "=== Direct Sync started successfully ===" Green
} catch {
    Log "  - FAIL: $($_.Exception.Message)" Red
    Read-Host "Press Enter to exit"
    exit 1
}
