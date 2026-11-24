@echo off
rem ============================================================
rem  Stop the local Insurance Management AI Assistant
rem  and start the Feishu Bitable direct MQ consumer (Session 0)
rem  2026-11-24
rem
rem  The script self-elevates silently (ConsentPromptBehaviorAdmin=0),
rem  so there is normally no UAC prompt to click.
rem ============================================================
cd /d C:\insurance-automation
set PY=C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe

echo [1/2] Requesting elevation (silent)...
"%PY%" "C:\insurance-automation\_elevated_run.py"
echo [2/2] Waiting for the elevated worker to finish...

timeout /t 45 /nobreak >nul

echo.
echo ---- Result ----
if exist "C:\insurance-automation\_disable_result.json" (
    type "C:\insurance-automation\_disable_result.json"
) else (
    echo Result file not found. Check C:\insurance-automation\_elevated_run.log
)
echo.
echo Done. This window can be closed.
timeout /t 8 /nobreak >nul
