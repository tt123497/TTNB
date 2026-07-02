@echo off
REM ============================================
REM TTNB 本地服务器 + Cloudflare 隧道 启动脚本
REM 位置: D:\projects\market-dashboard\start_all.bat
REM ============================================

cd /d D:\projects\market-dashboard

REM 1. 启动 HTTP 服务器 (端口8080)
start "TTNB-WebServer" /min python -m http.server 8080 --bind 0.0.0.0

REM 2. 等待HTTP服务器启动
timeout /t 3 /nobreak >nul

REM 3. 启动 Cloudflare 隧道
start "TTNB-Tunnel" /min "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8080

REM 4. 记录启动时间
echo %date% %time% TTNB services started >> D:\projects\market-dashboard\service_log.txt
