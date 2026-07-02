@echo off
REM ============================================
REM TTNB 停止脚本
REM 位置: D:\projects\market-dashboard\stop_all.bat
REM ============================================

REM 停止 HTTP 服务器
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

REM 停止 Cloudflare 隧道
taskkill /im cloudflared.exe /F >nul 2>&1

echo %date% %time% TTNB services stopped >> D:\projects\market-dashboard\service_log.txt
