@echo off
chcp 65001 >nul
title 保险单识别系统
echo ========================================
echo   保险单识别系统 - 本地部署
echo ========================================
echo.
echo 启动中... 浏览器访问 http://localhost:8765
echo 按 Ctrl+C 停止服务
echo.

cd /d C:\insurance-automation
"C:\insurance-automation\H-AGENT\.venv\Scripts\python.exe" web_app\server.py

pause
