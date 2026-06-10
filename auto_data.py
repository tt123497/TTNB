# -*- coding: utf-8 -*-
"""
Sentinel Auto-Updater - fetches realtime market data, writes data.json
Runs every 30 minutes. Compatible with Windows Python 3.11+.
"""
import json, os, re, time, random
from datetime import datetime
import requests

DIR = r'D:\projects\market-dashboard'
JSON_PATH = os.path.join(DIR, 'data.json')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}')

def fetch(url, referer='https://finance.sina.com.cn/'):
    try:
        r = requests.get(url, headers={'User-Agent':UA,'Referer':referer,'Accept':'*/*'}, timeout=8)
        # EastMoney serves UTF-8 JSON; Sina uses GBK
        if 'eastmoney' in url or 'push2' in url:
            r.encoding = 'utf-8'
        else:
            r.encoding = r.apparent_encoding or 'gbk'
        return r.text
    except Exception as e:
        return None

def get_indices():
    codes = ['sh000001','sz399001','sz399006','sh000688','sh000300','sh000016']
    names = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指','sh000688':'科创50','sh000300':'沪深300','sh000016':'上证50'}
    text = fetch('http://hq.sinajs.cn/list='+','.join(codes))
    if not text: return []
    results = []
    for line in text.strip().split('\n'):
        if '=' not in line: continue
        c = line.split('=')[0].replace('var hq_str_','')
        d = line.split('"')[1].split(',') if '"' in line else []
        if len(d)<5: continue
        try:
            pr=float(d[3]); pv=float(d[2]); ch=round((pr-pv)/pv*100,2) if pv else 0
            results.append({'n':names.get(c,c),'v':f'{pr:.0f}','chg':f'{ch:+.2f}%','up':ch>=0})
        except: pass
    return results

def get_sector_heat():
    url = 'http://push2.eastmoney.com/api/qt/clist/get?fid=f3&po=1&pz=30&pn=1&np=1&fltt=2&fields=f2,f3,f4,f12,f14&fs=m:90+t:3&ut=bd1d9ddb04089700cf9c27f6f7426281'
    text = fetch(url, referer='https://quote.eastmoney.com/')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'n':i.get('f14',''),'s':f"{i.get('f3',0):+.1f}%",'c':'var(--red)' if i.get('f3',0)>0 else 'var(--green)'} for i in items[:30]]
    except: return []

def get_live_prices(all_codes):
    """Batch fetch stock prices from Sina"""
    results = {}
    sina = []
    for c in all_codes:
        if c.startswith('60') or c.startswith('68'): sina.append(f'sh{c}')
        elif c.startswith('00') or c.startswith('30'): sina.append(f'sz{c}')
        elif c.startswith('8') or c.startswith('4') or c.startswith('9'): sina.append(f'bj{c}')
        else: sina.append(f'sh{c}')

    for i in range(0, len(sina), 60):
        batch = sina[i:i+60]
        text = fetch('http://hq.sinajs.cn/list='+','.join(batch))
        if not text: continue
        for line in text.strip().split('\n'):
            if '=' not in line: continue
            c = line.split('=')[0].replace('var hq_str_','')
            d = line.split('"')[1].split(',') if '"' in line else []
            if len(d)<5: continue
            try:
                pr=float(d[3]); pv=float(d[2]); ch=round((pr-pv)/pv*100,2) if pv else 0
                results[c] = {'price':pr,'chg_pct':ch,'name':d[0]}
            except: pass
    return results

def main():
    log('Sentinel Engine starting...')

    # Load tracked stock codes from HTML
    html_path = os.path.join(DIR, 'index.html')
    all_codes = set()
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()):
                all_codes.add(m.group(1))
        log(f'Tracking {len(all_codes)} stocks')
    except Exception as e:
        log(f'WARN: Cannot read HTML: {e}')

    count = 0
    while True:
        try:
            count += 1
            log(f'Update #{count}...')

            indices = get_indices()
            sectors = get_sector_heat()
            live = get_live_prices(all_codes) if all_codes else {}

            # Sort sectors
            sorted_sec = sorted(sectors, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)
            winners = [{'s':s['n'],'stks':'实时领涨'} for s in sorted_sec[:6]]
            losers = [{'s':s['n'],'stks':'实时领跌'} for s in sorted_sec[-6:][::-1]]

            now = datetime.now()
            is_weekday = now.weekday() < 5

            out = {
                'updated': now.strftime('%Y-%m-%d %H:%M CST'),
                'nextSentinel': '今日 17:03 收盘雷达' if is_weekday else '下个交易日 9:03',
                'updateCount': count,
                'recap': {
                    'index': indices[:6],
                    'heat': sectors[:20],
                    'winners': winners,
                    'losers': losers,
                    'note': f"{now.strftime('%m/%d %H:%M')} Python自动更新 | 每30分钟刷新 | {len(live)}只标的价格已抓取"
                },
                'livePrices': live,
                'runtime': {
                    'python': True, 'autoUpdate': True,
                    'interval': '30min', 'stockCount': len(all_codes),
                    'liveCount': len(live), 'updateCount': count
                }
            }

            with open(JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)

            log(f'OK: {len(indices)} indices, {len(sectors)} sectors, {len(live)} live stocks')

        except Exception as e:
            log(f'ERROR: {e}')

        time.sleep(1800)  # 30 min

if __name__ == '__main__':
    main()
