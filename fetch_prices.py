#!/usr/bin/env python3
"""Fetch live market data and push to GitHub. Run by Claude cron every 5 min.
   Data sources: Sina (indices+stocks), EastMoney HTTP (sectors+fund flow)"""
import json, os, re, time, subprocess
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(DIR, 'data.json')
GIT = r'D:\Tools\Git\bin\git.exe'

def fetch(url, enc='gbk', retries=2, extra_headers=None):
    for i in range(retries):
        try:
            headers = {'User-Agent': UA}
            if extra_headers: headers.update(extra_headers)
            r = urlopen(Request(url, headers=headers), timeout=10)
            return r.read().decode(enc, errors='replace')
        except:
            if i == retries - 1: return None
            time.sleep(2)

def em_json(url):
    """Fetch EastMoney JSON API over HTTP (works locally)"""
    text = fetch(url, enc='utf-8', extra_headers={'Accept': '*/*'})
    if not text: return []
    try:
        return json.loads(text).get('data', {}).get('diff', [])
    except: return []

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
    # Also include extra codes from data.json pending list
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                extra = json.load(f).get('extraCodes', [])
                for c in extra:
                    codes.add(str(c))
            except: pass
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

def get_sector_heat_em():
    """Get real concept sector ranking from EastMoney HTTP"""
    items = em_json(
        'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f2,f3,f12,f14'
    )
    return [{'n': i.get('f14', ''), 's': f"{i.get('f3', 0):+.1f}%",
             'c': 'var(--red)' if i.get('f3', 0) > 0 else 'var(--green)'} for i in items]

def get_fund_flow_em():
    """Get sector fund flow from EastMoney HTTP"""
    items = em_json(
        'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f12,f14,f62,f3'
    )
    out = []
    for i in items:
        out.append({
            'n': i.get('f14', ''),
            'amt': f"{'流入' if i.get('f62', 0) > 0 else '流出'}{abs(i.get('f62', 0)) / 100000000:.1f}亿",
            'chg': f"{i.get('f3', 0):+.1f}%"
        })
    return out

def compute_sector_stocks(live_prices, stock_sector, heat_data):
    """Match real sector ranking to our monitored stocks for winners/losers detail"""
    sec_changes = {}
    for sina_key, v in live_prices.items():
        code = sina_key[2:]
        sec = stock_sector.get(code, '')
        if not sec: continue
        chg = v.get('chg_pct', 0)
        if sec not in sec_changes: sec_changes[sec] = []
        sec_changes[sec].append({'c': code, 'n': v.get('name', ''), 'chg': chg})

    # Try to match EastMoney sector names to our sectors
    sec_detail = {}
    for sec, stocks in sec_changes.items():
        if not stocks: continue
        sorted_stks = sorted(stocks, key=lambda x: x['chg'], reverse=True)
        names = ' / '.join([f"{s['c']} {s['n']} {s['chg']:+.1f}%" for s in sorted_stks[:5]])
        sec_detail[sec] = names

    # Build winners/losers from heat data (real EastMoney ranking)
    sorted_em = sorted(heat_data, key=lambda x: float(x['s'].replace('%', '').replace('+', '').replace('-', '-')), reverse=True)
    winners = []; losers = []
    for s in sorted_em[:8]:
        matched = None
        for our_sec in sec_detail:
            if s['n'] in our_sec or our_sec in s['n'] or any(w in our_sec for w in s['n'][:2]):
                matched = our_sec; break
        stks = sec_detail.get(matched, '') if matched else ''
        winners.append({'s': s['n'], 'stks': stks or s['s']})
    for s in sorted_em[-8:][::-1]:
        matched = None
        for our_sec in sec_detail:
            if s['n'] in our_sec or our_sec in s['n'] or any(w in our_sec for w in s['n'][:2]):
                matched = our_sec; break
        stks = sec_detail.get(matched, '') if matched else ''
        losers.append({'s': s['n'], 'stks': stks or s['s']})

    return winners[:6], losers[:6]

def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15

    codes = get_stock_codes()
    indices = get_indices()
    live = get_live_prices(codes)
    heat = get_sector_heat_em()
    fund = get_fund_flow_em()
    stock_sector = get_sector_mapping()
    winners_list, losers_list = compute_sector_stocks(live, stock_sector, heat)

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
            'flow': fund,
            'winners': winners_list,
            'losers': losers_list,
            'note': f"{cst.strftime('%m/%d %H:%M')} 东财板块+Sina个股 | 每5分钟"
        },
        'livePrices': live,
        'runtime': {
            'cloud': False, 'autoUpdate': True, 'interval': '5min',
            'stockCount': len(codes), 'liveCount': len(live),
            'updateCount': int(time.time() / 900),
            'trading': is_trading
        }
    }

    # Preserve manual fields
    for k in ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout']:
        if k in existing and existing[k]:
            out[k] = existing[k]

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"{out['updated']} | idx:{len(indices)} heat:{len(heat)} live:{len(live)} flow:{len(fund)}")

    # Git push
    subprocess.run([GIT, 'remote', 'set-url', 'origin', 'git@github.com:tt123497/market-sentinel.git'],
                   cwd=DIR, capture_output=True)
    subprocess.run([GIT, 'add', 'data.json'], cwd=DIR, capture_output=True)
    result = subprocess.run([GIT, 'diff', '--staged', '--quiet'], cwd=DIR)
    if result.returncode != 0:
        subprocess.run([GIT, 'commit', '-m', f"📊 {cst.strftime('%H:%M')} 东财板块+Sina个股实时更新"],
                       cwd=DIR, capture_output=True)
        subprocess.run([GIT, 'push', 'origin', 'main'], cwd=DIR,
                       env={**os.environ, 'GIT_SSH_COMMAND': 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10'},
                       capture_output=True)
        print('Pushed.')

if __name__ == '__main__':
    main()
