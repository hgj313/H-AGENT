@echo off
rem ============================================
rem  保险单识别系统 - 一键启动（守护模式）
rem  双击本文件启动服务，崩溃自动重启
rem ============================================
cd /d C:\insurance-automation

rem 检查服务是否已在运行
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 服务已在运行中（8765 端口已监听）
    timeout /t 3 >nul
    exit /b 0
)

rem 启动守护进程（无窗口，崩溃自动重启）
start "" "C:\insurance-automation\H-AGENT\.venv\Scripts\pythonw.exe" "C:\insurance-automation\service_watchdog.py"

echo [成功] 服务正在后台启动，请稍候...
echo 访问地址: http://localhost:8765
timeout /t 5 >nul
