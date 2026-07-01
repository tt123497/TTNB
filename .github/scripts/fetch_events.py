#!/usr/bin/env python3
"""
Event Calendar — runs once daily at 10:00 CST.

Data sources:
  1. NBS 2026 Macro Calendar — algorithmically generated from NBS published schedule
     (PMI/CPI/trade/industrial/M2/LPR/FOMC etc. with auto weekend adjustment)
  2. EastMoney earnings forecast API — real company 业绩预告 (when sector-matching)
  3. AI Sentinel newEvents — from real market news analysis (runs 4x/day independently)
  4. Hand-curated events (with 'u' URL field) — preserved FOREVER

Rules:
  - Hand events (with 'u' URL) are NEVER deleted
  - Past events stay in the list (frontend marks them with 'past' class)
  - New events MERGE into existing, never replace
  - Cap: 100 events total (trims oldest non-hand past events if needed)
"""
import json, os, re, time, calendar as cal
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# ═══════════════════════════════════════════════════
# Layout Builder: events → layout cards with real stocks
# ═══════════════════════════════════════════════════

# Sector name → possible EastMoney board search terms (try in order)
SECTOR_BOARD_HINTS = {
    '钨/稀土': ['钨','稀土','小金属','稀有金属'],
    '钨': ['钨','小金属'],
    '稀土': ['稀土','小金属'],
    '商业航天': ['航天航空','航天','商业航天'],
    '人形机器人': ['机器人','人形机器人','自动化设备'],
    '固态电池': ['固态电池','电池','锂电池'],
    '六氟化钨': ['电子化学品','氟化工','化工'],
    '六氟化钨/钨': ['电子化学品','钨','小金属'],
    '低空经济': ['低空经济','通用航空','飞行汽车'],
    '低空经济eVTOL': ['低空经济','通用航空','飞行汽车'],
    'MLCC': ['MLCC','被动元件','电子元件'],
    'MLCC电容': ['被动元件','电子元件','MLCC'],
    'MLCC/被动元件': ['被动元件','电子元件','MLCC'],
    '电子树脂/PPE': ['电子化学品','化工','树脂'],
    '电子树脂/PCB': ['电子化学品','PCB','印制电路板'],
    'PCB/覆铜板': ['PCB','覆铜板','印制电路板'],
    '存储芯片': ['存储芯片','半导体'],
    'HBM/存储芯片': ['存储芯片','HBM','半导体'],
    '存储/设备': ['存储芯片','半导体设备'],
    'AI芯片': ['AI芯片','半导体','算力'],
    'AI芯片/CPO': ['CPO','光通信','光模块'],
    'CPO/光模块': ['CPO','光通信','光模块'],
    '光模块': ['光模块','光通信'],
    'AI服务器/超节点': ['服务器','算力','AI服务器'],
    'AI算力': ['算力','AI服务器','数据中心'],
    'AI': ['人工智能','AI','大模型'],
    'AI应用': ['人工智能','AI应用','大模型'],
    'AI/鸿蒙': ['鸿蒙','华为概念','人工智能'],
    'AI/大模型': ['大模型','AI','人工智能'],
    'AI/互联网': ['互联网','AI','人工智能'],
    '半导体设备': ['半导体设备','半导体','专用设备'],
    '半导体全链': ['半导体','芯片'],
    '半导体硅片': ['硅片','半导体','半导体材料'],
    '先进封装CoWoS': ['先进封装','半导体','封测'],
    '光纤光缆': ['光纤光缆','光通信','通信设备'],
    '连接器/铜连接': ['连接器','铜连接','电子元件'],
    '电子铜箔': ['铜箔','电子元件','有色金属'],
    '液冷散热': ['液冷','散热','冷却'],
    '交换机/网络': ['交换机','通信设备','网络设备'],
    '电源/DrMOS': ['电源','半导体','DrMOS'],
    '数据中心/AIDC': ['数据中心','AIDC','算力'],
    '光刻胶': ['光刻胶','半导体材料','电子化学品'],
    '玻璃基板TGV': ['玻璃基板','TGV','电子元件'],
    '培育钻石/散热': ['培育钻石','金刚石','散热'],
    '超导/核聚变': ['超导','核聚变','电力设备'],
    '碳纤维': ['碳纤维','化工','新材料'],
    '6G/通信': ['6G','通信设备','通信'],
    '空间计算/物理AI': ['空间计算','物理AI','AI'],
    '消费电子/AI硬件': ['消费电子','AI硬件','电子'],
    '锂矿/盐湖提锂': ['锂矿','能源金属','盐湖'],
    '锂电池/电解液': ['锂电池','电解液','电池'],
    '光伏/太阳能': ['光伏','太阳能','HJT电池'],
    '风电': ['风电','风能'],
    '储能': ['储能','虚拟电厂'],
    '新能源汽车': ['新能源车','汽车整车'],
    '煤炭': ['煤炭','煤化工'],
    '黄金/贵金属': ['黄金','贵金属'],
    '铜铝有色': ['铜','铝','有色金属'],
    '化工': ['化工','化学制品'],
    '钢铁': ['钢铁','普钢'],
    '银行': ['银行','金融'],
    '券商': ['券商','证券'],
    '保险': ['保险'],
    '房地产开发': ['房地产','地产'],
    '白酒': ['白酒','酿酒'],
    '食品饮料': ['食品饮料','食品'],
    '医药/CRO': ['医药','CRO','创新药'],
    '创新药/CXO': ['创新药','CXO','新药','生物医药'],
    '电子布/玻璃纤维': ['电子布','玻璃纤维','低介电','玻纤','电子纱'],
    '医疗器械': ['医疗器械','医疗设备'],
    '算电协同': ['算电','电力','数据中心电源'],
    '电网设备/特高压': ['特高压','智能电网','电网设备','输变电'],
    '火电/电力运营': ['火电','电力','火力发电','热电'],
    '算力租赁/GPU云': ['算力租赁','GPU云','智算'],
    '稀土永磁': ['稀土永磁','永磁','小金属','稀有金属'],
    '钼/小金属': ['钼','小金属','有色金属','稀有金属'],
    '电子特气/工业气体': ['电子特气','工业气体','电子化学品','化工'],
    '半导体靶材': ['半导体靶材','半导体','靶材'],
    'AI应用/模型推理': ['AI智能体','人工智能','AI应用','大模型'],
    '核电/核能': ['核电','核能','电力','新能源'],
    '量子计算/量子科技': ['量子计算','量子科技','量子通信'],
    '卫星互联网/北斗': ['卫星互联网','北斗','低轨卫星','航天'],
    '数字经济': ['数字经济','数据要素','信息技术'],
    '全部赛道': ['上证指数','沪深300'],
    'HBM/先进封装': ['HBM','先进封装','半导体'],
}

def fetch_board_stocks(bcode, max_stocks=8):
    """Fetch top gainers from an EastMoney concept board. Returns list of 'code name'."""
    url = f'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz={max_stocks}&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:{bcode}&fields=f2,f3,f12,f14'
    try:
        req = Request(url, headers={'User-Agent': UA, 'Referer': 'https://quote.eastmoney.com/'})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8', errors='replace'))
        return [f'{s.get("f12","")} {s.get("f14","")}' for s in data.get('data',{}).get('diff',[])]
    except:
        return []

def fetch_top_gainers_all(max_stocks=8):
    """Fallback: fetch top gainers from ALL A-shares (no sector filter).
    Returns list of 'code name chg%'."""
    url = f'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz={max_stocks}&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f2,f3,f12,f14'
    try:
        req = Request(url, headers={'User-Agent': UA, 'Referer': 'https://quote.eastmoney.com/'})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8', errors='replace'))
        return [f'{s.get("f12","")} {s.get("f14","")}' for s in data.get('data',{}).get('diff',[])]
    except:
        return []

def fetch_board_codes_all():
    """Fetch EastMoney concept + industry boards (single request, max page size)."""
    all_boards = {}
    # Try concept boards (t:3) + industry boards (t:2) in one shot
    markets = ['m:90+t:3', 'm:90+t:2']
    for mkt in markets:
        url = f'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs={mkt}&fields=f2,f3,f12,f14'
        try:
            req = Request(url, headers={'User-Agent': UA, 'Referer': 'https://quote.eastmoney.com/'})
            with urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8', errors='replace'))
            for h in data.get('data', {}).get('diff', []):
                name = h.get('f14', '')
                if name not in all_boards:
                    all_boards[name] = h.get('f12', '')
        except:
            continue
    return all_boards

def find_board_code(sector_name, board_map):
    """Match our sector name to an EastMoney board code."""
    hints = SECTOR_BOARD_HINTS.get(sector_name, [sector_name])
    for hint in hints:
        # Exact match
        if hint in board_map:
            return board_map[hint]
        # Substring match
        for name, code in board_map.items():
            if hint in name or name in hint:
                return code
    # Last resort: check if any board name contains 2+ chars from sector
    for name, code in board_map.items():
        common = sum(1 for c in sector_name if c in name)
        if common >= 3 and len(name) > 1:
            return code
    return ''

def build_layout_from_events(events, existing_layout=None):
    """Generate layout cards from events.
    Metadata generated here, real-time stocks filled by fetch_data.py every 5 min.
    Existing stocks are preserved so they survive between API refresh cycles."""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.date()

    # Index existing layout by (date, title) to preserve stocks
    old_stocks = {}
    for lv in (existing_layout or []):
        key = (lv.get('d', ''), lv.get('e', ''))
        if lv.get('stocks'):
            old_stocks[key] = lv['stocks']

    layout = []
    seen = set()
    for ev in events:
        d_str = ev.get('d', '')
        m = re.search(r'(\d+)月(\d+)日', d_str)
        if m:
            ev_date = datetime(cst.year, int(m.group(1)), int(m.group(2))).date()
        else:
            # Handle 上旬/中旬/下旬
            m2 = re.search(r'(\d+)月(上旬|中旬|下旬)', d_str)
            if m2:
                mm = int(m2.group(1))
                label = m2.group(2)
                day = 5 if label == '上旬' else (15 if label == '中旬' else 25)
                ev_date = datetime(cst.year, mm, day).date()
            else:
                continue

        lkey = (d_str, ev.get('e', ''))
        if lkey in seen:
            continue
        seen.add(lkey)

        days_left = (ev_date - today).days
        lead = 7 if ev.get('big') else 5
        if days_left < lead:
            lead = max(1, days_left)

        # Preserve existing stocks if available
        stocks = old_stocks.get(lkey, [])

        layout.append({
            'd': d_str,
            'days': days_left,
            'lead': lead,
            'e': ev.get('e', ''),
            'icon': ev.get('icon', '📅'),
            's': ev.get('s', ''),
            'big': ev.get('big', 0),
            'stocks': stocks[:8] if stocks else [],
            'u': ev.get('u', '')
        })

    layout.sort(key=lambda x: (x['days'] < 0, x['days']))
    return layout

# ═══════════════════════════════════════════════════
# NBS 2026 Macro Calendar
# Based on NBS published annual release schedule
# ═══════════════════════════════════════════════════

MACRO_S = '宏观/全部'

def next_biz(y, m, day):
    d = datetime(y, m, min(day, cal.monthrange(y, m)[1]))
    while d.weekday() >= 5: d += timedelta(days=1)
    return d

def fmt_d(d): return f'{d.month}月{d.day}日'

def generate_macro(cst_date):
    """Generate NBS 2026 macro calendar + key recurring events.
    Returns events with all required fields: d/icon/e/s/big/desc/u"""
    year = cst_date.year
    events = []
    def add(m, d, t, icon='📊', big=1, desc='', s='宏观/全部'):
        import calendar as _cal
        dt = __import__('datetime').datetime(year, m, min(d, _cal.monthrange(year, m)[1]))
        while dt.weekday() >= 5: dt += __import__('datetime').timedelta(days=1)
        desc_val = desc if desc else t[:20]
        events.append({'d': f'{m}月{dt.day}日', 'icon': icon, 'e': t, 's': s, 'big': big, 'desc': desc_val})
    def biz_day(m, d):
        import calendar as _cal
        dt = __import__('datetime').datetime(year, m, min(d, _cal.monthrange(year, m)[1]))
        while dt.weekday() >= 5: dt += __import__('datetime').timedelta(days=1)
        return dt.day
    for m in range(1, 13):
        nm = 1 if m == 12 else m + 1
        add(nm, biz_day(nm, 1), f'{m}月官方PMI（制造业/非制造业）', '🔴', 1, '官方PMI发布')
        add(nm, biz_day(nm, 3), f'{m}月财新PMI', '📊', 1, '财新PMI发布')
        add(nm, biz_day(nm, 10), f'{m}月CPI/PPI', '🔴', 1, '通胀数据公布')
        add(nm, biz_day(nm, 13), f'{m}月进出口贸易数据', '📊', 1, '贸易数据公布')
        add(nm, biz_day(nm, 16), f'{m}月工业增加值/社零/固投', '📊', 1, '经济数据三合一')
        add(nm, biz_day(nm, 12), f'{m}月金融数据（M2/社融/新增贷款）', '🔴', 1, '金融数据公布')
        add(m, biz_day(m, 20), f'{m}月LPR报价', '📅', 1, 'LPR利率决定')
        add(m, biz_day(m, 15), f'{m}月MLF操作', '📅', 0, 'MLF操作')
    add(4, 17, 'Q1 GDP数据', '🔴', 1, '一季度GDP公布')
    add(7, 16, 'Q2 GDP数据 / 上半年国民经济运行', '🔴', 1, '上半年GDP公布')
    add(10, 19, 'Q3 GDP数据', '🔴', 1, '三季度GDP公布')
    for m, d in [(1,29),(3,19),(5,7),(6,18),(7,30),(9,17),(11,5),(12,17)]:
        add(m, biz_day(m, d), 'FOMC利率决议', '🔴', 1, '美联储利率决议')
    add(4, 30, 'A股年报/一季报披露截止日', '📊', 1, '年报一季报截止')
    add(8, 31, 'A股中报披露截止日', '📊', 1, '中报披露截止')
    add(10, 31, 'A股三季报披露截止日', '📊', 1, '三季报截止')
    add(3, 5, '全国两会开幕（政协）', '📅', 1, '两会开幕')
    add(3, 7, '全国两会（人大）', '📅', 1, '人大会议')
    add(6, 4, '台北Computex 2026', '🚀', 1, '台北电脑展')
    add(7, 10, '世界人工智能大会 WAIC 2026', '🚀', 1, 'WAIC大会')
    add(11, 11, '双11电商节', '📅', 0, '双11消费')
    from datetime import datetime, timedelta
    cst = datetime(year, cst_date.month, cst_date.day)
    future = []
    cutoff = cst + timedelta(days=90)
    for ev in events:
        parts = ev['d'].replace('月',' ').replace('日','').split()
        m2, d2 = int(parts[0]), int(parts[1])
        ev_year = year if m2 >= cst.month - 1 else year + 1
        try:
            ed = datetime(ev_year, m2, d2)
            if ed.date() >= cst_date and ed.date() <= cutoff.date():
                future.append(ev)
        except:
            pass
    print(f'Macro: {len(future)} events in next 90 days')
    return future

# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.date()

    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try: data = json.load(f)
            except: pass

    existing = data.get('events', [])

    # Separate: hand (has URL AND not macro) vs macro
    macro_keywords = ['PMI','CPI','PPI','GDP','MLF','LPR','FOMC','利率决议','进出口','工业增加值',
                      '社零','固投','金融数据','M2','社融','财报','年报','中报','季报','披露截止']

    hand_evs = []
    old_macro = []
    for e in existing:
        e_title = e.get('e','')
        e_sector = e.get('s','')
        # Hand: has real URL AND NOT macro
        has_url = bool(e.get('u','').strip())
        is_macro = any(kw in e_title for kw in macro_keywords) or e_sector == '宏观/全部'
        if has_url and not is_macro:
            hand_evs.append(e)
        else:
            old_macro.append(e)

    hand_keys = {(e['d'], e['e']) for e in hand_evs}

    # AI events: non-macro, non-hand (from sentinel_ai newEvents)
    macro_keys_used = {(e['d'], e['e']) for e in old_macro}
    ai_evs = [e for e in existing
        if (e['d'], e['e']) not in hand_keys
        and (e['d'], e['e']) not in macro_keys_used]

    print(f'Existing: {len(hand_evs)} hand + {len(old_macro)} old-macro + {len(ai_evs)} AI')

    # Generate fresh macro
    macro = generate_macro(today)
    print(f'Fresh macro: {len(macro)} events')

    # Merge: hand > fresh-macro > AI > other
    merged = list(hand_evs)  # Forever

    for ev in macro:
        k = (ev['d'], ev['e'])
        if k not in hand_keys:
            merged.append(ev)
    macro_keys = {(e['d'], e['e']) for e in macro}

    all_keys = {(e['d'], e['e']) for e in merged}
    for ev in ai_evs:
        k = (ev.get('d',''), ev.get('e',''))
        if k in all_keys:
            continue
        merged.append(ev)

    # ── URL enrichment: generate links for events missing them ──
    # ── Field normalization: ensure all events have icon/big/desc ──
    for ev in merged:
        if not ev.get('u','').strip():
            title = ev.get('e','')
            sector = ev.get('s','')
            search_term = sector.split('/')[0].strip() if sector else title[:8]
            if search_term:
                ev['u'] = 'https://so.eastmoney.com/news/s?keyword=' + quote(search_term)
            else:
                ev['u'] = 'https://data.eastmoney.com/'
        # Ensure standard fields: icon/big/desc
        if not ev.get('icon'):
            ev['icon'] = '📅'
        if 'big' not in ev:
            # Infer: macro/critical events get big=1
            e_title = ev.get('e','')
            s_name = ev.get('s','')
            ev['big'] = 1 if any(kw in e_title for kw in ['FOMC','GDP','PMI','CPI','LPR','MLF','决议','财报','数据','大会','展会','停产','涨价','法规','年报','中报','季报','两会']) else 0
            if s_name == '宏观/全部':
                ev['big'] = 1
        if not ev.get('desc'):
            ev['desc'] = ev.get('e','')[:20]

    # Sort by date
    def parse_date(ev):
        m = re.search(r'(\d+)月(\d+)日', ev.get('d',''))
        if m: return datetime(cst.year, int(m.group(1)), int(m.group(2)))
        m = re.search(r'(\d+)月上旬', ev.get('d',''))
        if m: return datetime(cst.year, int(m.group(1)), 5)
        m = re.search(r'(\d+)月中旬', ev.get('d',''))
        if m: return datetime(cst.year, int(m.group(1)), 15)
        m = re.search(r'(\d+)月下旬', ev.get('d',''))
        if m: return datetime(cst.year, int(m.group(1)), 25)
        return datetime(2099,1,1)

    merged.sort(key=parse_date)

    # Expire past events older than 30 days (except hand-curated with links)
    cutoff = (today - timedelta(days=30))
    merged = [e for e in merged
              if parse_date(e).date() >= cutoff
              or (e.get('u','') and parse_date(e).date() >= cutoff - timedelta(days=60))]

    # Cap at 100: trim oldest non-hand past events if needed
    if len(merged) > 100:
        future = [e for e in merged if parse_date(e).date() >= today]
        past = [e for e in merged if parse_date(e).date() < today]
        past_hand = [e for e in past if e.get('u','').strip()]
        past_other = [e for e in past if not e.get('u','').strip()]
        past_other = past_other[-max(0, 30 - len(past_hand)):]
        merged = past_hand + past_other + future
        if len(merged) > 100:
            merged = merged[-100:]

    data['events'] = merged

    # ── Auto-generate layout cards from events ──
    # Every pre-positionable event → layout card with real-time stocks
    print('Building layout from events...')
    data['layout'] = build_layout_from_events(merged, data.get('layout'))
    layout_with_stocks = sum(1 for lv in data['layout'] if lv.get('stocks'))
    layout_count = len(data['layout'])
    print(f'  Layout: {layout_count} cards, {layout_with_stocks} with stocks')

    data['_eventsMeta'] = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'total': len(merged),
        'hand': len(hand_evs),
        'macro': len(macro),
        'ai': len(ai_evs),
        'schedule': 'daily at 10:00 CST',
        'source': 'NBS 2026 schedule + AI sentinel news + hand-curated'
    }

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    future_count = sum(1 for e in merged if parse_date(e).date() >= today)
    past_count = len(merged) - future_count
    print(f'Done: {len(merged)} total ({future_count} upcoming + {past_count} past)')
    print(f'  Hand:{len(hand_evs)} | Macro:{len(macro)} | AI:{len(ai_evs)}')
    # Show upcoming that are NOT macro (sector-specific)
    sector_evs = [e for e in merged if parse_date(e).date() >= today and e.get('s') != MACRO_S]
    if sector_evs:
        print(f'  Sector-specific upcoming: {len(sector_evs)}')
        for ev in sector_evs[:5]:
            try:
                d_val = ev['d']; e_val = ev['e']
                print(f'    {d_val} {e_val}')
            except:
                d_val = ev['d']
                print(f'    {d_val} [encoding issue]')


if __name__ == '__main__':
    main()
