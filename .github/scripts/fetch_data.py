#!/usr/bin/env python3
"""GitHub Actions data fetcher - runs in cloud every 15 min during A-share hours"""
import json, os, re, time, shutil, glob as _glob
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

def fetch(url, encoding='gbk', retries=2, extra_headers=None):
    for i in range(retries):
        try:
            headers = {'User-Agent': UA, 'Accept': '*/*'}
            if extra_headers: headers.update(extra_headers)
            req = Request(url, headers=headers)
            enc = encoding if 'eastmoney' not in url and 'push2ex' not in url else 'utf-8'
            with urlopen(req, timeout=12) as r:
                return r.read().decode(enc, errors='replace')
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
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f2,f3,f12,f14', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'n':i.get('f14',''),'s':f"{i.get('f3',0):+.1f}%",'c':'var(--red)' if i.get('f3',0)>0 else 'var(--green)'} for i in items[:50]]
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

def get_sector_mapping():
    """Extract {stock_code: sector_name} from index.html D.groups st:[] blocks"""
    mapping = {}
    html_path = os.path.join(DIR, 'index.html')
    if not os.path.exists(html_path): return mapping
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
    st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)
    for i in range(min(len(id_names), len(st_blocks))):
        _, sec_name = id_names[i]
        for c in re.findall(r'\{c:"(\d{6})"', st_blocks[i]):
            mapping[c] = sec_name
    return mapping

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
        time.sleep(0.05)
    return results

def get_fund_flow_em():
    """Returns fund flow: [{n, amt: '+87.9亿'}, ...]"""
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f3,f12,f14,f62', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'n': i.get('f14',''), 'amt': f"{'+' if float(i.get('f62',0) or 0) > 0 else ''}{abs(float(i.get('f62',0) or 0)) / 100000000:.1f}亿"}
                for i in items]
    except: return []

def compute_winners_losers(live, stock_sector, heat_em):
    """Group live prices by sector, produce top-5 stock detail per sector"""
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

def get_zt_ladder(cst):
    """Fetch consecutive limit-up pool from EastMoney. Returns {tiers, maxBoard, totalCount} or None"""
    # Try today first, then fall back to last trading day
    for attempt in range(3):
        try_date = cst - timedelta(days=attempt)
        if try_date.weekday() >= 5: continue  # skip weekends
        date_str = try_date.strftime('%Y%m%d')
        url = (f'http://push2ex.eastmoney.com/getTopicZTPool'
               f'?ut=7eea3edcaed734bea9cbfc24409ed989'
               f'&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date={date_str}')
        text = fetch(url, encoding='utf-8', extra_headers={'Referer': 'http://quote.eastmoney.com/'})
        if not text: continue
        try:
            # Handle JSONP wrapper: callback({...})
            if text.startswith('callback('):
                text = text[9:-1]
            elif text.startswith('jQuery'):
                text = text[text.index('(')+1:-1]
            data_obj = json.loads(text)
            items = data_obj.get('data', {}).get('pool', [])
        except Exception:
            continue
        if not items: continue

        tiers_dict = {}
        for item in items:
            lbc = item.get('lbc', 1) or 1
            stock = {
                'c': item.get('c', ''),
                'n': item.get('n', ''),
                'industry': item.get('hybk', ''),
                'p': (item.get('p', 0) or 0) / 1000 if item.get('p', 0) else 0,
                'zdf': item.get('zdp', 0)
            }
            tiers_dict.setdefault(lbc, []).append(stock)

        tiers = [{'boardCount': k, 'stocks': v} for k, v in sorted(tiers_dict.items(), reverse=True)]
        return {
            'updated': cst.strftime('%Y-%m-%d %H:%M'),
            'tiers': tiers,
            'maxBoard': max(tiers_dict.keys()) if tiers_dict else 0,
            'totalCount': len(items)
        }
    return None

def main():
    now = datetime.now(timezone.utc)
    cst = now + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15

    codes = get_stock_codes()
    stock_sector = get_sector_mapping()
    indices = get_indices()
    sectors = get_sector_heat()
    live = get_live_prices(codes)
    fund = get_fund_flow_em()
    zt_ladder = get_zt_ladder(cst)

    # Compute winners/losers with real stock detail
    winners, losers = compute_winners_losers(live, stock_sector, sectors)

    next_update = '今日 17:00 收盘复盘' if is_trading else '下个交易日 9:15 开盘扫描'

    # Preserve manually-curated fields from existing data.json
    preserve = {}
    preserve_keys = ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout', 'bHistory']
    old_cycle = None
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                old = json.load(f)
                for k in preserve_keys:
                    if k in old and old[k]:
                        preserve[k] = old[k]
                old_recap = old.get('recap', {})
                if 'cycle' in old_recap and old_recap['cycle']:
                    old_cycle = old_recap['cycle']
            except: pass

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': next_update,
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices[:6] if indices else [],
            'heat': sectors[:25] if sectors else [],
            'flow': fund,
            'winners': winners,
            'losers': losers,
            'ztLadder': zt_ladder,
            'note': f"{cst.strftime('%m/%d %H:%M')} GitHub Actions云更新 | {len(codes)}只 | {len(sectors)}板块"
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
    if old_cycle:
        out['recap']['cycle'] = old_cycle

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Archive snapshot at market close (~15:00-15:30 CST)
    if is_trading and cst.hour == 15 and cst.minute < 45:
        archive_dir = os.path.join(DIR, 'archive')
        os.makedirs(archive_dir, exist_ok=True)
        date_key = cst.strftime('%Y-%m-%d')
        archive_path = os.path.join(archive_dir, f'{date_key}.json')
        shutil.copy2(DATA_PATH, archive_path)
        # Update index.json
        existing_archives = sorted(
            [os.path.basename(f).replace('.json','') for f in _glob.glob(os.path.join(archive_dir, '*.json'))
             if not os.path.basename(f) == 'index.json'],
            reverse=True
        )
        with open(os.path.join(archive_dir, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump(existing_archives, f, ensure_ascii=False)
        print(f"📦 Archived: {date_key} ({len(existing_archives)} snapshots)")

    print(f"✅ {out['updated']} | {len(indices)} idx | {len(sectors)} sec | {len(live)} stks | flow={len(fund)} | zt={zt_ladder and zt_ladder.get('totalCount',0) or 0} | trading={is_trading}")

if __name__ == '__main__':
    main()
