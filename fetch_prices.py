#!/usr/bin/env python3
"""Fetch live market data via Sina API (local only) and push to GitHub.
   Run by Claude cron every 15 min during trading hours."""
import json, os, re, time, subprocess
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(DIR, 'data.json')
GIT = r'D:\Tools\Git\bin\git.exe'

def fetch(url, enc='gbk', retries=2):
    for i in range(retries):
        try:
            r = urlopen(Request(url, headers={'User-Agent': UA, 'Referer': 'https://finance.sina.com.cn'}), timeout=10)
            return r.read().decode(enc, errors='replace')
        except:
            if i == retries - 1: return None
            time.sleep(2)

def get_indices():
    codes = ['sh000001','sz399001','sz399006','sh000688','sh000300','sh000016']
    names = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指','sh000688':'科创50','sh000300':'沪深300','sh000016':'上证50'}
    text = fetch('http://hq.sinajs.cn/list=' + ','.join(codes))
    if not text: return []
    results = []
    for line in text.strip().split('\n'):
        if '=' not in line: continue
        c, d = line.split('=')[0].replace('var hq_str_', ''), line.split('"')[1].split(',') if '"' in line else []
        if len(d) < 5: continue
        try:
            pr, pv = float(d[3]), float(d[2])
            ch = round((pr-pv)/pv*100, 2) if pv else 0
            results.append({'n': names.get(c, c), 'v': f'{pr:.0f}', 'chg': f'{ch:+.2f}%', 'up': ch >= 0})
        except: pass
    return results

def get_live_prices(codes):
    sina = []
    for c in codes:
        if c.startswith(('60','68')): sina.append(f'sh{c}')
        elif c.startswith(('00','30')): sina.append(f'sz{c}')
        elif c.startswith(('8','4','9')): sina.append(f'bj{c}')
        else: sina.append(f'sh{c}')
    results = {}
    for i in range(0, len(sina), 60):
        batch = sina[i:i+60]
        text = fetch('http://hq.sinajs.cn/list=' + ','.join(batch))
        if not text: continue
        for line in text.strip().split('\n'):
            if '=' not in line: continue
            sym = line.split('=')[0].replace('var hq_str_', '')
            parts = line.split('"')[1].split(',') if '"' in line else []
            if len(parts) < 5: continue
            try:
                pr, pv = float(parts[3]), float(parts[2])
                ch = round((pr-pv)/pv*100, 2) if pv else 0
                results[sym] = {'price': pr, 'chg_pct': ch, 'name': parts[0]}
            except: pass
        time.sleep(0.05)
    return results

def get_stock_codes():
    codes = set()
    idx_path = os.path.join(DIR, 'index.html')
    if os.path.exists(idx_path):
        with open(idx_path, 'r', encoding='utf-8') as f:
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()): codes.add(m.group(1))
    return sorted(codes)

def get_sector_mapping():
    """Parse index.html to map stock codes -> sector names"""
    mapping = {}
    idx_path = os.path.join(DIR, 'index.html')
    if not os.path.exists(idx_path): return mapping
    with open(idx_path, 'r', encoding='utf-8') as f:
        html = f.read()
    import re
    id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
    st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)
    for i in range(min(len(id_names), len(st_blocks))):
        _, sec_name = id_names[i]
        codes = re.findall(r'\{c:"(\d{6})"', st_blocks[i])
        for c in codes: mapping[c] = sec_name
    return mapping

def compute_sector_heat(live_prices, stock_sector):
    """Compute sector averages AND top/bottom stocks per sector"""
    sec_changes = {}  # {sector_name: [{code, name, chg_pct}]}
    for sina_key, v in live_prices.items():
        code = sina_key[2:]
        sec = stock_sector.get(code, '')
        if not sec: continue
        chg = v.get('chg_pct', 0)
        if sec not in sec_changes: sec_changes[sec] = []
        sec_changes[sec].append({'c': code, 'n': v.get('name', ''), 'chg': chg})

    heat = []
    sec_detail = {}  # {sector_name: "stock1+5% / stock2-3%"}
    for sec, stocks in sec_changes.items():
        if not stocks: continue
        avg = sum(s['chg'] for s in stocks) / len(stocks)
        heat.append({'n': sec, 's': f'{avg:+.1f}%', 'c': 'var(--red)' if avg > 0 else 'var(--green)'})
        # Top 5 gainers, bottom 5 losers within sector, sorted
        sorted_stks = sorted(stocks, key=lambda x: x['chg'], reverse=True)
        names = ' / '.join([f"{s['n']}{s['chg']:+.1f}%" for s in sorted_stks[:5]])
        sec_detail[sec] = names

    heat.sort(key=lambda x: float(x['s'].replace('%', '').replace('+', '').replace('-', '-')), reverse=True)
    return heat, sec_detail, sec_changes

def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15

    codes = get_stock_codes()
    indices = get_indices()
    live = get_live_prices(codes)
    stock_sector = get_sector_mapping()
    heat, sec_detail, sec_changes = compute_sector_heat(live, stock_sector)

    sorted_h = sorted(heat, key=lambda x: float(x['s'].replace('%', '').replace('+', '').replace('-', '-')), reverse=True)
    winners_list = [{'s': s['n'], 'stks': sec_detail.get(s['n'], '')} for s in sorted_h[:6]]
    losers_list = [{'s': s['n'], 'stks': sec_detail.get(s['n'], '')} for s in sorted_h[-6:][::-1]]

    # Load existing, preserve manual fields
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    else:
        existing = {}

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': existing.get('nextSentinel', '今日 09:15 早盘哨兵'),
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices,
            'heat': heat[:25],
            'winners': winners_list,
            'losers': losers_list,
            'note': f"{cst.strftime('%m/%d %H:%M')} 本地Sina实时 | 每15分钟"
        },
        'livePrices': live,
        'runtime': {
            'cloud': False, 'autoUpdate': True, 'interval': '15min',
            'stockCount': len(codes), 'liveCount': len(live),
            'updateCount': int(time.time() / 900),
            'trading': is_trading
        }
    }

    # Preserve manual fields
    for k in ['sectors', 'top3', 'picks', 'briefing', 'events']:
        if k in existing and existing[k]:
            out[k] = existing[k]

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"{out['updated']} | idx:{len(indices)} heat:{len(heat)} live:{len(live)} trading={is_trading}")

    # Git push
    subprocess.run([GIT, 'remote', 'set-url', 'origin', 'git@github.com:tt123497/market-sentinel.git'],
                   cwd=DIR, capture_output=True)
    subprocess.run([GIT, 'add', 'data.json'], cwd=DIR, capture_output=True)
    result = subprocess.run([GIT, 'diff', '--staged', '--quiet'], cwd=DIR)
    if result.returncode != 0:
        subprocess.run([GIT, 'commit', '-m', f"📊 {cst.strftime('%H:%M')} 本地Sina实时更新"],
                       cwd=DIR, capture_output=True)
        subprocess.run([GIT, 'push', 'origin', 'main'], cwd=DIR,
                       env={**os.environ, 'GIT_SSH_COMMAND': 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10'},
                       capture_output=True)
        print('Pushed.')

if __name__ == '__main__':
    main()
