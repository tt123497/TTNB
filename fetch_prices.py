#!/usr/bin/env python3
"""Fetch live market data (all EastMoney HTTP, no Sina dependency) + git push. Run every 5 min."""
import json, os, re, time, subprocess
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(DIR, 'data.json')
GIT = r'D:\Tools\Git\bin\git.exe'

def em_json(url, retries=2):
    for i in range(retries):
        try:
            r = urlopen(Request(url, headers={'User-Agent': UA, 'Accept': '*/*'}), timeout=12)
            return json.loads(r.read().decode('utf-8')).get('data') or {}
        except:
            if i == retries - 1: return {}
            time.sleep(2)

# ═══════════ Indices (EastMoney) ═══════════
INDEX_MAP = {'1.000001': '上证指数', '0.399001': '深证成指', '0.399006': '创业板指',
             '1.000688': '科创50', '1.000300': '沪深300', '1.000016': '上证50'}

def get_indices():
    items = em_json(f"http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={','.join(INDEX_MAP)}").get('diff', [])
    return [{'n': INDEX_MAP.get(i.get('f12',''), i.get('f14','')), 'v': f"{i.get('f2',0):.0f}",
             'chg': f"{i.get('f3',0):+.2f}%", 'up': i.get('f3',0)>=0} for i in items]

# ═══════════ Stock codes ═══════════
def get_stock_codes():
    codes = set()
    idx_path = os.path.join(DIR, 'index.html')
    if os.path.exists(idx_path):
        with open(idx_path, 'r', encoding='utf-8') as f:
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()): codes.add(m.group(1))
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                for c in json.load(f).get('extraCodes', []): codes.add(str(c))
            except: pass
    return sorted(codes)

# ═══════════ Live prices (EastMoney batch) ═══════════
def get_live_prices(codes):
    results = {}
    secids = []
    for c in codes:
        if c[0] in '68': secids.append(f'1.{c}')
        elif c[0] in '89': secids.append(f'133.{c}')  # BSE stocks use 133. prefix in EastMoney
        else: secids.append(f'0.{c}')
    for i in range(0, len(secids), 100):
        batch = ','.join(secids[i:i+100])
        for s in em_json(f"http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={batch}").get('diff', []):
            c = s.get('f12', '')
            key = f"sh{c}" if c[0] in '68' else f"sz{c}"
            results[key] = {'price': s.get('f2',0) or 0, 'chg_pct': s.get('f3',0) or 0, 'name': s.get('f14','') or ''}
        time.sleep(0.1)
    # Fill in any missing codes with zero (delisted BSE stocks etc.)
    for c in codes:
        for pfx in ['sh','sz']:
            if pfx + c in results:
                break
        else:
            results['sh' + c] = {'price': 0, 'chg_pct': 0, 'name': ''}
    return results

# ═══════════ Sector heat ═══════════
def get_sector_heat_em():
    return [{'n': i.get('f14',''), 's': f"{i.get('f3',0):+.1f}%",
             'c': 'var(--red)' if i.get('f3',0)>0 else 'var(--green)'}
            for i in em_json("http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f2,f3,f12,f14").get('diff',[])]

# ═══════════ Fund flow ═══════════
def get_fund_flow_em():
    """Returns flow items in format HTML expects: {n, amt: '+87.9亿'}"""
    items = em_json("http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f3,f12,f14,f62").get('diff', [])
    return [{'n': i.get('f14', ''), 'amt': f"{'+' if i.get('f62', 0) > 0 else ''}{abs(i.get('f62', 0) or 0) / 100000000:.1f}亿"}
            for i in items]

# ═══════════ Sector mapping (from index.html D.groups) ═══════════
def get_sector_mapping():
    mapping = {}
    idx_path = os.path.join(DIR, 'index.html')
    if not os.path.exists(idx_path): return mapping
    with open(idx_path, 'r', encoding='utf-8') as f:
        html = f.read()
    id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
    st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)
    for i in range(min(len(id_names), len(st_blocks))):
        _, sec_name = id_names[i]
        for c in re.findall(r'\{c:"(\d{6})"', st_blocks[i]): mapping[c] = sec_name
    return mapping

# ═══════════ Winners/Losers with stock codes ═══════════
def compute_winners_losers(live, stock_sector, heat_em):
    sec_changes = {}
    for key, v in live.items():
        code = key[2:]
        sec = stock_sector.get(code, '')
        if not sec: continue
        chg = v.get('chg_pct', 0)
        sec_changes.setdefault(sec, []).append({'c': code, 'n': v.get('name',''), 'chg': chg})

    sec_detail = {}
    for sec, stocks in sec_changes.items():
        ss = sorted(stocks, key=lambda x: x['chg'], reverse=True)
        sec_detail[sec] = ' / '.join([f"{s['c']} {s['n']} {s['chg']:+.1f}%" for s in ss[:5]])

    sorted_em = sorted(heat_em, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)
    winners, losers = [], []
    for s in sorted_em[:10]:
        matched = next((o for o in sec_detail if s['n'][:2] in o or o in s['n'] or s['n'] in o), None)
        stks = sec_detail.get(matched,'') if matched else ''
        winners.append({'s': s['n'], 'stks': stks or s['s']})
    for s in sorted_em[-10:][::-1]:
        matched = next((o for o in sec_detail if s['n'][:2] in o or o in s['n'] or s['n'] in o), None)
        stks = sec_detail.get(matched,'') if matched else ''
        losers.append({'s': s['n'], 'stks': stks or s['s']})
    return winners[:6], losers[:6]

# ═══════════════ MAIN ═══════════════
def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15
    tick = time.time()

    codes = get_stock_codes()
    indices = get_indices()
    live = get_live_prices(codes)
    heat = get_sector_heat_em()
    fund = get_fund_flow_em()
    stock_sector = get_sector_mapping()
    winners, losers = compute_winners_losers(live, stock_sector, heat)

    existing = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try: existing = json.load(f)
            except: pass

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': existing.get('nextSentinel', '今日 09:15 早盘哨兵'),
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices,
            'heat': heat[:25],
            'flow': fund,
            'winners': winners,
            'losers': losers,
            'note': f"{cst.strftime('%m/%d %H:%M')} 东财全源 | {len(live)}只 | {len(heat)}板块"
        },
        'livePrices': live,
        'runtime': {
            'cloud': False, 'autoUpdate': True, 'interval': '5min',
            'stockCount': len(codes), 'liveCount': len(live),
            'updateCount': int(time.time() / 900), 'trading': is_trading
        }
    }
    for k in ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout', 'extraCodes']:
        if k in existing and existing[k]: out[k] = existing[k]

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    ms = int((time.time() - tick) * 1000)
    print(f"{out['updated']} idx:{len(indices)} heat:{len(heat)} live:{len(live)} flow:{len(fund)} {ms}ms")

    # Git push
    subprocess.run([GIT, 'remote', 'set-url', 'origin', 'git@github.com:tt123497/market-sentinel.git'],
                   cwd=DIR, capture_output=True, timeout=10)
    subprocess.run([GIT, 'add', 'data.json'], cwd=DIR, capture_output=True, timeout=10)
    r = subprocess.run([GIT, 'diff', '--staged', '--quiet'], cwd=DIR, timeout=10)
    if r.returncode != 0:
        subprocess.run([GIT, 'commit', '-m', f"📊 {cst.strftime('%H:%M')} 东财全源更新"],
                       cwd=DIR, capture_output=True, timeout=10)
        subprocess.run([GIT, 'push', 'origin', 'main'], cwd=DIR,
                       env={**os.environ, 'GIT_SSH_COMMAND': 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10'},
                       capture_output=True, timeout=30)
        print('Pushed.')

if __name__ == '__main__':
    main()
