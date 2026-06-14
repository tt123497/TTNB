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
# NBS 2026 Macro Calendar
# Based on NBS published annual release schedule
# ═══════════════════════════════════════════════════

MACRO_S = '宏观/全部'

def next_biz(y, m, day):
    d = datetime(y, m, min(day, cal.monthrange(y, m)[1]))
    while d.weekday() >= 5: d += timedelta(days=1)
    return d

def last_biz(y, m):
    d = datetime(y, m, cal.monthrange(y, m)[1])
    while d.weekday() >= 5: d += timedelta(days=1)
    if d.month != m:
        d = datetime(y, m, cal.monthrange(y, m)[1])
        while d.weekday() >= 5: d -= timedelta(days=1)
    return d

def first_fri(y, m):
    d = datetime(y, m, 1)
    while d.weekday() != 4: d += timedelta(days=1)
    return d

def third_fri(y, m):
    d = datetime(y, m, 15)
    while d.weekday() != 4: d += timedelta(days=1)
    return d

def fmt_d(d): return f'{d.month}月{d.day}日'

def generate_macro():
    """Only the macro events that actually matter for pre-positioning.
    Dropped: PMI, CPI/PPI, trade, industrial/retail/FAI, M2/credit,
     industrial profits, 70-city housing, FX reserves — all background noise,
     nobody pre-positions for a PMI release."""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.date()
    evs = []

    # ── Only 5 macro events that matter for layout ──

    # 1. FOMC — global asset pricing anchor
    fomc_url = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
    for y,m,d,t in [
        (2026,6,17,'6月FOMC+点阵图'),(2026,7,29,'7月FOMC'),
        (2026,9,16,'9月FOMC'),(2026,11,4,'11月FOMC'),
        (2026,12,16,'12月FOMC+点阵图')]:
        fd = datetime(y,m,d)
        evs.append({'d':fmt_d(fd),'icon':'🏛️','e':t,'s':MACRO_S,'big':1,
            'desc':'全球资产定价锚——利率决议+点阵图决定全年降息路径',
            'u':fomc_url})

    # 2. LPR — mortgage rate benchmark (monthly)
    lpr_url = 'http://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html'
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        lpr = next_biz(y, m, 20)
        evs.append({'d':fmt_d(lpr),'icon':'🏦','e':f'{m}月LPR报价','s':MACRO_S,
            'big':1,'desc':'房贷利率基准，降息=直接利好地产+银行+成长股估值扩张',
            'u':lpr_url})

    # 3. MLF — PBOC medium-term rate signal (monthly)
    mlf_url = 'http://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125428/index.html'
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        mlf = next_biz(y, m, 15)
        evs.append({'d':fmt_d(mlf),'icon':'🏦','e':f'{m}月MLF操作','s':MACRO_S,
            'big':1,'desc':'央行中期利率指引，降息信号=政策转向宽松，利好A股整体估值',
            'u':mlf_url})

    # 4. US Non-farm — global risk appetite (monthly)
    nfp_url = 'https://www.bls.gov/news.release/empsit.nr0.htm'
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        nfp = first_fri(y, m)
        evs.append({'d':fmt_d(nfp),'icon':'🇺🇸','e':f'{m}月美国非农就业','s':MACRO_S,
            'big':1,'desc':'全球最重要月度数据，影响美联储降息预期→美债利率→A股科技成长风格',
            'u':nfp_url})

    # 5. US CPI — inflation → rate cut expectation (monthly)
    cpi_url = 'https://www.bls.gov/news.release/cpi.nr0.htm'
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        us_cpi = next_biz(y, m, 12)
        evs.append({'d':fmt_d(us_cpi),'icon':'🇺🇸','e':f'{m}月美国CPI','s':MACRO_S,
            'big':1,'desc':'通胀数据→降息预期→美债利率→科技股估值',
            'u':cpi_url})

    # ── Recurring sector-specific events (not macro noise) ──

    # 股指期货交割 — risk management, useful to know
    ex_url = 'http://www.cffex.com.cn/jysj/yysj/'
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        ex = third_fri(y, m)
        evs.append({'d':fmt_d(ex),'icon':'📅','e':f'{m}月股指期货交割日','s':MACRO_S,
            'big':0,'desc':'交割日市场波动可能加大，注意仓位管理',
            'u':ex_url})

    # 章源钨业长单报价 — real sector catalyst
    zyw_url = 'https://quote.eastmoney.com/sz002842.html'
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        for day, lb in [(1,'上'),(15,'下')]:
            if day <= cal.monthrange(y,m)[1]:
                qd = next_biz(y, m, day)
                if qd.month == m:
                    evs.append({'d':fmt_d(qd),'icon':'💰',
                        'e':f'章源钨业{m}月{lb}半月长单报价','s':'钨/稀土',
                        'big':1,'desc':'每半月钨精矿定价催化',
                        'u':zyw_url})

    seen = set(); deduped = []
    for e in evs:
        k = (e['d'],e['e'])
        if k not in seen: seen.add(k); deduped.append(e)
    def pd(e):
        m=re.search(r'(\d+)月(\d+)日',e['d'])
        return (int(m.group(1)),int(m.group(2))) if m else (99,99)
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
    macro_patterns = ['FOMC','LPR报价','MLF操作','美国非农','美国CPI','股指期货交割','章源钨业长单']

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
        if k not in all_keys:
            merged.append(ev)

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

    # Cap at 100: trim oldest non-hand past events if needed
    if len(merged) > 100:
        future = [e for e in merged if parse_date(e).date() >= today]
        past = [e for e in merged if parse_date(e).date() < today]
        # Keep hand-curated past forever, trim others
        past_hand = [e for e in past if e.get('u','').strip()]
        past_other = [e for e in past if not e.get('u','').strip()]
        past_other = past_other[-max(0, 30 - len(past_hand)):]
        merged = past_hand + past_other + future
        if len(merged) > 100:
            merged = merged[-100:]

    data['events'] = merged
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
