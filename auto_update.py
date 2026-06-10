#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📡 股市哨兵 · 自动数据引擎
每30分钟抓取实时行情 → 更新 data.json → 网站自动刷新
独立运行，不依赖 Claude Code
"""

import json, os, time, re, random
from datetime import datetime, timedelta
from collections import OrderedDict

try:
    import requests
except ImportError:
    os.system(f'"{os.path.dirname(os.__file__)}\\Scripts\\pip.exe" install requests --quiet')
    import requests

DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(DIR, 'data.json')
LOG_PATH = os.path.join(DIR, 'update.log')

# User-Agent pool
UAS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148',
]

def log(msg):
    ts = datetime.now().strftime('%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except:
        pass

def fetch(url, referer='https://finance.sina.com.cn/', retries=2):
    headers = {
        'User-Agent': random.choice(UAS),
        'Referer': referer,
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Cache-Control': 'no-cache',
    }
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=8)
            r.encoding = r.apparent_encoding or 'gbk'
            return r.text
        except Exception as e:
            if i == retries - 1:
                log(f"⚠️ Fetch failed: {url[:80]}... {e}")
                return None
            time.sleep(1)

def get_indices():
    """拉取主要指数实时数据 - 新浪财经API"""
    codes = {
        'sh000001': '上证指数', 'sz399001': '深证成指',
        'sz399006': '创业板指', 'sh000688': '科创50',
        'sh000300': '沪深300', 'sh000016': '上证50',
    }
    query = ','.join(codes.keys())
    url = f'http://hq.sinajs.cn/list={query}'
    text = fetch(url)
    if not text:
        return []

    results = []
    for line in text.strip().split('\n'):
        if '=' not in line or len(line) < 30:
            continue
        code = line.split('=')[0].replace('var hq_str_', '')
        name = codes.get(code, code)
        data = line.split('"')[1].split(',') if '"' in line else []
        if len(data) < 5:
            continue
        try:
            price = float(data[3])  # 当前价
            prev = float(data[2])   # 昨收
            chg_pct = round((price - prev) / prev * 100, 2) if prev > 0 else 0
            vol = data[8] if len(data) > 8 else '0'
            results.append({
                'code': code, 'name': name, 'price': price,
                'chg_pct': chg_pct, 'volume': vol,
            })
        except:
            continue
    return results

def get_sector_heat():
    """板块热度 - 东方财富概念板块API"""
    try:
        url = 'http://push2.eastmoney.com/api/qt/clist/get?fid=f3&po=1&pz=30&pn=1&np=1&fltt=2&fields=f2,f3,f4,f12,f14&fs=m:90+t:3&ut=bd1d9ddb04089700cf9c27f6f7426281'
        text = fetch(url, referer='https://quote.eastmoney.com/')
        if not text:
            return []
        data = json.loads(text)
        items = data.get('data', {}).get('diff', [])
        results = []
        for item in items[:30]:
            results.append({
                'code': item.get('f12', ''),
                'name': item.get('f14', ''),
                'chg_pct': item.get('f3', 0),
                'price': item.get('f2', 0),
            })
        return results
    except Exception as e:
        log(f"⚠️ Sector heat failed: {e}")
        return []

def get_market_flow():
    """资金流向概要"""
    try:
        url = 'http://push2.eastmoney.com/api/qt/clist/get?fid=f62&po=1&pz=10&pn=1&np=1&fltt=2&fields=f12,f14,f62,f184&fs=m:90+t:2&ut=bd1d9ddb04089700cf9c27f6f7426281'
        text = fetch(url, referer='https://data.eastmoney.com/')
        if not text:
            return []
        data = json.loads(text)
        items = data.get('data', {}).get('diff', [])
        results = []
        for item in items[:8]:
            results.append({
                'name': item.get('f14', ''),
                'flow': item.get('f62', 0) / 1e8,
            })
        return results
    except:
        return []

def get_realtime_stocks(codes_str):
    """批量获取个股实时行情"""
    results = {}
    codes = [c.strip() for c in codes_str.split(',') if c.strip()]
    # 处理前缀
    sina_codes = []
    for c in codes:
        if c.startswith('60') or c.startswith('68'):
            sina_codes.append(f'sh{c}')
        elif c.startswith('00') or c.startswith('30'):
            sina_codes.append(f'sz{c}')
        elif c.startswith('8') or c.startswith('4') or c.startswith('9'):
            sina_codes.append(f'bj{c}')
        else:
            sina_codes.append(f'sh{c}')

    for i in range(0, len(sina_codes), 50):
        batch = sina_codes[i:i+50]
        url = 'http://hq.sinajs.cn/list=' + ','.join(batch)
        text = fetch(url)
        if not text:
            continue
        for line in text.strip().split('\n'):
            if '=' not in line:
                continue
            code = line.split('=')[0].replace('var hq_str_', '')
            parts = line.split('"')[1].split(',') if '"' in line else []
            if len(parts) < 5:
                continue
            try:
                results[code] = {
                    'price': float(parts[3]),
                    'chg_pct': round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else 0,
                    'name': parts[0],
                }
            except:
                continue
    return results

def build_recap():
    """构建大盘复盘"""
    indices = get_indices()
    sectors = get_sector_heat()

    recap_index = []
    for idx in indices:
        recap_index.append({
            'n': idx['name'], 'v': f"{idx['price']:.0f}" if idx['price'] > 100 else f"{idx['price']:.0f}",
            'chg': f"{idx['chg_pct']:+.2f}%", 'up': idx['chg_pct'] >= 0,
        })

    # 领涨/领跌板块
    sorted_sec = sorted(sectors, key=lambda x: x['chg_pct'], reverse=True)
    winners = sorted_sec[:6]
    losers = sorted_sec[-6:][::-1]

    win_list = [{'s': s['name'], 'stks': f"领涨板块"} for s in winners]
    lose_list = [{'s': s['name'], 'stks': f"领跌板块"} for s in losers]

    heat_list = [{'n': s['name'], 's': f"{s['chg_pct']:+.1f}%", 'c': 'var(--red)' if s['chg_pct'] > 0 else 'var(--green)'} for s in sorted_sec[:15]]

    note = f"{datetime.now().strftime('%m/%d %H:%M')} 自动更新。涨跌板块实时刷新。"

    return {
        'index': recap_index[:6] if len(recap_index) >= 6 else recap_index,
        'flow': [{'n': '实时资金数据', 'amt': '见东财', 'pct': '-'}],
        'heat': heat_list[:12],
        'winners': win_list[:5],
        'losers': lose_list[:5],
        'note': note,
    }

def build_full_json():
    """构建完整的 data.json"""
    now = datetime.now()
    is_weekday = now.weekday() < 5

    # 基础数据（从市场模板 + 已有静态知识）
    base = {
        'updated': now.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': '今日 17:03 收盘雷达' if is_weekday else '下个交易日 9:03 早盘哨兵',
        'updateCount': getattr(build_full_json, 'count', 0) + 1,
        'recap': build_recap(),
        'sectors_signal': {},  # 各赛道最新信号
        'runtime': {
            'python': True,
            'autoUpdate': True,
            'interval': '30分钟',
            'lastError': None,
        }
    }
    build_full_json.count = base['updateCount']

    # 尝试获取赛道标的实时行情
    all_codes = getattr(build_full_json, 'all_codes', '')
    if all_codes:
        try:
            live = get_realtime_stocks(all_codes)
            base['livePrices'] = live
        except Exception as e:
            base['runtime']['lastError'] = str(e)[:100]

    return base

def main_loop():
    """主循环 - 每30分钟更新一次"""
    log('🚀 股市哨兵数据引擎启动')
    log(f'📂 输出: {JSON_PATH}')

    # 预加载所有标的代码
    try:
        html_path = os.path.join(DIR, 'index.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        codes = set()
        for m in re.finditer(r'\{c:"(\d{6})"', html):
            codes.add(m.group(1))
        build_full_json.all_codes = ','.join(sorted(codes))
        log(f'📊 监控标的: {len(codes)} 只')
    except Exception as e:
        log(f'⚠️ 加载标的列表失败: {e}')

    error_count = 0
    while True:
        try:
            log(f'🔄 开始更新... (第{getattr(build_full_json,"count",0)+1}次)')

            data = build_full_json()

            with open(JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            log(f'✅ 更新成功 -> {data["updated"]}')
            error_count = 0

        except Exception as e:
            error_count += 1
            log(f'❌ 更新失败 ({error_count}): {e}')
            if error_count > 5:
                log('⚠️ 连续失败5次，30分钟后重试')

        # 等待30分钟
        time.sleep(1800)

if __name__ == '__main__':
    main_loop()
