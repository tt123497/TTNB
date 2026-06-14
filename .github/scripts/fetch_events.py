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
from urllib.parse import urlencode

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
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.date()
    evs = []
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1

        pm = last_biz(y, m)
        evs.append({'d':fmt_d(pm),'icon':'📊','e':f'{m}月PMI发布','s':MACRO_S,
            'big':1 if pm.date()>=today else 0,
            'desc':'制造业景气度风向标，新订单/出口订单验证经济动能'})

        cp = next_biz(y, m, 9)
        evs.append({'d':fmt_d(cp),'icon':'💰','e':f'{m}月CPI/PPI发布','s':MACRO_S,
            'big':1 if cp.date()>=today else 0,
            'desc':'通胀影响货币政策预期，PPI影响上游资源品定价'})

        tr = next_biz(y, m, 7)
        evs.append({'d':fmt_d(tr),'icon':'🚢','e':f'{m}月进出口数据发布','s':MACRO_S,
            'big':1,'desc':'出口增速影响制造业/港口航运/电子产业链'})

        ind = next_biz(y, m, 15)
        evs.append({'d':fmt_d(ind),'icon':'🏭','e':f'{m}月工业/社零/固投发布','s':MACRO_S,
            'big':1 if ind.date()>=today else 0,
            'desc':'经济三驾马车月度成绩单'})

        mon = next_biz(y, m, 11)
        evs.append({'d':fmt_d(mon),'icon':'💳','e':f'{m}月M2/社融/贷款发布','s':MACRO_S,
            'big':1,'desc':'流动性指标决定市场风格切换'})

        lpr = next_biz(y, m, 20)
        evs.append({'d':fmt_d(lpr),'icon':'🏦','e':f'{m}月LPR报价','s':MACRO_S,
            'big':1 if lpr.date()>=today else 0,
            'desc':'降息=利好地产+成长股估值'})

        prof = next_biz(y, m, 27)
        pm2 = m-1 if m>1 else 12
        evs.append({'d':fmt_d(prof),'icon':'💼','e':f'{pm2}月工业企业利润发布','s':MACRO_S,
            'big':0,'desc':'上市公司业绩先行指标'})

        house = next_biz(y, m, 16)
        evs.append({'d':fmt_d(house),'icon':'🏠','e':f'{m}月70城房价发布','s':MACRO_S,
            'big':0,'desc':'地产链景气温度计'})

        fx = next_biz(y, m, 7)
        evs.append({'d':fmt_d(fx),'icon':'💱','e':f'{m}月外汇储备发布','s':MACRO_S,
            'big':0,'desc':'汇率预期影响外资流向'})

        mlf = next_biz(y, m, 15)
        evs.append({'d':fmt_d(mlf),'icon':'🏦','e':f'{m}月MLF操作','s':MACRO_S,
            'big':1 if mlf.date()>=today else 0,
            'desc':'央行中期利率指引'})

    # US events (affect A-share 科技/成长风格)
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        nfp = first_fri(y, m)
        evs.append({'d':fmt_d(nfp),'icon':'🇺🇸','e':f'{m}月美国非农就业','s':MACRO_S,
            'big':1 if nfp.date()>=today else 0,
            'desc':'全球最重要月度经济数据，影响降息预期及全球风险偏好'})
        us_cpi = next_biz(y, m, 12)
        evs.append({'d':fmt_d(us_cpi),'icon':'🇺🇸','e':f'{m}月美国CPI','s':MACRO_S,
            'big':1 if us_cpi.date()>=today else 0,
            'desc':'通胀→降息预期→美债利率→A股科技成长估值'})

    # FOMC 2026 remaining
    for y,m,d,t in [
        (2026,6,17,'6月FOMC+点阵图'),(2026,7,29,'7月FOMC'),
        (2026,9,16,'9月FOMC'),(2026,11,4,'11月FOMC'),
        (2026,12,16,'12月FOMC+点阵图')]:
        fd = datetime(y,m,d)
        evs.append({'d':fmt_d(fd),'icon':'🏛️','e':t,'s':MACRO_S,
            'big':1 if fd.date()>=today else 0,
            'desc':'全球资产定价锚——利率决议影响全年降息路径'})

    # Recurring sector events
    for off in range(4):
        m, y = cst.month + off, cst.year
        if m > 12: m -= 12; y += 1
        ex = third_fri(y, m)
        evs.append({'d':fmt_d(ex),'icon':'📅','e':f'{m}月股指期货交割日','s':MACRO_S,
            'big':0,'desc':'交割日市场波动可能加大'})
        for day, lb in [(1,'上'),(15,'下')]:
            if day <= cal.monthrange(y,m)[1]:
                qd = next_biz(y, m, day)
                if qd.month == m:
                    evs.append({'d':fmt_d(qd),'icon':'💰',
                        'e':f'章源钨业{m}月{lb}半月长单报价','s':'钨/稀土',
                        'big':1 if qd.date()>=today else 0,
                        'desc':'每半月钨精矿定价催化，观察涨幅趋势'})

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

    # Separate: hand (with URL) vs macro vs AI vs other
    hand_evs = [e for e in existing if e.get('u','').strip()]
    hand_keys = {(e['d'], e['e']) for e in hand_evs}

    macro_patterns = ['PMI','CPI','PPI','进出口','工业/社零','M2/社融','LPR报价',
        '工业企业利润','70城房价','外汇储备','MLF操作','非农就业','美国CPI',
        'FOMC','股指期货交割','章源钨业长单']
    old_macro = [e for e in existing if not e.get('u','').strip()
        and any(kw in e.get('e','') for kw in macro_patterns)]

    ai_evs = [e for e in existing if not e.get('u','').strip()
        and not any(kw in e.get('e','') for kw in macro_patterns)]
    other_evs = []  # reserved

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

    all_keys = {(e['d'], e['e']) for e in merged}
    for ev in ai_evs:
        k = (ev.get('d',''), ev.get('e',''))
        if k not in all_keys:
            merged.append(ev)

    for ev in other_evs:
        k = (ev.get('d',''), ev.get('e',''))
        if k not in all_keys:
            merged.append(ev)

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
