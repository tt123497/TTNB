# tdxstock:// protocol handler — 一键打开个股
param([string]$url='')

# 1. 从 URL 提取6位代码
$code = ''
if ($url -match 'tdxstock://(\d{6})') { $code = $Matches[1] }
if ($url -match 'tdxstock://([^/]+)') { $code = $Matches[1] }
if (-not $code -or $code.Length -ne 6) { exit }

# 2. 自动检测通达信安装路径 (不再硬编码)
$tdxPath = $null
$candidates = @(
  'D:\tongxinda\TdxW.exe',
  'C:\new_tdx\TdxW.exe',
  'D:\new_tdx\TdxW.exe',
  'D:\通达信\TdxW.exe',
  'C:\通达信\TdxW.exe',
  'D:\新通达信\TdxW.exe',
  'C:\Program Files\通达信\TdxW.exe',
  'D:\Program Files\通达信\TdxW.exe',
  'E:\tongxinda\TdxW.exe',
  'E:\new_tdx\TdxW.exe'
)
foreach ($p in $candidates) {
  if (Test-Path $p) { $tdxPath = $p; break }
}
# 仍未找到: 搜索注册表中的 TdxW.exe
if (-not $tdxPath) {
  try {
    $reg = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\TdxW.exe' -ErrorAction SilentlyContinue
    if ($reg -and $reg.'(default)') { $tdxPath = $reg.'(default)' }
  } catch {}
}
# 最后兜底: 用 Get-Process 找已运行的通达信
if (-not $tdxPath) {
  $proc = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
  if ($proc) { $tdxPath = $proc.Path }
}

# 3. 启动通达信 (如果没运行)
$tdxProcess = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
if (-not $tdxProcess -and $tdxPath) {
  Start-Process -FilePath $tdxPath -WindowStyle Maximized
  Start-Sleep -Seconds 5
}

# 4. 把通达信窗口拉到前台并最大化
try {
  Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32 {
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }
"@
    $procs = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        [Win32]::ShowWindow($p.MainWindowHandle, 3) | Out-Null  # SW_MAXIMIZE
        [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 300
        break
    }
} catch {}

# 5. 模拟键盘输入代码 + 回车 (敲入通达信键盘精灵)
Add-Type -AssemblyName System.Windows.Forms
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait($code)
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
