# tdxstock:// protocol handler — copy code to clipboard + launch TDX
param([string]$url='')
$code = ''
if ($url -match 'tdxstock://(\d{6})') { $code = $Matches[1] }
if ($url -match 'tdxstock://([^/]+)') { $code = $Matches[1] }
if (-not $code -or $code.Length -ne 6) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("无效的股票代码: $code", 'TDX Helper', 'OK', 'Error')
    exit
}

# 1. Copy to clipboard
Set-Clipboard -Value $code

# 2. Try to bring TDX to front / launch if not running
$tdxPath = 'D:\tongxinda\TdxW.exe'
$tdxProcess = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
if (-not $tdxProcess) {
    Start-Process -FilePath $tdxPath -WindowStyle Normal
    Start-Sleep -Seconds 3
}

# 3. Bring TDX window to front
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
        [Win32]::ShowWindow($p.MainWindowHandle, 9) | Out-Null  # SW_RESTORE
        [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
    }
} catch {}

# 4. Show notification
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = '📈 通达信'
$notify.BalloonTipText = "已复制 $code`n在通达信窗口按 Ctrl+V 查看"
$notify.Visible = $true
$notify.ShowBalloonTip(2000)
Start-Sleep -Seconds 3
$notify.Dispose()
