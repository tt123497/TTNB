# install_tdx_protocol.ps1 — 自动注册 tdxstock:// 协议
# 运行一次即可, 无需手动双击 .reg 文件
# 用法: powershell -ExecutionPolicy Bypass -File install_tdx_protocol.ps1

$ErrorActionPreference = 'Stop'

# 自动检测当前脚本所在目录 (不再硬编码项目路径)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ps1Path = Join-Path $scriptDir 'open_tdx.ps1'

if (-not (Test-Path $ps1Path)) {
  Write-Host "错误: 找不到 open_tdx.ps1, 应在: $ps1Path" -ForegroundColor Red
  exit 1
}

# 写入注册表 (用当前脚本目录, 不再硬编码 D:\projects\...)
$command = "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1Path`" `"%1`""

Write-Host "注册 tdxstock:// 协议..." -ForegroundColor Cyan
Write-Host "  脚本路径: $ps1Path"

$key = 'HKCU:\SOFTWARE\Classes\tdxstock'
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name '(default)' -Value 'URL:通达信行情协议'
Set-ItemProperty -Path $key -Name 'URL Protocol' -Value ''

New-Item -Path "$key\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$key\DefaultIcon" -Name '(default)' -Value 'TdxW.exe,0'

New-Item -Path "$key\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "$key\shell\open\command" -Name '(default)' -Value $command

# 验证
$verify = (Get-ItemProperty -Path "$key\shell\open\command" -Name '(default)').'(default)'
if ($verify -eq $command) {
  Write-Host ""
  Write-Host "✅ tdxstock:// 协议注册成功!" -ForegroundColor Green
  Write-Host "   现在在浏览器点击股票代码会自动打开通达信" -ForegroundColor Green
  Write-Host ""
  Write-Host "提示: 重新安装通达信或移动项目目录后, 重新运行此脚本即可" -ForegroundColor Yellow
} else {
  Write-Host "✗ 注册失败, 请检查权限" -ForegroundColor Red
}
