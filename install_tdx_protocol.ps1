# install_tdx_protocol.ps1
# powershell -ExecutionPolicy Bypass -File install_tdx_protocol.ps1

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ps1Path = Join-Path $scriptDir "open_tdx.ps1"

if (-not (Test-Path $ps1Path)) {
  Write-Host "ERROR: open_tdx.ps1 not found at: $ps1Path" -ForegroundColor Red
  exit 1
}

$command = "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1Path`" `"%1`""

Write-Host "Registering tdxstock:// protocol..." -ForegroundColor Cyan
Write-Host "  Script path: $ps1Path"

$key = "HKCU:\SOFTWARE\Classes\tdxstock"
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name "(default)" -Value "URL:TDX Stock Protocol"
Set-ItemProperty -Path $key -Name "URL Protocol" -Value ""

New-Item -Path "$key\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$key\DefaultIcon" -Name "(default)" -Value "TdxW.exe,0"

New-Item -Path "$key\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "$key\shell\open\command" -Name "(default)" -Value $command

$cmdKey = Get-Item -Path "$key\shell\open\command"
$verify = $cmdKey.GetValue("")

if ($verify -eq $command) {
  Write-Host ""
  Write-Host "[OK] tdxstock:// protocol registered!" -ForegroundColor Green
  Write-Host "     Click stock code in browser to open TDX" -ForegroundColor Green
  Write-Host ""
  Write-Host "Tip: Re-run this script after moving project folder" -ForegroundColor Yellow
} else {
  Write-Host "[FAIL] Registration failed, check permissions" -ForegroundColor Red
}