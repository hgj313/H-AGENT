@echo off
REM Elevate and run the SYSTEM scheduled-task restart for port 8765.
REM Kept ASCII-only (cmd reads .bat in the OEM codepage).
REM The inner python calls powershell.exe itself, inheriting the elevated token.
set "PY=C:\insurance-automation\.venv\Scripts\python.exe"
set "SCRIPT=C:\insurance-automation\tools\elevate_restart.py"
"%PY%" "%SCRIPT%"
