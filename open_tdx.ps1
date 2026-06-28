# tdxstock:// protocol handler 鈥?涓€閿墦寮€涓偂
param([string]$url='')

# 1. 浠?URL 鎻愬彇6浣嶄唬鐮?
$code = ''
if ($url -match 'tdxstock://(\d{6})') { $code = $Matches[1] }
if ($url -match 'tdxstock://([^/]+)') { $code = $Matches[1] }
if (-not $code -or $code.Length -ne 6) { exit }

# 2. 鑷姩妫€娴嬮€氳揪淇″畨瑁呰矾寰?(涓嶅啀纭紪鐮?
$tdxPath = $null
$candidates = @(
  'D:\tongxinda\TdxW.exe',
  'C:\new_tdx\TdxW.exe',
  'D:\new_tdx\TdxW.exe',
  'D:\閫氳揪淇TdxW.exe',
  'C:\閫氳揪淇TdxW.exe',
  'D:\鏂伴€氳揪淇TdxW.exe',
  'C:\Program Files\閫氳揪淇TdxW.exe',
  'D:\Program Files\閫氳揪淇TdxW.exe',
  'E:\tongxinda\TdxW.exe',
  'E:\new_tdx\TdxW.exe'
)
foreach ($p in $candidates) {
  if (Test-Path $p) { $tdxPath = $p; break }
}
# 浠嶆湭鎵惧埌: 鎼滅储娉ㄥ唽琛ㄤ腑鐨?TdxW.exe
if (-not $tdxPath) {
  try {
    $reg = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\TdxW.exe' -ErrorAction SilentlyContinue
    if ($reg -and $reg.'(default)') { $tdxPath = $reg.'(default)' }
  } catch {}
}
# 鏈€鍚庡厹搴? 鐢?Get-Process 鎵惧凡杩愯鐨勯€氳揪淇?
if (-not $tdxPath) {
  $proc = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
  if ($proc) { $tdxPath = $proc.Path }
}

# 3. 鍚姩閫氳揪淇?(濡傛灉娌¤繍琛?
$tdxProcess = Get-Process -Name 'TdxW' -ErrorAction SilentlyContinue
if (-not $tdxProcess -and $tdxPath) {
  Start-Process -FilePath $tdxPath -WindowStyle Maximized
  Start-Sleep -Seconds 5
}

# 4. 鎶婇€氳揪淇＄獥鍙ｆ媺鍒板墠鍙板苟鏈€澶у寲
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

# 5. 妯℃嫙閿洏杈撳叆浠ｇ爜 + 鍥炶溅 (鏁插叆閫氳揪淇￠敭鐩樼簿鐏?
Add-Type -AssemblyName System.Windows.Forms
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait($code)
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
