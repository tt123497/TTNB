# ============================================
# 股市哨兵 · 自动启动脚本
# 启动 HTTP 服务器 + 公网隧道
# ============================================
$ErrorActionPreference = "SilentlyContinue"
$dir = "D:\projects\market-dashboard"

# 1. 启动 HTTP 服务器
Write-Host "📡 启动 HTTP 服务器..." -ForegroundColor Green
$http = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'http.server' }
if (-not $http) {
    Start-Process -WindowStyle Hidden -FilePath python -ArgumentList '-m','http.server','8080','-d',$dir
    Write-Host "   ✅ HTTP 服务器运行在 http://localhost:8080" -ForegroundColor Cyan
} else {
    Write-Host "   ✅ HTTP 服务器已在运行" -ForegroundColor Cyan
}

# 2. 启动 localtunnel
Write-Host "🌐 启动公网隧道..." -ForegroundColor Green
Start-Sleep 2
$tunnelJob = Start-Job -ScriptBlock { npx --yes localtunnel --port 8080 2>&1 } -Name "tunnel"

# 等待获取 URL
for ($i=0; $i -lt 30; $i++) {
    Start-Sleep 1
    $out = Receive-Job $tunnelJob
    if ($out -match "your url is: (https://[^\s]+)") {
        $url = $Matches[1]
        Write-Host "   ✅ 公网地址: $url" -ForegroundColor Yellow
        $url | Out-File "$dir\public-url.txt"
        break
    }
}

# 3. 显示访问信息
Write-Host ""
Write-Host "================================================" -ForegroundColor Magenta
Write-Host "  📡 股市哨兵已就绪！" -ForegroundColor White
Write-Host "  🏠 家里: http://localhost:8080" -ForegroundColor Cyan
if ($url) {
    Write-Host "  🌐 外面: $url" -ForegroundColor Yellow
}
Write-Host "  📱 手机扫码或浏览器打开上面的网址即可" -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "按 Ctrl+C 停止，或直接关闭窗口（后台继续运行）" -ForegroundColor DarkGray

# 保持运行并监控
while ($true) {
    Start-Sleep 60
    # 检查 HTTP 服务器是否还在
    $http = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'http.server' }
    if (-not $http) {
        Write-Host "⚠️ HTTP 服务器挂了，重启中..." -ForegroundColor Red
        Start-Process -WindowStyle Hidden -FilePath python -ArgumentList '-m','http.server','8080','-d',$dir
    }
    # 检查 tunnel
    if ($tunnelJob.State -ne 'Running') {
        Write-Host "⚠️ 隧道挂了，重启中..." -ForegroundColor Red
        $tunnelJob = Start-Job -ScriptBlock { npx --yes localtunnel --port 8080 2>&1 } -Name "tunnel"
        Start-Sleep 10
        $out = Receive-Job $tunnelJob
        if ($out -match "your url is: (https://[^\s]+)") {
            $newUrl = $Matches[1]
            Write-Host "   ✅ 新地址: $newUrl" -ForegroundColor Yellow
            $newUrl | Out-File "$dir\public-url.txt"
        }
    }
}
