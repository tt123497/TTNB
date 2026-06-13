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
    """Use EastMoney API (works from GitHub Actions US IPs, unlike Sina)"""
    names = {'1.000001':'上证指数','0.399001':'深证成指','0.399006':'创业板指',
             '1.000688':'科创50','1.000300':'沪深300','1.000016':'上证50'}
    secids = ','.join(names.keys())
    text = fetch(f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f12,f14&secids={secids}&ut=bd1d9ddb04089700cf9c27f6f7426281', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        results = []
        for i in items:
            n = names.get(i.get('f12',''), i.get('f14',''))
            p = i.get('f2', 0)
            chg = i.get('f3', 0)
            results.append({'n': n, 'v': f'{p:.0f}' if p else '0', 'chg': f'{chg:+.2f}%', 'up': chg >= 0})
        return results
    except: return []

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
    """Use EastMoney batch API (works from GitHub Actions US IPs)"""
    results = {}
    secids = []
    for c in all_codes:
        if c.startswith(('60','68')): secids.append(f'1.{c}')
        elif c.startswith(('00','30')): secids.append(f'0.{c}')
        else: secids.append(f'1.{c}')

    for i in range(0, len(secids), 100):
        batch = secids[i:i+100]
        url = f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={",".join(batch)}&ut=bd1d9ddb04089700cf9c27f6f7426281'
        text = fetch(url, encoding='utf-8')
        if not text: continue
        try:
            items = json.loads(text).get('data',{}).get('diff',[])
            for s in items:
                c = s.get('f12','')
                price = s.get('f2', 0)
                chg = s.get('f3', 0)
                sina_key = f'sh{c}' if c.startswith(('60','68')) else f'sz{c}'
                results[sina_key] = {'price': price, 'chg_pct': chg, 'name': s.get('f14','')}
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
    preserve_keys = ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout']
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
