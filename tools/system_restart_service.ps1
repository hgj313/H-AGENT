# Restart 8765 service via a temporary SYSTEM scheduled task.
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads .ps1 as GBK/ANSI here).
$ErrorActionPreference = 'Continue'
$py = 'C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe'
$script = 'C:\insurance-automation\tools\system_restart_service.py'
$taskName = 'TempKill8765'

try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`""
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(3)

Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Trigger $trigger -Force | Out-Null
Write-Output "task registered: $taskName"

Start-ScheduledTask -TaskName $taskName
Write-Output "task triggered"
Start-Sleep -Seconds 10

$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
Write-Output "last task result: $($info.LastTaskResult)"

try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Write-Output "temp task removed"
