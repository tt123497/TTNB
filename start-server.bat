@echo off
echo 📡 Starting Market Sentinel Server...
cd /d D:\projects\market-dashboard
start "" python -m http.server 8080
echo ✅ Server running at http://localhost:8080
echo 📱 Open this on your phone or any device on the same network
pause
