@echo off
set PYTHONUTF8=1
cd /d D:\projects\market-dashboard
python news_fetch_once.py > nul 2>&1
git add data.json > nul 2>&1
git commit -m "news %time:~0,5%" > nul 2>&1
git pull --rebase origin main > nul 2>&1
git push origin main > nul 2>&1
