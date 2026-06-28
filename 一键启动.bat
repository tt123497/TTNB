@echo off
title 股市哨兵 - 全自动运行中...
echo.
echo ====================================
echo   📡 股市哨兵 · 全自动启动
echo ====================================
echo.
echo [1/3] HTTP服务器 启动...
start "" /min python -m http.server 8080 -d D:\projects\market-dashboard
echo        http://localhost:8080
echo.
echo [2/3] 数据引擎 启动...
start "" /min python D:\projects\market-dashboard\run_update.py
echo        统一数据更新 (a-stock-data 28端点)
echo.
echo [3/3] 公网隧道 启动...
start "" /min powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command "npx --yes localtunnel --port 8080 2>&1 | ForEach-Object { if ($_ -match 'your url is: (https://[^\s]+)') { $Matches[1] | Out-File 'D:\projects\market-dashboard\public-url.txt'; Write-Host $Matches[1] } }"
timeout /t 8 /nobreak >nul
if exist D:\projects\market-dashboard\public-url.txt (
    set /p URL=<D:\projects\market-dashboard\public-url.txt
    echo        %URL%
)
echo.
echo ====================================
echo   ✅ 哨兵系统已就绪！
echo   🏠 家里: http://localhost:8080
echo   🔄 数据: 每30分钟自动刷新
echo   ❌ 关闭此窗口不影响后台运行
echo ====================================
echo.
pause
