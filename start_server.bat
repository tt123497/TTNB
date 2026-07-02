@echo off
REM TTNB Local Web Server - 开机自启
REM 在 D:\projects\market-dashboard 启动 HTTP 服务器，端口 8080

cd /d D:\projects\market-dashboard

REM 用 Python 内置 HTTP 服务器
python -m http.server 8080 --bind 0.0.0.0
