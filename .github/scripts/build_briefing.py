#!/usr/bin/env python3
"""Build daily briefing from market data - runs 2x/day"""
import json, os, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

def fetch(url, encoding='utf-8'):
    try:
        req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
        with urlopen(req, timeout=10) as r:
            return r.read().decode(encoding, errors='replace')
    except: return None

def get_top_gainers():
    """Get top gaining stocks from EastMoney"""
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?fid=f3&po=1&pz=10&pn=1&np=1&fltt=2&fields=f2,f3,f12,f14&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&ut=bd1d9ddb04089700cf9c27f6f7426281')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'c': i.get('f12',''), 'n': i.get('f14',''), 'chg': i.get('f3',0)} for i in items[:8]]
    except: return []

def get_market_temperature():
    """Get market breadth data"""
    text = fetch('http://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,f107,f116,f117,f162,f167,f168,f169,f170,f171,f292')
    if not text: return None
    try:
        return json.loads(text)
    except: return None

def build_briefing():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    top_stocks = get_top_gainers()

    # Read existing data.json
    existing = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try: existing = json.load(f)
            except: pass

    # Build briefing messages
    msgs = []
    picks = []

    if top_stocks:
        # Top gainers become picks
        for i, s in enumerate(top_stocks[:5]):
            picks.append({
                'r': i+1, 'c': s['c'], 'n': s['n'],
                'sec': '今日强势', 'why': f"涨幅 {s['chg']:+.1f}%，主力资金关注"
            })

    # Build top news from market data
    recap = existing.get('recap', {})
    heat = recap.get('heat', [])
    indices = recap.get('index', [])

    top3 = []

    # News 1: Index summary
    if indices:
        idx_str = ' | '.join([f"{i['n']} {i['chg']}" for i in indices[:4]])
        top3.append({
            'r': 1, 't': f"📊 大盘实时: {idx_str}",
            'b': f"更新时间 {cst.strftime('%H:%M')}，数据每15分钟自动刷新。{'市场普涨' if sum(1 for i in indices if i['up']) >= 3 else '市场分化' if sum(1 for i in indices if i['up']) >= 2 else '市场调整'}。",
            's': []
        })

    # News 2: Hottest sectors
    if heat:
        top_sectors = heat[:5]
        top3.append({
            'r': 2, 't': f"🔥 今日最热板块: {', '.join([h['n'] for h in top_sectors[:5]])}",
            'b': f"领涨: {top_sectors[0]['n']} {top_sectors[0]['s']} | 市场风格{'偏科技' if any(k in top_sectors[0]['n'] for k in ['半导','芯片','光','PCB','MLCC','AI']) else '偏周期/消费'}",
            's': [f"{h['n']} {h['s']}" for h in top_sectors[:5]]
        })

    # News 3: Top individual stocks
    if top_stocks:
        top3.append({
            'r': 3, 't': f"🎯 今日强势个股 TOP5",
            'b': ' | '.join([f"{s['n']}({s['c']}) {s['chg']:+.1f}%" for s in top_stocks[:5]]),
            's': [f"{s['c']} {s['n']}" for s in top_stocks[:5]]
        })

    # Archive old briefing to history before overwriting
    old_briefing = existing.get('briefing', {})
    bHistory = existing.get('bHistory', [])
    if old_briefing and old_briefing.get('top3'):
        last_date = bHistory[0].get('updated','') if bHistory else ''
        if old_briefing.get('updated','') != last_date:
            bHistory.insert(0, old_briefing)
            bHistory = bHistory[:30]
        existing['bHistory'] = bHistory

    # Always generate fresh briefing
    existing['briefing'] = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'top3': top3,
        'picks': picks,
    }
    print(f"Briefing auto-generated: {cst.strftime('%H:%M')}")

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    build_briefing()
