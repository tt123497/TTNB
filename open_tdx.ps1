# tdxstock:// protocol handler — 一键打开个股
param([string]$url='')
$code = ''
if ($url -match 'tdxstock://(\d{6})') { $code = $Matches[1] }
if ($url -match 'tdxstock://([^/]+)') { $code = $Matches[1] }
if (-not $code -or $code.Length -ne 6) { exit }

# 1. Launch TDX if not running
$tdxPath = 'D:\tongxinda\TdxW.exe'
$tdxProcess = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
if (-not $tdxProcess) {
    Start-Process -FilePath $tdxPath -WindowStyle Normal
    Start-Sleep -Seconds 5
}

# 2. Bring TDX to foreground
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
        [Win32]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
        [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 300
        break
    }
} catch {}

# 3. Type stock code into TDX keyboard elf + Enter
Add-Type -AssemblyName System.Windows.Forms
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait($code)
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
