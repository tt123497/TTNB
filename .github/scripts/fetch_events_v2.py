#!/usr/bin/env python3
"""
fetch_events_v2.py — 事件驱动预判引擎

改造重点：每个事件不只是日期，而是包含影响分析
- 影响方向: bullish/bearish/neutral
- 影响板块: 哪些赛道会受影响
- 受益标的: 具体股票
- 观察要点: 什么情况下利好/利空
- 倒计时: 距今天几天

数据源：
1. 宏观日历（NBS/FOMC/LPR等）+ 自动影响分析
2. 产业事件（从信号历史中提取，由signal_monitor.py生成）
3. 财报日历（未来30天有财报的公司）
"""
import json, os, re, calendar as cal
from datetime import datetime, timezone, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(DIR)) if '.github' in DIR else DIR
if not os.path.exists(os.path.join(PROJECT_DIR, 'data.json')):
    for candidate in [PROJECT_DIR, os.path.dirname(DIR), DIR, 'D:/projects/market-dashboard']:
        if os.path.exists(os.path.join(candidate, 'data.json')):
            PROJECT_DIR = candidate
            break
DATA_PATH = os.path.join(PROJECT_DIR, 'data.json')

CST = datetime.now(timezone.utc) + timedelta(hours=8)
TODAY = CST.date()

# ═══════════════════════════════════════════════════
# 宏观事件影响分析模板
# ═══════════════════════════════════════════════════

MACRO_EVENTS = {
    'PMI': {
        'name': 'PMI数据',
        'icon': '📊',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': 'PMI>50为扩张，<50为收缩。高于预期利好制造业和周期股，低于预期利好债市和防御板块。',
        'watch_bull': 'PMI>50且环比回升 → 利好工业/有色/化工',
        'watch_bear': 'PMI<50且环比下降 → 利空制造业，利好黄金/债券',
        'sectors_bull': ['铜铝有色', '化工', '钢铁', '银行'],
        'sectors_bear': ['黄金/贵金属', '医药/CRO', '食品饮料'],
    },
    'CPI': {
        'name': 'CPI/PPI数据',
        'icon': '📊',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': 'CPI反映通胀。低于2.5%→降息预期升温利好成长股；高于3%→通胀压力利好资源股。',
        'watch_bull': 'CPI<2.5% → 降息预期，利好科技/创新药/地产',
        'watch_bear': 'CPI>3% → 通胀压力，利好黄金/有色/煤炭',
        'sectors_bull': ['AI芯片', '创新药/CXO', '房地产开发', '券商'],
        'sectors_bear': ['黄金/贵金属', '铜铝有色', '煤炭'],
    },
    'GDP': {
        'name': 'GDP数据',
        'icon': '📊',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': 'GDP反映经济增速。高于预期利好顺周期，低于预期利好逆周期和稳增长板块。',
        'watch_bull': 'GDP增速>5% → 利好银行/有色/消费',
        'watch_bear': 'GDP增速<4.5% → 利好基建/地产/稳增长',
        'sectors_bull': ['银行', '铜铝有色', '白酒', '消费电子/AI硬件'],
        'sectors_bear': ['电网设备/特高压', '房地产开发', '券商'],
    },
    'FOMC': {
        'name': 'FOMC利率决议',
        'icon': '🏦',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': '美联储利率决议。降息利好黄金/新兴市场/成长股；加息或鹰派利空科技股。',
        'watch_bull': '降息25bp+鸽派指引 → 利好黄金/AI芯片/创新药',
        'watch_bear': '维持利率+鹰派指引 → 利空科技股，利好美元/银行',
        'sectors_bull': ['黄金/贵金属', 'AI芯片', '创新药/CXO', '半导体设备'],
        'sectors_bear': ['银行', '保险'],
    },
    'LPR': {
        'name': 'LPR报价',
        'icon': '🏦',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': 'LPR下调降低企业融资成本，利好地产/银行息差/高负债行业；维持不变则无直接影响。',
        'watch_bull': 'LPR下调10bp+ → 利好地产/券商/高负债制造业',
        'watch_bear': 'LPR维持不变 → 无直接影响',
        'sectors_bull': ['房地产开发', '券商', '银行', '钢铁'],
        'sectors_bear': [],
    },
    'MLF': {
        'name': 'MLF操作',
        'icon': '🏦',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': 'MLF利率是LPR的锚。下调MLF利率→LPR有下调空间→利好地产/成长股。',
        'watch_bull': 'MLF利率下调/超额续做 → 利好债市/成长股/地产',
        'watch_bear': 'MLF缩量续做 → 流动性收紧，利空债市',
        'sectors_bull': ['房地产开发', '券商', 'AI芯片'],
        'sectors_bear': ['银行'],
    },
    '社融': {
        'name': '社融/M2数据',
        'icon': '💰',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': '社融超预期→信用扩张→利好顺周期；低于预期→信用收缩→利好防御板块。',
        'watch_bull': '社融超预期+M2增速>9% → 利好银行/券商/有色',
        'watch_bear': '社融低于预期 → 利好黄金/医药/食品饮料',
        'sectors_bull': ['银行', '券商', '铜铝有色', '房地产'],
        'sectors_bear': ['黄金/贵金属', '医药/CRO'],
    },
    '进出口': {
        'name': '进出口贸易数据',
        'icon': '🚢',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': '出口超预期利好制造业和航运；进口超预期利好大宗商品。',
        'watch_bull': '出口增速>10% → 利好制造业/航运/电子',
        'watch_bear': '出口下滑 → 利空制造业，关注内需板块',
        'sectors_bull': ['消费电子/AI硬件', '半导体设备', 'PCB/覆铜板'],
        'sectors_bear': ['食品饮料', '白酒'],
    },
    '工业增加值': {
        'name': '工业增加值/社零/固投',
        'icon': '🏭',
        'sector': '宏观',
        'direction': 'neutral',
        'logic': '工业增加值反映生产端，社零反映消费端，固投反映投资端。',
        'watch_bull': '工业增加值>5%+社零>4% → 利好制造业/消费',
        'watch_bear': '数据低于预期 → 利好稳增长/基建',
        'sectors_bull': ['铜铝有色', '化工', '消费电子/AI硬件', '食品饮料'],
        'sectors_bear': ['电网设备/特高压', '房地产'],
    },
}

# 2026年宏观日历（自动生成）
def generate_macro_calendar():
    """生成未来90天的宏观事件日历"""
    events = []
    y = CST.year
    m = CST.month

    for offset in range(0, 90):
        d = CST + timedelta(days=offset)
        dm = f'{d.month}月{d.day}日'

        # 每月1日：上月PMI（次月1日发布）
        if d.day == 1 and d.month in [1,2,3,4,5,6,7,8,9,10,11,12]:
            prev_m = d.month - 1 if d.month > 1 else 12
            prev_y = d.year if d.month > 1 else d.year - 1
            events.append({
                'd': f'{prev_m}月{prev_m}月PMI' if False else f'{d.month}月{d.day}日',
                'e': f'{prev_m}月财新PMI',
                'icon': '📊', 's': '宏观', 'big': 0,
                'countdown': offset,
                'impact': MACRO_EVENTS['PMI']
            })

        # 每月10日：CPI/PPI
        if d.day == 10:
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{d.month-1}月CPI/PPI数据' if d.month > 1 else '12月CPI/PPI数据',
                'icon': '📊', 's': '宏观', 'big': 1,
                'countdown': offset,
                'impact': MACRO_EVENTS['CPI']
            })

        # 每月13日：进出口
        if d.day == 13:
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{d.month-1}月进出口贸易数据' if d.month > 1 else '12月进出口数据',
                'icon': '🚢', 's': '宏观', 'big': 0,
                'countdown': offset,
                'impact': MACRO_EVENTS['进出口']
            })

        # 每月13日：社融
        if d.day == 13:
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{d.month-1}月金融数据（M2/社融/新增贷款）' if d.month > 1 else '12月金融数据',
                'icon': '💰', 's': '宏观', 'big': 1,
                'countdown': offset,
                'impact': MACRO_EVENTS['社融']
            })

        # 每月15日：MLF
        if d.day == 15:
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{d.month}月MLF操作',
                'icon': '🏦', 's': '宏观', 'big': 0,
                'countdown': offset,
                'impact': MACRO_EVENTS['MLF']
            })

        # 每月16日：工业增加值
        if d.day == 16:
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{d.month-1}月工业增加值/社零/固投' if d.month > 1 else '12月工业增加值',
                'icon': '🏭', 's': '宏观', 'big': 0,
                'countdown': offset,
                'impact': MACRO_EVENTS['工业增加值']
            })

        # 每月16日：GDP（仅1/4/7/10月）
        if d.day == 16 and d.month in [1, 4, 7, 10]:
            quarter = {1:'Q4', 4:'Q1', 7:'Q2', 10:'Q3'}[d.month]
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{quarter} GDP数据 / 上半年国民经济运行' if d.month == 7 else f'{quarter} GDP数据',
                'icon': '📊', 's': '宏观', 'big': 1,
                'countdown': offset,
                'impact': MACRO_EVENTS['GDP']
            })

        # 每月20日：LPR
        if d.day == 20:
            events.append({
                'd': f'{d.month}月{d.day}日',
                'e': f'{d.month}月LPR报价',
                'icon': '🏦', 's': '宏观', 'big': 0,
                'countdown': offset,
                'impact': MACRO_EVENTS['LPR']
            })

    # FOMC（固定日期）
    fomc_dates = [
        (7, 30),  # 7月FOMC
        (9, 17),  # 9月FOMC
        (11, 6),  # 11月FOMC
        (12, 17),  # 12月FOMC
    ]
    for fm, fd in fomc_dates:
        event_date = datetime(y, fm, fd)
        delta = (event_date.date() - TODAY).days
        if 0 <= delta <= 90:
            events.append({
                'd': f'{fm}月{fd}日',
                'e': 'FOMC利率决议',
                'icon': '🏦', 's': '宏观', 'big': 1,
                'countdown': delta,
                'impact': MACRO_EVENTS['FOMC']
            })

    return events

# ═══════════════════════════════════════════════════
# 从信号历史提取产业事件
# ═══════════════════════════════════════════════════

def extract_industry_events(d):
    """从_signalHistory中提取high级别的产业事件"""
    signals = d.get('_signalHistory', [])
    events = []
    seen = set()

    for s in signals:
        if s.get('level') != 'high':
            continue
        title = s.get('title', '')
        if title in seen:
            continue
        seen.add(title)

        sectors = s.get('sectors', [])
        sig_type = s.get('type_label', '')
        detected = s.get('detected', '')
        url = s.get('url', '')

        # 根据信号类型确定影响方向
        direction = 'neutral'
        if s.get('type') in ['price_up', 'capacity', 'earnings', 'order', 'tech', 'supply_chain']:
            direction = 'bullish'
        elif s.get('type') in ['price_down']:
            direction = 'bearish'

        events.append({
            'd': detected[:10] if detected else CST.strftime('%Y-%m-%d'),
            'e': title[:60],
            'icon': '⚡' if direction == 'bullish' else '⚠️' if direction == 'bearish' else '📌',
            's': sectors[0] if sectors else '产业',
            'big': 1,
            'countdown': 0,  # 已发生的事件
            'impact': {
                'direction': direction,
                'logic': f'{sig_type}信号，关联板块: {", ".join(sectors[:3])}',
                'sectors': sectors,
                'source': url,
                'detected': detected
            },
            'is_industry': True  # 标记为产业事件
        })

    return events

# ═══════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════

def main():
    print(f"=== Events v2 {CST.strftime('%Y-%m-%d %H:%M CST')} ===")

    if not os.path.exists(DATA_PATH):
        print("  ERROR: data.json not found")
        return

    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        d = json.load(f)

    # 1. 生成宏观日历
    macro = generate_macro_calendar()
    print(f"  Macro events: {len(macro)}")

    # 2. 从信号历史提取产业事件
    industry = extract_industry_events(d)
    print(f"  Industry events (from signals): {len(industry)}")

    # 3. 合并所有事件
    all_events = macro + industry

    # 4. 按倒计时排序
    all_events.sort(key=lambda x: x.get('countdown', 999))

    # 5. 保留旧的手工事件（有URL的）
    old_events = d.get('events', [])
    hand_events = [e for e in old_events if e.get('u', '').strip() and not e.get('is_industry')]
    print(f"  Hand-curated events preserved: {len(hand_events)}")

    # 6. 合并手工事件
    final_events = hand_events + all_events

    # 去重（按事件名）
    seen_names = set()
    deduped = []
    for e in final_events:
        name = e.get('e', '')
        if name not in seen_names:
            seen_names.add(name)
            deduped.append(e)

    # 限制100条
    if len(deduped) > 100:
        deduped = deduped[:100]

    d['events'] = deduped

    # 7. 更新layout（用新事件）
    # 保留旧layout的stocks信息
    old_layout = d.get('layout', [])
    old_layout_map = {l.get('e', ''): l for l in old_layout}

    new_layout = []
    for ev in deduped:
        layout_item = {
            'd': ev['d'],
            'icon': ev.get('icon', '📅'),
            'e': ev['e'],
            's': ev.get('s', '宏观'),
            'big': ev.get('big', 0),
            'countdown': ev.get('countdown', 0),
        }
        # 保留旧layout的stocks
        if ev['e'] in old_layout_map:
            layout_item['stocks'] = old_layout_map[ev['e']].get('stocks', [])
            layout_item['lead'] = old_layout_map[ev['e']].get('lead', 0)
        # 添加影响分析
        if 'impact' in ev:
            layout_item['impact'] = ev['impact']
        new_layout.append(layout_item)

    d['layout'] = new_layout

    # 8. 保存meta
    d['_eventsMeta'] = {
        'updated': CST.strftime('%Y-%m-%d %H:%M CST'),
        'total': len(deduped),
        'macro': len(macro),
        'industry': len(industry),
        'hand': len(hand_events),
        'schedule': '每次market-update自动刷新',
        'version': 'v2'
    }

    # 保存
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)

    print(f"  Total events: {len(deduped)} (macro={len(macro)} industry={len(industry)} hand={len(hand_events)})")
    print(f"  Layout: {len(new_layout)} cards")
    print(f"  Done → {DATA_PATH}")

if __name__ == '__main__':
    main()
