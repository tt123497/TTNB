#!/bin/bash
# Start news daemon — fetches news every 60s, writes data.json, no git push
# Uses runner's own Python environment
cd /d/actions-runner/_work/TTNB/TTNB 2>/dev/null || cd /d/projects/market-dashboard
while true; do
  PYTHONUTF8=1 python news_fetch_once.py 2>/dev/null
  sleep 60
done
