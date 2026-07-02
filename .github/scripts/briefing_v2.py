#!/usr/bin/env python3
"""
briefing_v2.py — 明日预判简报

改造重点：从"总结今天"改为"预判明天"
- 市场判断: 方向+置信度+逻辑
- Watchlist: 基于信号和因子的关注标的
- 信号汇总: 当日关键信号
- 次日事件: 明天会发生什么

数据来源（不靠AI编，全部结构化）：
1. 当日行情统计（recap）
2. 赛道因子评分（sectorFactors）
3. 异动信号（_marketSignals）
4. 北向资金趋势（northbound）
5. 龙虎榜机构席位（lhbFull）
6. 次日事件日历（events countdown=1）
"""
import json, os, re
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
TODAY = CST.strftime('%Y-%m-%d')

def load_data():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)

def calc_market_judgment(d):
    """计算市场方向判断"""
    r = d.get('recap', {})
    indices = r.get('index', [])
    nb = d.get('northbound', {})
    sf = d.get('sectorFactors', {})
    signals = d.get('_marketSignals', [])

    if not indices:
        return {'direction': 'neutral', 'confidence': 30, 'logic': '数据不足', 'key_levels': ''}

    # 计算指数均涨跌
    total_chg = 0
    count = 0
    up_count = 0
    for i in indices[:6]:
        chg_str = i.get('chg', '0%')
        try:
            chg = float(re.search(r'([-]?\d+\.?\d*)', chg_str).group(1))
            total_chg += chg
            count += 1
            if i.get('up'):
                up_count += 1
        except:
            pass

    avg_chg = total_chg / count if count > 0 else 0

    # 北向资金
    nb_net = nb.get('net_yi', 0) or 0

    # 赛道因子综合分
    total_score = 0
    sector_count = 0
    bull_sectors = []
    bear_sectors = []
    for s, info in sf.items():
        score = info.get('score', 0)
        total_score += score
        sector_count += 1
        if score >= 2:
            bull_sectors.append(s)
        elif score <= 0:
            bear_sectors.append(s)

    avg_factor = total_score / sector_count if sector_count > 0 else 0

    # high信号数
    high_signals = sum(1 for s in signals if s.get('level') == 'high')

    # 综合判断
    bull_score = 0
    bear_score = 0

    # 指数
    if avg_chg > 1:
        bull_score += 30
    elif avg_chg > 0:
        bull_score += 15
    elif avg_chg > -1:
        bear_score += 15
    else:
        bear_score += 30

    # 北向
    if nb_net > 30:
        bull_score += 20
    elif nb_net > 0:
        bull_score += 10
    elif nb_net > -30:
        bear_score += 10
    else:
        bear_score += 20

    # 因子
    if avg_factor > 1.5:
        bull_score += 25
    elif avg_factor > 0.5:
        bull_score += 12
    elif avg_factor < -0.5:
        bear_score += 12
    elif avg_factor < -1.5:
        bear_score += 25

    # 信号
    if high_signals > 3:
        bull_score += 15
    elif high_signals > 0:
        bull_score += 8

    confidence = abs(bull_score - bear_score)
    confidence = min(confidence + 30, 95)  # 基础30分+差值

    if bull_score > bear_score + 15:
        direction = 'bullish'
        logic = f'指数均涨{avg_chg:+.1f}%，{up_count}/{count}上涨。北向{"净流入"+str(nb_net)+"亿" if nb_net > 0 else "净流出"+str(abs(nb_net))+"亿"}。{len(bull_sectors)}个赛道因子偏多。'
    elif bear_score > bull_score + 15:
        direction = 'bearish'
        logic = f'指数均跌{avg_chg:.1f}%，{count-up_count}/{count}下跌。北向净流出{abs(nb_net)}亿。{len(bear_sectors)}个赛道因子偏空。'
    else:
        direction = 'neutral'
        logic = f'指数均涨{avg_chg:+.1f}%，多空交织。北向{"净流入"+str(nb_net)+"亿" if nb_net > 0 else "净流出"+str(abs(nb_net))+"亿"}。因子综合分{avg_factor:.1f}。'

    # 关键位（简化版）
    key_levels = ''
    for i in indices[:3]:
        name = i.get('n', '')
        val = i.get('v', '')
        chg = i.get('chg', '')
        key_levels += f'{name} {val}({chg}) '

    return {
        'direction': direction,
        'confidence': confidence,
        'logic': logic,
        'key_levels': key_levels,
        'avg_chg': round(avg_chg, 2),
        'up_count': up_count,
        'total_count': count,
        'northbound': nb_net,
        'factor_avg': round(avg_factor, 2),
        'bull_sectors': bull_sectors[:5],
        'bear_sectors': bear_sectors[:5],
        'high_signals': high_signals
    }

def build_watchlist(d, judgment):
    """基于因子和信号生成关注标的"""
    sf = d.get('sectorFactors', {})
    lp = d.get('livePrices', {})
    sfs = d.get('sectorFixedStocks', {})
    watchlist = []
    seen = set()

    # 从高评分赛道选标的
    sorted_sectors = sorted(sf.items(), key=lambda x: x[1].get('score', 0), reverse=True)
    for sector, info in sorted_sectors[:5]:
        if info.get('score', 0) < 1:
            continue
        # 获取赛道标的
        stocks = sfs.get(sector, [])
        for s in stocks[:3]:
            parts = s.split()
            if len(parts) < 2:
                continue
            code = parts[0]
            name = parts[1]
            if code in seen:
                continue
            seen.add(code)

            # 获取实时价格
            price_info = lp.get(f'sz{code}') or lp.get(f'sh{code}')
            chg = 0
            if price_info:
                chg = price_info.get('chg_pct', 0)

            # 找该赛道有信号的因子
            factor_reason = ''
            for f in info.get('factors', []):
                if f.get('value') and f.get('impact') == 'bullish':
                    factor_reason = f'{f["name"]}: {f["value"][:40]}'
                    break

            watchlist.append({
                'c': code,
                'n': name,
                'sec': sector,
                'chg': round(chg, 2),
                'factor_score': info.get('score', 0),
                'reason': factor_reason or f'{sector}因子评分+{info.get("score",0)}',
                'direction': 'long' if judgment['direction'] != 'bearish' else 'watch'
            })

    return watchlist[:8]

def build_signal_summary(d):
    """汇总当日关键信号"""
    signals = d.get('_marketSignals', [])
    summary = []

    # 按类型分组
    by_type = {}
    for s in signals:
        t = s.get('type_label', '其他')
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(s)

    for sig_type, items in by_type.items():
        summary.append({
            'type': sig_type,
            'count': len(items),
            'sectors': list(set(s.get('sectors', [])[0] for s in items if s.get('sectors'))),
            'top': items[0].get('title', '')[:60] if items else ''
        })

    return summary

def build_tomorrow_events(d):
    """明日事件"""
    events = d.get('events', [])
    tomorrow = []
    for ev in events:
        countdown = ev.get('countdown', 999)
        if countdown <= 1:  # 明天或今天
            impact = ev.get('impact', {})
            tomorrow.append({
                'd': ev.get('d', ''),
                'e': ev.get('e', ''),
                'icon': ev.get('icon', '📅'),
                'direction': impact.get('direction', 'neutral'),
                'logic': impact.get('logic', '')[:80] if impact else '',
                'sectors': impact.get('sectors_bull', []) + impact.get('sectors_bear', []) if impact else []
            })
    return tomorrow[:5]

def main():
    print(f"=== Briefing v2 {CST.strftime('%Y-%m-%d %H:%M CST')} ===")

    d = load_data()

    # 1. 市场判断
    judgment = calc_market_judgment(d)
    print(f"  Direction: {judgment['direction']} ({judgment['confidence']}%)")

    # 2. 关注标的
    watchlist = build_watchlist(d, judgment)
    print(f"  Watchlist: {len(watchlist)} stocks")

    # 3. 信号汇总
    signal_summary = build_signal_summary(d)
    print(f"  Signal types: {len(signal_summary)}")

    # 4. 次日事件
    tomorrow = build_tomorrow_events(d)
    print(f"  Tomorrow events: {len(tomorrow)}")

    # 组装简报
    briefing = {
        'date': CST.strftime('%Y-%m-%d'),
        'updated': CST.strftime('%Y-%m-%d %H:%M CST'),
        'marketJudgment': judgment,
        'watchlist': watchlist,
        'signals': signal_summary,
        'tomorrowEvents': tomorrow,
        'version': 'v2'
    }

    d['briefing'] = briefing

    # 也更新top3和picks（兼容前端）
    direction_emoji = {'bullish': '🟢', 'bearish': '🔴', 'neutral': '🟡'}
    d['top3'] = [{
        't': f"{direction_emoji.get(judgment['direction'],'🟡')} 市场预判: {judgment['direction']} (置信度{judgment['confidence']}%)",
        's': judgment['logic'],
        'b': judgment['logic'] + ' | 关键位: ' + judgment.get('key_levels', ''),
        'u': '',
        'sig': direction_emoji.get(judgment['direction'], '🟡')
    }]

    # top3补充信号
    for sig in signal_summary[:2]:
        d['top3'].append({
            't': f"📊 {sig['type']} ({sig['count']}条) - {sig['sectors'][0] if sig['sectors'] else ''}",
            's': sig['top'],
            'b': sig['top'],
            'u': '',
            'sig': '🟡'
        })

    # picks
    d['picks'] = []
    for w in watchlist[:5]:
        d['picks'].append({
            'r': len(d['picks']) + 1,
            'c': w['c'],
            'n': w['n'],
            'why': w['reason'],
            'sec': w['sec'],
            'u': f'https://quote.eastmoney.com/sz{w["c"]}.html' if not w['c'].startswith('6') else f'https://quote.eastmoney.com/sh{w["c"]}.html'
        })

    save_data(d)
    print(f"  Top3: {len(d['top3'])} | Picks: {len(d['picks'])}")
    print(f"  Done → {DATA_PATH}")

if __name__ == '__main__':
    main()
