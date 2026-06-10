@echo off
echo ====================================
echo   设置 Windows 开机自启动
echo ====================================
echo.

:: 创建任务计划
schtasks /create /tn "MarketSentinel" /tr "D:\projects\market-dashboard\一键启动.bat" /sc onlogon /delay 0001:00 /rl highest /f

if %errorlevel%==0 (
    echo ✅ 已添加开机自启动！
    echo    任务名称: MarketSentinel
    echo    重启电脑后自动运行
    echo.
    echo    立即运行？
    start "" "D:\projects\market-dashboard\一键启动.bat"
) else (
    echo ❌ 添加失败，尝试备用方案...
    echo.
    echo    请手动把 一键启动.bat 拖到
    echo    shell:startup 文件夹中
    echo.
    start shell:startup
)

pause
