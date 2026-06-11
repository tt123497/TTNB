#!/usr/bin/env python3
"""GitHub Actions data fetcher - runs in cloud every 15 min during A-share hours"""
import json, os, re, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

def fetch(url, encoding='gbk', retries=2):
    for i in range(retries):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urlopen(req, timeout=10) as r:
                return r.read().decode(encoding if 'eastmoney' not in url else 'utf-8', errors='replace')
        except Exception as e:
            if i == retries - 1: return None
            time.sleep(2)

def get_indices():
    codes = ['sh000001','sz399001','sz399006','sh000688','sh000300','sh000016']
    names = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指',
             'sh000688':'科创50','sh000300':'沪深300','sh000016':'上证50'}
    text = fetch('http://hq.sinajs.cn/list=' + ','.join(codes), encoding='gbk')
    if not text: return []
    results = []
    for line in text.strip().split('\n'):
        if '=' not in line: continue
        c = line.split('=')[0].replace('var hq_str_','')
        d = line.split('"')[1].split(',') if '"' in line else []
        if len(d) < 5: continue
        try:
            pr = float(d[3]); pv = float(d[2])
            ch = round((pr-pv)/pv*100,2) if pv else 0
            results.append({'n':names.get(c,c),'v':f'{pr:.0f}','chg':f'{ch:+.2f}%','up':ch>=0})
        except: pass
    return results

def get_sector_heat():
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?fid=f3&po=1&pz=30&pn=1&np=1&fltt=2&fields=f2,f3,f4,f12,f14&fs=m:90+t:3&ut=bd1d9ddb04089700cf9c27f6f7426281', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'n':i.get('f14',''),'s':f"{i.get('f3',0):+.1f}%",'c':'var(--red)' if i.get('f3',0)>0 else 'var(--green)'} for i in items[:30]]
    except: return []

def get_stock_codes():
    html_path = os.path.join(DIR, 'index.html')
    codes = set()
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()):
                codes.add(m.group(1))
    except: pass
    return sorted(codes)

def get_live_prices(all_codes):
    results = {}
    sina = []
    for c in all_codes:
        if c.startswith(('60','68')): sina.append(f'sh{c}')
        elif c.startswith(('00','30')): sina.append(f'sz{c}')
        elif c.startswith(('8','4','9')): sina.append(f'bj{c}')
        else: sina.append(f'sh{c}')

    for i in range(0, len(sina), 60):
        batch = sina[i:i+60]
        text = fetch('http://hq.sinajs.cn/list=' + ','.join(batch), encoding='gbk')
        if not text: continue
        for line in text.strip().split('\n'):
            if '=' not in line: continue
            c = line.split('=')[0].replace('var hq_str_','')
            d = line.split('"')[1].split(',') if '"' in line else []
            if len(d) < 5: continue
            try:
                pr = float(d[3]); pv = float(d[2])
                ch = round((pr-pv)/pv*100,2) if pv else 0
                results[c] = {'price':pr,'chg_pct':ch,'name':d[0]}
            except: pass
    return results

def get_news_headlines():
    """Scrape top financial news headlines"""
    headlines = []
    try:
        # Try EastMoney flash news
        text = fetch('http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f3,f12,f14&secids=1.000001,0.399001,0.399006&ut=bd1d9ddb04089700cf9c27f6f7426281', encoding='utf-8')
        # Try another source
        text2 = fetch('https://flash-api.xuangubao.cn/api/market_indicator/line?fields=market_temperature', encoding='utf-8')
        if text2:
            try:
                data = json.loads(text2)
                temp = data.get('data',{}).get('market_temperature',{})
                if temp:
                    headlines.append(f"市场温度: {temp}")
            except: pass
    except: pass
    return headlines

def main():
    now = datetime.now(timezone.utc)
    cst = now + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15

    codes = get_stock_codes()
    indices = get_indices()
    sectors = get_sector_heat()
    live = get_live_prices(codes[:100])  # Limit to first 100 for speed

    # Build recap
    sorted_sec = sorted(sectors, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)
    winners = [{'s': s['n'], 'stks': '实时领涨'} for s in sorted_sec[:6]]
    losers = [{'s': s['n'], 'stks': '实时领跌'} for s in sorted_sec[-6:][::-1]]

    next_update = '今日 17:00 收盘复盘' if is_trading else '下个交易日 9:15 开盘扫描'

    # Preserve manually-curated fields from existing data.json
    preserve = {}
    preserve_keys = ['sectors', 'top3', 'picks', 'briefing']
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                old = json.load(f)
                for k in preserve_keys:
                    if k in old and old[k]:
                        preserve[k] = old[k]
            except: pass

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': next_update,
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices[:6] if indices else [],
            'heat': sectors[:20] if sectors else [],
            'winners': winners,
            'losers': losers,
            'note': f"{cst.strftime('%m/%d %H:%M')} GitHub Actions云更新 | 每15分钟"
        },
        'livePrices': live,
        'runtime': {
            'cloud': True,
            'autoUpdate': True,
            'interval': '15min',
            'stockCount': len(codes),
            'liveCount': len(live),
            'updateCount': int(time.time() / 900),
            'trading': is_trading,
        }
    }
    # Merge preserved fields
    out.update(preserve)

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"✅ {out['updated']} | {len(indices)} indices | {len(sectors)} sectors | {len(live)} stocks | trading={is_trading}")

if __name__ == '__main__':
    main()
