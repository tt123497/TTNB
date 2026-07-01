#!/usr/bin/env python3
"""Build daily briefing from market data - runs 2x/day"""
import json, os, time
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
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
    cst = datetime.now(CST)
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
                'sec': '今日强势', 'why': f"涨幅 {s['chg']:+.1f}%，主力资金关注",
                'u': f"https://quote.eastmoney.com/sz{s['c']}.html"
            })

    # Build top news from market data
    recap = existing.get('recap', {})
    heat = recap.get('heat', [])
    indices = recap.get('index', [])

    top3 = []

    # News 1: Index summary
    if indices:
        idx_str = ' | '.join([f"{i['n']} {i['chg']}" for i in indices[:4]])
        up_count = sum(1 for i in indices if i['up'])
        sig = '🟢' if up_count >= 3 else '🟡' if up_count >= 2 else '🔴'
        top3.append({
            'r': 1, 't': f"{sig} 大盘实时: {idx_str}",
            'b': f"更新时间 {cst.strftime('%H:%M')}，每10分钟自动刷新。{'市场普涨' if up_count >= 3 else '市场分化' if up_count >= 2 else '市场调整'}。来源可信度：高（交易所实时行情）。已定价。",
            's': [],
            'u': 'https://quote.eastmoney.com/center/gridlist.html#hs_a_board'
        })

    # News 2: Hottest sectors
    if heat:
        top_sectors = heat[:5]
        em_code = 'BK0451'  # fallback
        top3.append({
            'r': 2, 't': f"🟢 今日热点板块: {', '.join([h['n'] for h in top_sectors[:5]])}",
            'b': f"领涨: {top_sectors[0]['n']} {top_sectors[0]['s']} | 来源可信度：高（东财板块行情实时数据）。已定价（板块日内涨幅已反映）。",
            's': [f"{h.get('code','')} {h['n']} {h['s']}" for h in top_sectors[:5]],
            'u': 'https://quote.eastmoney.com/center/boardlist.html#boards-BK'
        })

    # News 3: Top individual stocks
    if top_stocks:
        g = top_stocks[0]
        top3.append({
            'r': 3, 't': f"🟢 今日强势个股: {g['n']} {g['chg']:+.1f}%领涨",
            'b': ' | '.join([f"{s['n']}({s['c']}) {s['chg']:+.1f}%" for s in top_stocks[:5]]) + '。来源可信度：高（交易所行情）。已定价。',
            's': [f"{s['c']} {s['n']}" for s in top_stocks[:5]],
            'u': 'https://quote.eastmoney.com/center/gridlist.html#hs_a_board'
        })

    # Check if there's a recent AI-generated briefing — preserve it
    old_briefing = existing.get('briefing', {})
    if old_briefing.get('_ai') and old_briefing.get('updated'):
        # AI briefing exists, check if it's still fresh (< 3 hours)
        try:
            ai_time = datetime.strptime(old_briefing['updated'], '%Y-%m-%d %H:%M CST')
            ai_time = ai_time.replace(tzinfo=timezone(timedelta(hours=8)))
            age_min = (cst - ai_time).total_seconds() / 60
            if age_min < 180 and len(old_briefing.get('picks', [])) >= 5:
                print(f"AI briefing preserved (age={age_min:.0f}min), skip auto-gen")
                return
        except (ValueError, TypeError):
            pass  # Can't parse time, fall through to auto-generate

    # Archive old briefing to history before overwriting
    bHistory = existing.get('bHistory', [])
    if old_briefing and old_briefing.get('top3'):
        last_date = bHistory[0].get('updated','') if bHistory else ''
        if old_briefing.get('updated','') != last_date:
            bHistory.insert(0, old_briefing)
            bHistory = bHistory[:30]
        existing['bHistory'] = bHistory

    # Always generate fresh briefing — write both levels (标准: 根层+briefing双写)
    existing['briefing'] = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'top3': top3,
        'picks': picks,
    }
    existing['top3'] = top3
    existing['picks'] = picks
    print(f"Briefing auto-generated: {cst.strftime('%H:%M')}")

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    build_briefing()
