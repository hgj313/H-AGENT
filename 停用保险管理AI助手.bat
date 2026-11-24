@echo off
rem Disable local Insurance Agent (8765 service + MQ bridge + watchdog)
rem Requires admin: approve the UAC prompt.
cd /d C:\insurance-automation
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\insurance-automation\disable_assistant.ps1'"
echo.
echo Admin elevation requested. Please click "Yes" on the UAC prompt.
timeout /t 5 >nul
