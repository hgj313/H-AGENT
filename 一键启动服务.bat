@echo off
rem ============================================================
rem  Insurance Service - Start Launcher
rem
rem  This .bat is intentionally minimal: it only launches a
rem  persistent PowerShell console running 一键启动服务.ps1.
rem ============================================================

cd /d C:\insurance-automation

start "Insurance Service Console" powershell.exe -NoExit -ExecutionPolicy Bypass -File "C:\insurance-automation\一键启动服务.ps1"
