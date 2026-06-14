#!/usr/bin/env python3
"""
Real-time event calendar generator.
Two sources:
  1. NBS Macro Calendar — auto-generated from 统计局 2026 release schedule
     (dates follow fixed monthly patterns, auto-adjust for weekends)
  2. AI Sentinel newEvents — already reads real market news, runs 4x/day
Runs every 5 min via live-update workflow. Outputs merged events to data.json.
"""
import json, os
from datetime import datetime, timezone, timedelta

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

# ── NBS 2026 Macro Data Release Schedule ──
# Patterns (统计局每年初公布全年日程):
#   PMI制造业/非制造业: 每月最后一天 (遇周末顺延至下周一)
#   CPI/PPI: 每月9日左右 (遇周末顺延)
#   进出口贸易: 每月7日左右
#   工业增加值/社零/固投: 每月15日左右
#   GDP: 1/4/7/10月15日左右
#   规模以上工业企业利润: 每月27日
#   70城房价: 每月15-16日
#   M2/社融/新增贷款: 每月10-15日
#   LPR: 每月20日 (遇周末顺延)
#   外汇储备: 每月7日
#   MLF操作: 每月15日 (遇周末顺延)
#   US 非农+失业率: 每月第一个周五
#   US CPI: 每月10-14日
#   FOMC: 每6周, 2026年剩余: 6/17, 7/29, 9/16, 11/4, 12/16

# Our 35 sector mapping for macro events
MACRO_SECTOR = '宏观/全部'
NBS_ICONS = {
    'pmi': '📊', 'cpi': '💰', 'trade': '🚢', 'industrial': '🏭',
    'gdp': '📈', 'profits': '💼', 'housing': '🏠', 'money': '💳',
    'lpr': '🏦', 'fx': '💱', 'mlf': '🏦', 'nfp': '🇺🇸', 'us_cpi': '🇺🇸',
    'fomc': '🏛️', 'pboc': '🏦', 'soc': '🏭',
}

def next_business_day(year, month, target_day):
    """Target day of month, if weekend → next Monday. Returns (year, month, day)."""
    d = datetime(year, month, 1) + timedelta(days=target_day - 1)
    # If the target_day exceeds the month, clamp to last day
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    if target_day > max_day:
        d = datetime(year, month, max_day)
    while d.weekday() >= 5:  # Sat=5, Sun=6 → shift to Monday
        d += timedelta(days=1)
    return d

def last_day_of_month(year, month):
    """Last day of month, if weekend → previous Friday."""
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    d = datetime(year, month, max_day)
    # NBS rule: PMI released on last day, if weekend → next business day (Monday)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    # If pushed into next month, pull back to Friday
    if d.month != month:
        d = datetime(year, month, max_day)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d

def first_friday(year, month):
    """First Friday of the month."""
    d = datetime(year, month, 1)
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    return d

def third_friday(year, month):
    """Third Friday of the month."""
    d = datetime(year, month, 15)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d

def fmt_date(d):
    return f'{d.month}月{d.day}日'

def fmt_short(d):
    return f'{d.month}/{d.day}'

def generate_macro_calendar():
    """Generate macro data release schedule for current month + next 3 months."""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.date()
    events = []

    # Generate for 4 months: current month through +3
    for offset in range(4):
        m = cst.month + offset
        y = cst.year
        if m > 12:
            m -= 12
            y += 1

        # PMI — last day of month
        pmi_date = last_day_of_month(y, m)
        events.append({
            'd': fmt_date(pmi_date), 'icon': NBS_ICONS['pmi'],
            'e': f'{m}月中国制造业/非制造业PMI发布', 's': MACRO_SECTOR,
            'big': 1 if pmi_date.date() >= today else 0,
            'desc': '验证制造业景气度及新订单/出口订单趋势，影响周期股风格'
        })

        # CPI/PPI — around 9th
        cpi_date = next_business_day(y, m, 9)
        events.append({
            'd': fmt_date(cpi_date), 'icon': NBS_ICONS['cpi'],
            'e': f'{m}月CPI/PPI数据发布', 's': MACRO_SECTOR,
            'big': 1 if cpi_date.date() >= today else 0,
            'desc': '通胀数据影响货币政策预期，PPI影响上游资源品定价'
        })

        # Trade data — around 7th
        trade_date = next_business_day(y, m, 7)
        events.append({
            'd': fmt_date(trade_date), 'icon': NBS_ICONS['trade'],
            'e': f'{m}月进出口贸易数据发布', 's': MACRO_SECTOR,
            'big': 0,
            'desc': '出口增速影响制造业/港口航运/电子产业链预期'
        })

        # Industrial production + retail + FAI — around 15th
        ind_date = next_business_day(y, m, 15)
        events.append({
            'd': fmt_date(ind_date), 'icon': NBS_ICONS['industrial'],
            'e': f'{m}月工业增加值/社零/固投发布', 's': MACRO_SECTOR,
            'big': 1 if ind_date.date() >= today else 0,
            'desc': '验证经济动能——工业(制造业)/消费/投资三驾马车'
        })

        # M2/Money — around 11th
        money_date = next_business_day(y, m, 11)
        events.append({
            'd': fmt_date(money_date), 'icon': NBS_ICONS['money'],
            'e': f'{m}月M2/社融/新增贷款发布', 's': MACRO_SECTOR,
            'big': 0,
            'desc': '流动性指标，社融结构决定成长/价值风格切换'
        })

        # LPR — 20th
        lpr_date = next_business_day(y, m, 20)
        events.append({
            'd': fmt_date(lpr_date), 'icon': NBS_ICONS['lpr'],
            'e': f'{m}月LPR报价(1年/5年)', 's': MACRO_SECTOR,
            'big': 1 if lpr_date.date() >= today else 0,
            'desc': '房贷利率基准，降息=利好地产+成长股估值'
        })

        # Industrial profits — around 27th
        profit_date = next_business_day(y, m, 27)
        events.append({
            'd': fmt_date(profit_date), 'icon': NBS_ICONS['profits'],
            'e': f'{m-1 if m>1 else 12}月规上工业企业利润发布', 's': MACRO_SECTOR,
            'big': 0,
            'desc': '上市公司业绩先行指标，验证涨价传导至利润端'
        })

        # 70-city housing — around 16th
        house_date = next_business_day(y, m, 16)
        events.append({
            'd': fmt_date(house_date), 'icon': NBS_ICONS['housing'],
            'e': f'{m}月70城房价指数发布', 's': MACRO_SECTOR,
            'big': 0,
            'desc': '地产链景气温度计，影响建材/家电/银行板块'
        })

        # FX reserves — around 7th
        fx_date = next_business_day(y, m, 7)
        events.append({
            'd': fmt_date(fx_date), 'icon': NBS_ICONS['fx'],
            'e': f'{m}月外汇储备数据发布', 's': MACRO_SECTOR,
            'big': 0,
            'desc': '人民币汇率预期参考，影响外资流入意愿'
        })

        # MLF — 15th
        mlf_date = next_business_day(y, m, 15)
        events.append({
            'd': fmt_date(mlf_date), 'icon': NBS_ICONS['mlf'],
            'e': f'{m}月MLF操作利率及规模', 's': MACRO_SECTOR,
            'big': 1 if mlf_date.date() >= today else 0,
            'desc': '央行中期利率指引，降息信号=利好A股整体估值'
        })

    # ── US events (market-moving for A-shares too) ──
    for offset in range(4):
        m = cst.month + offset
        y = cst.year
        if m > 12:
            m -= 12
            y += 1

        # US Non-farm payrolls — first Friday
        nfp = first_friday(y, m)
        events.append({
            'd': fmt_date(nfp), 'icon': NBS_ICONS['nfp'],
            'e': f'美国{m}月非农就业+失业率', 's': '宏观/全部',
            'big': 1 if nfp.date() >= today else 0,
            'desc': '全球最重要月度经济数据，影响美联储降息预期及全球风险偏好'
        })

        # US CPI — around 12th
        us_cpi = next_business_day(y, m, 12)
        events.append({
            'd': fmt_date(us_cpi), 'icon': NBS_ICONS['us_cpi'],
            'e': f'美国{m}月CPI数据发布', 's': '宏观/全部',
            'big': 1 if us_cpi.date() >= today else 0,
            'desc': '通胀数据→降息预期→美债利率→A股科技成长股估值'
        })

    # ── FOMC 2026 remaining meetings ──
    fomc_dates = [
        (2026, 6, 17, '6月FOMC利率决议+点阵图'),
        (2026, 7, 29, '7月FOMC利率决议'),
        (2026, 9, 16, '9月FOMC利率决议+经济预测'),
        (2026, 11, 4, '11月FOMC利率决议'),
        (2026, 12, 16, '12月FOMC利率决议+点阵图'),
    ]
    for y, m, d, title in fomc_dates:
        fomc_d = datetime(y, m, d)
        events.append({
            'd': fmt_date(fomc_d), 'icon': NBS_ICONS['fomc'],
            'e': title, 's': '宏观/全部',
            'big': 1 if fomc_d.date() >= today else 0,
            'desc': '全球资产定价锚——利率决议+点阵图影响全年降息路径'
        })

    # ── Other recurring catalysts ──
    for offset in range(4):
        m = cst.month + offset
        y = cst.year
        if m > 12:
            m -= 12
            y += 1

        # 股指期货/期权交割 — 3rd Friday
        expiry = third_friday(y, m)
        events.append({
            'd': fmt_date(expiry), 'icon': '📅',
            'e': f'{m}月股指期货/期权交割日', 's': MACRO_SECTOR,
            'big': 0,
            'desc': '交割日市场波动可能加大，注意仓位管理'
        })

        # 章源钨业长单报价 — 每月1日和15日 (if these dates exist)
        for day, label in [(1, '上半月'), (15, '下半月')]:
            import calendar
            max_d = calendar.monthrange(y, m)[1]
            if day <= max_d:
                quote_d = next_business_day(y, m, day)
                if quote_d.month == m:  # Only if still in same month
                    events.append({
                        'd': fmt_date(quote_d), 'icon': '💰',
                        'e': f'章源钨业{m}月{label}长单报价', 's': '钨/稀土',
                        'big': 1 if quote_d.date() >= today else 0,
                        'desc': '每半月钨精矿定价催化，观察涨幅趋势'
                    })

    # ── Deduplicate by date+title ──
    seen = set()
    deduped = []
    for ev in events:
        key = (ev['d'], ev['e'])
        if key not in seen:
            seen.add(key)
            deduped.append(ev)

    # Sort by date
    def parse_date(ev):
        parts = ev['d'].replace('月', ' ').replace('日', '').split()
        if len(parts) >= 2:
            try:
                return (int(parts[0]), int(parts[1]))
            except:
                pass
        return (99, 99)

    deduped.sort(key=parse_date)
    return deduped


def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    macro_events = generate_macro_calendar()
    print(f'Generated {len(macro_events)} macro events')

    # Load existing data
    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                pass

    existing_events = data.get('events', [])

    # Separate existing events into types
    hand_events = []   # Manual with URL — always keep
    auto_macro = []    # Old auto-generated macro — replace
    ai_events = []     # AI-generated — keep
    other_events = []  # Everything else

    for ev in existing_events:
        # Hand-curated: has URL
        if ev.get('u') and ev['u'].strip():
            hand_events.append(ev)
            continue
        # AI-generated: has desc that's not a standard macro description
        desc = ev.get('desc', '')
        sector = ev.get('s', '')
        title = ev.get('e', '')

        # Macro events have MACRO_SECTOR or standard NBS patterns
        is_macro = (
            sector == MACRO_SECTOR
            or any(kw in title for kw in ['PMI', 'CPI', 'PPI', '进出口', '工业增加值',
                '社零', '固投', 'M2', '社融', 'LPR', '规上工业', '70城', '外汇储备',
                'MLF', 'FOMC', '非农', '股指期货交割', '章源钨业长单'])
        )
        if is_macro:
            auto_macro.append(ev)
        else:
            # Non-macro event without URL — likely AI-generated
            ai_events.append(ev)

    # Build merged event list
    # 1. Hand-curated events (with URLs) — top priority
    merged = list(hand_events)

    # 2. Fresh macro calendar — replaces old auto_macro
    merged.extend(macro_events)

    # 3. AI-generated events — deduplicate against hand + macro
    hand_keys = {(e['d'], e['e']) for e in hand_events}
    macro_keys = {(e['d'], e['e']) for e in macro_events}
    for ev in ai_events:
        key = (ev.get('d', ''), ev.get('e', ''))
        if key not in hand_keys and key not in macro_keys:
            merged.append(ev)

    # 4. Any remaining other events
    for ev in other_events:
        key = (ev.get('d', ''), ev.get('e', ''))
        if key not in hand_keys and key not in macro_keys:
            merged.append(ev)

    # Sort by date, remove past events older than 30 days
    today = cst.date()
    cutoff = today - timedelta(days=30)

    def parse_date_ev(ev):
        import re
        m = re.search(r'(\d+)月(\d+)日', ev.get('d', ''))
        if m:
            return datetime(cst.year, int(m.group(1)), int(m.group(2))).date()
        m = re.search(r'(\d+)月上旬', ev.get('d', ''))
        if m:
            return datetime(cst.year, int(m.group(1)), 5).date()
        m = re.search(r'(\d+)月中旬', ev.get('d', ''))
        if m:
            return datetime(cst.year, int(m.group(1)), 15).date()
        m = re.search(r'(\d+)月下旬', ev.get('d', ''))
        if m:
            return datetime(cst.year, int(m.group(1)), 25).date()
        return today

    # Keep: future events + past events within 30 days
    filtered = []
    for ev in merged:
        d = parse_date_ev(ev)
        if d >= cutoff:
            filtered.append(ev)

    # Sort by date
    filtered.sort(key=parse_date_ev)

    # Cap at 80 events
    if len(filtered) > 80:
        filtered = filtered[:80]

    # Write back
    data['events'] = filtered
    data['_eventsMeta'] = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'macro': len(macro_events),
        'hand': len(hand_events),
        'ai': len(ai_events),
        'total': len(filtered),
        'source': 'NBS calendar + AI sentinel + hand-curated'
    }

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Print summary
    future_ev = [e for e in filtered if parse_date_ev(e) >= today]
    print(f'Events: {len(filtered)} total ({len(future_ev)} upcoming, {len(filtered)-len(future_ev)} past 30d)')
    print(f'  Macro: {len(macro_events)} | Hand: {len(hand_events)} | AI: {len(ai_events)}')
    if future_ev:
        print('Next 3 upcoming:')
        for ev in future_ev[:3]:
            try:
                print(f'  {ev["d"]} | {ev["icon"]} {ev["e"]}')
            except UnicodeEncodeError:
                print(f'  {ev["d"]} | {ev["e"]}')


if __name__ == '__main__':
    main()
