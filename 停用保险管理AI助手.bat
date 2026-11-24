@echo off
rem ============================================================
rem  Stop the local Insurance Agent (8765 service + MQ bridge)
rem  and start the direct MQ -> Feishu Bitable sync consumer.
rem
rem  A new admin (UAC) window will open. Click "Yes" on the
rem  UAC prompt, then wait for that window to finish.
rem ============================================================
cd /d C:\insurance-automation
echo Requesting administrator rights...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\insurance-automation\disable_assistant.ps1'"
echo.
echo An admin window has been opened. Click "Yes" on the UAC prompt.
echo Wait for that window to report "Done", then close it.
echo.
timeout /t 10 >nul
