#!/usr/bin/env python3
"""
Hot sector discovery + persistence tracking.

Every 5 min:
  1. Scans EastMoney top concept boards
  2. If a board >2% that we DON'T track in our ~63 sectors → log it
  3. Tracks consecutive calendar days of heat via _sectorTracker
  4. If a sector is hot for ≥2 consecutive days AND avg gain ≥3% →
     writes to _promoteQueue with full stock list
  5. Claude checks _promoteQueue on session start → auto-adds to site
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

# All currently tracked sectors (keep in sync with sentinel_ai.py OUR_SECTORS)
OUR_SECTORS = {
    'AI芯片','CPO/光模块','光纤光缆','连接器/铜连接',
    'PCB/覆铜板','MLCC电容','电子树脂/PPE','电子铜箔','HBM/存储芯片',
    'AI服务器/超节点','液冷散热','交换机/网络','电源/DrMOS','数据中心/AIDC',
    '算电协同','电网设备/特高压','火电/电力运营','算力租赁/GPU云',
    '半导体设备','光刻胶','先进封装CoWoS','半导体硅片','半导体靶材',
    '六氟化钨WF₆','玻璃基板TGV','培育钻石/散热','超导/核聚变','碳纤维',
    '稀土永磁','钼/小金属','电子特气/工业气体',
    '人形机器人','商业航天','6G/通信','固态电池','低空经济eVTOL','空间计算/物理AI','钨稀土',
    'AI眼镜/AR硬件','AI应用/模型推理','核电/核能','量子计算/量子科技','卫星互联网/北斗',
    '锂矿/盐湖提锂','锂电池/电解液','光伏/太阳能','风电','储能','新能源汽车',
    '煤炭','黄金/贵金属','铜铝有色','化工','钢铁',
    '银行','券商','保险','房地产开发',
    '白酒','食品饮料','医药/CRO','医疗器械',
}

EXCLUDE = {'昨日打板','科创板做市','融资融券','大盘股','HS300','上证180',
    '标准普尔','周期股','行业龙头','MSCI中国','GDR','参股期货','首发经济',
    '金融地产','DRG/DIP','CAR-T','共享经济','可燃冰','低碳冶金','草甘膦',
    '动力电池回收','托育服务','刀片电池','病毒防治','CRO概念','锂矿概念'}

def fetch(url, retries=2):
    for _ in range(retries):
        try:
            r = urlopen(Request(url, headers={'User-Agent': UA, 'Accept': '*/*'}), timeout=15)
            return r.read().decode('utf-8', errors='replace')
        except:
            time.sleep(2)
    return None

def discover():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today_str = cst.strftime('%Y-%m-%d')
    today_cn = cst.strftime('%m/%d')

    # Fetch top 60 concept boards
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=60&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f2,f3,f12,f14')
    if not text:
        return
    try:
        items = json.loads(text).get('data', {}).get('diff', [])
    except:
        return

    # Load data.json
    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                pass

    # ── Step 1: Find hot sectors we don't track ──
    snapshot = []
    for h in items[:30]:
        pct = h.get('f3', 0) or 0
        if pct < 2.0:
            continue
        name = h.get('f14', '')
        if any(ex in name or name in ex for ex in EXCLUDE):
            continue
        # Is this already one of our tracked sectors?
        matched = False
        for our in OUR_SECTORS:
            if len(our) >= 2 and len(name) >= 2:
                if our in name or name in our or our[:3] in name or name[:3] in our:
                    matched = True
                    break
        if matched:
            continue

        bcode = h.get('f12', '')
        snapshot.append({'n': name, 'bk': bcode, 'pct': round(pct, 1), 'date': today_str})

    # ── Step 2: Update sector persistence tracker ──
    tracker = data.get('_sectorTracker', {})
    # tracker is: {sector_name: {first_seen, last_seen, days, max_pct, bk, stocks[]}}

    for entry in snapshot:
        name = entry['n']
        if name not in tracker:
            # First time seeing this sector
            tracker[name] = {
                'first_seen': today_str,
                'last_seen': today_str,
                'days': 1,
                'max_pct': entry['pct'],
                'bk': entry['bk'],
                'stocks': []
            }
        else:
            t = tracker[name]
            last_d = t.get('last_seen', '')
            # Count calendar days properly
            if last_d != today_str:
                try:
                    last_date = datetime.strptime(last_d, '%Y-%m-%d').date()
                    today_date = cst.date()
                    if (today_date - last_date).days == 1:
                        t['days'] = t.get('days', 0) + 1  # consecutive
                    elif (today_date - last_date).days > 1:
                        t['days'] = 1  # reset — gap too large
                except:
                    t['days'] = t.get('days', 0) + 1
            t['last_seen'] = today_str
            if entry['pct'] > t.get('max_pct', 0):
                t['max_pct'] = entry['pct']
            t['bk'] = entry['bk']  # update board code

    # Cleanup: drop sectors not seen in 7 days
    stale = []
    for name, t in tracker.items():
        try:
            last_date = datetime.strptime(t.get('last_seen', '2000-01-01'), '%Y-%m-%d').date()
            if (cst.date() - last_date).days > 7:
                stale.append(name)
        except:
            stale.append(name)
    for name in stale:
        del tracker[name]

    # ── Step 3: Fetch stock lists for sectors with ≥2 consecutive days ──
    promote_queue = data.get('_promoteQueue', [])
    seen_promote = {(p['name'], p.get('bk', '')) for p in promote_queue}

    for name, t in tracker.items():
        if t.get('days', 0) >= 2 and t.get('max_pct', 0) >= 3.0:
            key = (name, t.get('bk', ''))
            if key not in seen_promote and not t.get('stocks'):
                # Fetch stocks for this board
                bcode = t.get('bk', '')
                stocks = []
                for retry in range(2):
                    try:
                        t2 = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=12&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:%s&fields=f2,f3,f12,f14' % bcode)
                        if t2:
                            for s in json.loads(t2).get('data', {}).get('diff', []):
                                stocks.append({'c': s.get('f12', ''), 'n': s.get('f14', ''), 'chg': round(s.get('f3', 0), 1)})
                            break
                    except:
                        pass
                    time.sleep(0.5)
                t['stocks'] = stocks

                # Add to promote queue
                if len(stocks) >= 5:
                    promote_queue.append({
                        'name': name,
                        'bk': bcode,
                        'days': t['days'],
                        'max_pct': t['max_pct'],
                        'first_seen': t['first_seen'],
                        'stocks': stocks[:10],
                        'discovered': today_str
                    })
                    seen_promote.add(key)
                    print(f'PROMOTE: {name} ({t["days"]}d, max {t["max_pct"]}%, {len(stocks)} stocks)')

    # ── Step 4: Also add new hot sectors to dynamicSectors ──
    dyn_candidates = []
    for h in items:
        pct = h.get('f3', 0) or 0
        if pct < 2.0:
            continue
        name = h.get('f14', '')
        skip = False
        for ex in EXCLUDE:
            if ex in name or name in ex:
                skip = True
                break
        if skip:
            continue
        for our in OUR_SECTORS:
            if len(our) >= 2 and (our in name or name in our or our[:3] in name or name[:3] in our):
                skip = True
                break
        if not skip:
            dyn_candidates.append((h, pct))

    discovered = []
    for h, pct in dyn_candidates[:5]:
        bcode, name = h.get('f12', ''), h.get('f14', '')
        stocks = []
        for retry in range(2):
            try:
                t2 = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=12&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:%s&fields=f2,f3,f12,f14' % bcode)
                if t2:
                    for s in json.loads(t2).get('data', {}).get('diff', []):
                        stocks.append({'c': s.get('f12', ''), 'n': s.get('f14', ''), 'chg': round(s.get('f3', 0), 1)})
                    break
            except:
                pass
        if not stocks:
            continue

        icons = {'航天': '🚀', '航空': '✈️', '军工': '🛡️', '黄金': '🥇', '金融': '💰', '银行': '🏦',
                 '医药': '💊', '医疗': '🏥', '消费': '🛒', '食品': '🍜', '白酒': '🍶', '汽车': '🚗',
                 '新能源': '🔋', '光伏': '☀️', '风电': '🌬️', '煤炭': '⛏️', '石油': '🛢️',
                 '化工': '🧪', '钢铁': '🏗️', '电力': '⚡', '环保': '♻️', '游戏': '🎮', '传媒': '📺', '锂': '🔋'}
        icon = next((ic for kw, ic in icons.items() if kw in name), '🔥')
        pct_s = '%+.1f' % pct

        discovered.append({
            'id': 'dyn_%s' % bcode, 'n': name, 'icon': icon,
            'sig': 'major' if pct >= 4 else 'good',
            'tag': '%s%%|%s' % (pct_s.lstrip('+'), today_cn),
            'd': '%s板块%s%%,当日新晋热门。共%d只标的。' % (name, pct_s, len(stocks)),
            'st': stocks,
            'ch': {'up': '---', 'mid': '<em>板块%s%%</em>' % pct_s, 'down': '---'},
            'ev': '%s自动发现' % today_cn, 'stars': 3
        })

    # ── Write everything back ──
    data['_sectorTracker'] = tracker
    data['_promoteQueue'] = promote_queue[:10]
    data['_hot_uncovered'] = snapshot[:15]

    if discovered:
        old_dyn = data.get('dynamicSectors', [])
        merged = discovered + old_dyn
        seen, dedup = set(), []
        for ds in merged:
            k = ds['id']
            if k not in seen:
                seen.add(k)
                dedup.append(ds)
        data['dynamicSectors'] = dedup[:8]

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Summary
    tracking = sum(1 for t in tracker.values() if t.get('days', 0) >= 2)
    print('Snapshot: %d hot uncovered | Tracking: %d sectors | ≥2d: %d | Promote: %d | Dynamic: %d' % (
        len(snapshot), len(tracker), tracking, len(promote_queue), len(discovered)))
    if promote_queue:
        for p in promote_queue:
            print('  ⭐ %s — %dd, max %.1f%%, %d stocks' % (p['name'], p['days'], p['max_pct'], len(p['stocks'])))


if __name__ == '__main__':
    discover()
