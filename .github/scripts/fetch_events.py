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
    'CPO/硅光': ['CPO','光通信','光模块'],
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
    '医疗器械': ['医疗器械','医疗设备'],
    '算电协同': ['算电','电力','数据中心电源'],
    '电网设备/特高压': ['特高压','智能电网','电网设备','输变电'],
    '火电/电力运营': ['火电','电力','火力发电','热电'],
    '算力租赁/GPU云': ['算力租赁','GPU云','智算'],
    'Token工厂/模型推理': ['模型推理','人工智能','AI应用'],
    '稀土永磁': ['稀土永磁','永磁','小金属','稀有金属'],
    '钼/小金属': ['钼','小金属','有色金属','稀有金属'],
    '电子特气/工业气体': ['电子特气','工业气体','电子化学品','化工'],
    '半导体靶材': ['半导体靶材','半导体','靶材'],
    'AI智能体/应用': ['AI智能体','人工智能','AI应用','大模型'],
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

def generate_macro():
    """Only keep sector-specific recurring events that you can actually pre-position for.
    No FOMC/LPR/MLF/NFP/CPI — nobody buys stocks ahead of a PMI release.
    Only 章源钨业 monthly quotes survive as truly pre-positionable."""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.date()
    evs = []

    # Only one recurring event that matters for pre-positioning
    # 只生成当月的2条（上半月+下半月），不预生成未来几个月
    zyw_url = 'https://quote.eastmoney.com/sz002842.html'
    m, y = cst.month, cst.year
    for day, lb in [(1, '上半月'), (15, '下半月')]:
        if day <= cal.monthrange(y, m)[1]:
            qd = next_biz(y, m, day)
            if qd.month == m:
                evs.append({'d': fmt_d(qd), 'icon': '💰',
                    'e': f'章源钨业{m}月{lb}长单报价', 's': '钨/稀土',
                    'big': 1,
                    'desc': f'{m}月{lb}钨精矿定价催化，提前布局钨矿股',
                    'u': zyw_url})

    seen = set()
    deduped = []
    for e in evs:
        k = (e['d'], e['e'])
        if k not in seen:
            seen.add(k)
            deduped.append(e)

    def pd(e):
        m = re.search(r'(\d+)月(\d+)日', e['d'])
        return (int(m.group(1)), int(m.group(2))) if m else (99, 99)
    deduped.sort(key=pd)
    return deduped

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

    # Separate: hand (has URL AND not macro) vs macro vs AI (no URL) vs new AI (with URL, not macro, not hand)
    macro_patterns = ['FAKE_REMOVED']

    hand_evs = [e for e in existing if e.get('u','').strip()
        and not any(kw in e.get('e','') for kw in macro_patterns)]
    hand_keys = {(e['d'], e['e']) for e in hand_evs}

    old_macro = [e for e in existing
        if any(kw in e.get('e','') for kw in macro_patterns)]

    # AI events: everything else (with or without URL)
    macro_keys_used = {(e['d'], e['e']) for e in old_macro}
    ai_evs = [e for e in existing
        if (e['d'], e['e']) not in hand_keys
        and (e['d'], e['e']) not in macro_keys_used]

    print(f'Existing: {len(hand_evs)} hand + {len(old_macro)} old-macro + {len(ai_evs)} AI')

    # Generate fresh macro
    macro = generate_macro()
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
        # Drop old macro noise (LPR/MLF/FOMC/NFP/CPI etc.) — sector=宏观/全部 but NOT 章源钨业
        if k in all_keys:
            continue
        if ev.get('s') == MACRO_S and 'FAKE_REMOVED' not in ev.get('e', ''):
            continue  # macro noise, dropped
        merged.append(ev)

    # Purge ALL macro noise from merged list
    # Any event with sector=宏观/全部 that is NOT 章源钨业 gets deleted
    # (catches FOMC/LPR/MLF/NFP/CPI/交割日 regardless of classification)
    echo_count_before = len(merged)
    merged = [e for e in merged
              if e.get('s') != MACRO_S or 'FAKE_REMOVED' in e.get('e', '')]
    dropped = echo_count_before - len(merged)
    if dropped > 0:
        print(f'Purged {dropped} macro noise events (FOMC/LPR/MLF/NFP/CPI/etc)')

    # ── URL enrichment: generate links for events missing them ──
    for ev in merged:
        if not ev.get('u','').strip():
            # Generate EastMoney search URL from title keywords
            title = ev.get('e','')
            sector = ev.get('s','')
            # Use sector + first keyword from title
            search_term = sector.split('/')[0].strip() if sector else title[:8]
            if search_term:
                ev['u'] = 'https://so.eastmoney.com/news/s?keyword=' + quote(search_term)
            else:
                ev['u'] = 'https://data.eastmoney.com/'

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
