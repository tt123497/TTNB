@echo off
:: 添加到 Windows 开机自启动
:: 在开始菜单的启动文件夹创建快捷方式

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SCRIPT=D:\projects\market-dashboard\start-silent.vbs

:: 创建 VBS 脚本（静默启动，无窗口）
echo Set WshShell = CreateObject("WScript.Shell") > "%SCRIPT%"
echo WshShell.Run "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File D:\projects\market-dashboard\start.ps1", 0, False >> "%SCRIPT%"

:: 创建快捷方式到启动文件夹
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_DIR%\MarketSentinel.lnk'); $s.TargetPath = '%SCRIPT%'; $s.WorkingDirectory = 'D:\projects\market-dashboard'; $s.Save()"

echo ✅ 已设置开机自启动
echo 📡 下次开机时，哨兵系统会自动在后台运行
pause
