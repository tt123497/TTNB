@echo off
set PYTHONUTF8=1
set LANG=zh_CN.UTF-8
cd /d D:\projects\market-dashboard
C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe D:\projects\market-dashboard\news_watch.py >> D:\actions-runner\news_watch.log 2>&1
