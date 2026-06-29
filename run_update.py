#!/usr/bin/env python3
"""
run_update.py — TTNB 统一数据更新入口
替代: fetch_data.py + fetch_enrich.py + fetch_tierA.py + fetch_tierB.py + fetch_news.py

调用 a_stock_data.py 的全部28+端点，带优先级降级链。
每个周期: 加载 data.json → 采集所有数据层 → 写入 data.json
"""
import json, os, sys, time, shutil, glob as _glob
from datetime import datetime, timezone, timedelta
from collections import Counter

# ── 确保能找到 a_stock_data ──
DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

import a_stock_data as ad

# ── 加载固定标的池 ──
SECTOR_FIXED_STOCKS = {}
try:
    SFS_PATH = os.path.join(DIR, 'sector_fixed_stocks.py')
    with open(SFS_PATH, encoding='utf-8') as _sfs:
        _sfs_src = _sfs.read()
    _sfs_ns = {}
    exec(_sfs_src, _sfs_ns)
    SECTOR_FIXED_STOCKS = _sfs_ns.get('SECTOR_FIXED_STOCKS', {})
except Exception:
    SECTOR_FIXED_STOCKS = {}

DATA_PATH = os.path.join(DIR, 'data.json')
BHISTORY_PATH = os.path.join(DIR, 'briefing-history.json')
CST = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════════════
# 0. 工具函数
# ═══════════════════════════════════════════════════════════════

def load_data():
    """加载现有 data.json，失败返回 {}"""
    if not os.path.exists(DATA_PATH):
        return {}
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

from sanitize_json import atomic_save_with_briefing_history

def save_data(d):
    """原子写入 — 带 UTF-8 清洗"""
    atomic_save_with_briefing_history(d, DATA_PATH, BHISTORY_PATH)

def codes_from_data(d):
    """从 data.json 提取所有6位代码"""
    codes = set()
    for lev in d.get('layout', []):
        for s in lev.get('stocks', []):
            if isinstance(s, dict):
                c = s.get('c', '')
            else:
                parts = (s or '').split()
                c = parts[0] if parts else ''
            if c and len(c) == 6:
                codes.add(c)
    for sec_stocks in d.get('sectorStocks', {}).values():
        for s in (sec_stocks or []):
            c = s.get('c', '') if isinstance(s, dict) else ((s or '').split()[0] if s else '')
            if c and len(c) == 6:
                codes.add(c)
    # Also from index.html
    html_path = os.path.join(DIR, 'index.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            import re
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()):
                codes.add(m.group(1))
    return sorted(codes)

def priority_code_list(codes, preserve):
    """Reorder codes so briefing picks + layout stocks come first."""
    import re
    priority = []
    seen = set()

    # Tier 1: briefing picks (AI-selected daily picks — most important)
    for src in [preserve.get('picks', []), preserve.get('briefing', {}).get('picks', [])]:
        for p in (src or []):
            c = p.get('c', '') if isinstance(p, dict) else ''
            if c and len(c) == 6 and c not in seen:
                priority.append(c)
                seen.add(c)

    # Tier 2: layout card stocks (visible on dashboard)
    for lev in preserve.get('layout', []):
        for s in lev.get('stocks', []):
            c = s.get('c', '') if isinstance(s, dict) else ''
            if c and len(c) == 6 and c not in seen:
                priority.append(c)
                seen.add(c)

    # Tier 3: top3 briefing topics (may reference stock codes in text)
    for t3 in preserve.get('top3', []):
        text = t3.get('t', '') if isinstance(t3, dict) else str(t3)
        for m in re.finditer(r'\b(\d{6})\b', text):
            c = m.group(1)
            if c not in seen:
                priority.append(c)
                seen.add(c)

    # Tier 4: remaining codes, alphabetically sorted
    for c in codes:
        if c not in seen:
            priority.append(c)

    return priority

def get_sector_mapping():
    """从 index.html 提取 {code: sector_name} 映射"""
    mapping = {}
    html_path = os.path.join(DIR, 'index.html')
    if not os.path.exists(html_path):
        return mapping
    import re
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
    st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)
    for i in range(min(len(id_names), len(st_blocks))):
        _, sec_name = id_names[i]
        for c in re.findall(r'\{c:"(\d{6})"', st_blocks[i]):
            mapping[c] = sec_name
    return mapping

def now_cst():
    return datetime.now(timezone.utc) + timedelta(hours=8)

def is_trading(cst):
    """
    判断是否为A股交易时段。
    优先使用 chinese_calendar 库判断法定节假日 (春节/国庆/清明等),
    库不可用时回退到简单的周一到周五判断。

    交易时段: 周一到周五 9:15-15:00 (含集合竞价, 含午休时段)
    """
    # 周末一定不交易
    if cst.weekday() >= 5:
        return False
    if not (9 <= cst.hour < 15):
        return False
    # 法定节假日判断 (chinese_calendar 库)
    try:
        import chinese_calendar as cc
        # chinese_calendar 的 is_holiday 接受 date 对象
        d = cst.date()
        if cc.is_holiday(d):
            return False
        # is_workday 返回 True 表示是工作日 (含调休)
        return cc.is_workday(d)
    except Exception:
        # chinese_calendar 库不可用或日期超出范围, 回退到简单判断
        return True

# ═══════════════════════════════════════════════════════════════
# 1. 实时行情 (L1: 通达信 > 腾讯 > 东财 + 新浪兜底)
# ═══════════════════════════════════════════════════════════════

def fetch_indices():
    """指数行情: 腾讯 > 通达信 > 新浪"""
    cst = now_cst()
    # 找最近交易日
    indices = ad.get_index_quotes()
    if indices:
        return indices
    # 终极兜底
    return [{'n': '等待开盘', 'v': '?', 'chg': '0%', 'up': True}]

def fetch_live_prices(codes, prefer_tdx=True):
    """
    个股实时行情 → data.json livePrices 格式
    返回: {sh600519: {price, chg_pct, name, industry, concepts}, ...}
    """
    results = {}
    quotes = ad.get_stock_quotes(codes, prefer_tdx=prefer_tdx)
    for code_orig in codes:
        code = ad.normalize_code(code_orig)
        pfx = ad.get_prefix(code)
        key = f"{pfx}{code}"

        # Try exact match in quotes
        q = quotes.get(code, {})
        if not q and key in quotes:
            q = quotes[key]

        if q:
            results[key] = {
                'price': q.get('price', 0),
                'chg_pct': q.get('change_pct', q.get('chg_pct', 0)),
                'name': q.get('name', ''),
            }
        else:
            results[key] = {'price': 0, 'chg_pct': 0, 'name': ''}
    return results

def fetch_sector_heat(live=None, stock_sector=None):
    """
    赛道热度 → [{n,s,c,bk}]
    优先级: 从个股现价自算 → 东财行业板块降级
    """
    # L1: 从个股现价自算赛道平均涨跌（不依赖东财）
    if live and stock_sector:
        heat = ad.compute_sector_heat_from_stocks(live, stock_sector)
        if heat:
            return heat

    # L2 降级: 东财行业板块 (可能被风控)
    comp = ad.industry_comparison(50)
    if comp['total'] > 0:
        sectors = []
        for r in comp['top'] + comp['bottom'][:10]:
            pct = r.get('change_pct', 0) or 0
            sectors.append({
                'n': r['name'],
                's': f"{pct:+.1f}%",
                'c': 'var(--red)' if pct > 0 else 'var(--green)',
                'bk': r.get('code', '')
            })
        return sectors

    return []

def fetch_sector_stocks(heat_data, our_names, prefer_tdx=True):
    """
    各赛道标的 — 优先级: sector_fixed_stocks + 通达信实时价 > 腾讯实时价 > 东财板块API
    不用东财做标的发现，用固定池+实时行情。
    """
    result = {}
    if not SECTOR_FIXED_STOCKS:
        return result

    # 收集所有固定标的代码 → 批量取实时价
    all_codes = set()
    sec_codes = {}
    for sec_name in our_names:
        fixed = SECTOR_FIXED_STOCKS.get(sec_name, [])
        if not fixed:
            # 模糊匹配
            for fk in SECTOR_FIXED_STOCKS:
                if sec_name[:2] in fk or fk[:2] in sec_name:
                    fixed = SECTOR_FIXED_STOCKS[fk]
                    break
        codes = []
        for s in fixed[:8]:
            parts = s.split()
            if parts and len(parts[0]) == 6:
                codes.append(parts[0])
        sec_codes[sec_name] = codes
        all_codes.update(codes)

    all_codes = sorted(all_codes)

    # L1: 通达信 TCP (最快，不封IP)
    tdx_prices = {}
    if prefer_tdx:
        try:
            tdx_prices = ad.mootdx_quotes(all_codes) or {}
        except Exception:
            pass

    # L2: 腾讯 HTTP (不封IP)
    tx_prices = {}
    if len(tdx_prices) < len(all_codes) * 0.3:
        try:
            tx_prices = ad.tencent_quote(all_codes)
        except Exception:
            pass

    # 组装结果
    for sec_name in our_names:
        stocks = []
        for code in sec_codes.get(sec_name, [])[:8]:
            # 优先通达信价格
            q = tdx_prices.get(code, {})
            price = q.get('price', 0) or 0
            chg_pct = q.get('chg_pct', 0) or 0
            name = q.get('name', '')

            # 再试腾讯
            if not price or not name:
                tx = tx_prices.get(code, {})
                if tx:
                    price = tx.get('price', 0) or 0
                    chg_pct = tx.get('change_pct', 0) or 0
                    name = tx.get('name', '')

            # 从固定池拿名字
            if not name:
                fixed_list = SECTOR_FIXED_STOCKS.get(sec_name, [])
                for fs in fixed_list:
                    if fs.startswith(code):
                        name = fs[7:] if len(fs) > 7 else code
                        break

            stocks.append({'c': code, 'n': name or code, 'chg': round(chg_pct, 1)})

        stocks.sort(key=lambda x: -x['chg'])
        result[sec_name] = stocks[:8]

    return result

def fill_layout_stocks(layout_list, sector_stocks, fixed_stocks):
    """
    用固定标的池 + 实时价填充布局卡标的。
    替代旧 fetch_data.py 的 auto-repair layout stocks 逻辑，
    数据源从东财板块API → sector_fixed_stocks.py + 通达信/腾讯实时价
    """
    if not layout_list or not fixed_stocks:
        return layout_list

    for lev in layout_list:
        sec_name = lev.get('s', '')
        if not sec_name:
            continue

        # 统一从 sector_fixed_stocks.py 取标的——单一数据源
        fixed = fixed_stocks.get(sec_name, [])
        if not fixed:
            for fk in fixed_stocks:
                if sec_name[:2] in fk or fk[:2] in sec_name:
                    fixed = fixed_stocks[fk]
                    break

        if fixed:
            stocks = []
            for fs in fixed[:6]:
                parts = fs.split()
                if not parts or len(parts[0]) != 6:
                    continue
                code = parts[0]
                name = ' '.join(parts[1:]) if len(parts) > 1 else code
                chg = 0
                # 从 sectorStocks 找最新涨跌幅
                for sec, ss in (sector_stocks or {}).items():
                    for s in ss:
                        if s.get('c') == code:
                            chg = s.get('chg', 0)
                            break
                    if chg != 0:
                        break
                stocks.append({'c': code, 'n': name, 'chg': round(chg, 1)})
            stocks.sort(key=lambda x: -x['chg'])
            lev['stocks'] = stocks[:6]

    return layout_list

def fetch_zt_ladder(cst):
    """连板梯队"""
    return ad.get_zt_pool()

def fetch_lhb_full():
    """全市场龙虎榜"""
    cst = now_cst()
    for attempt in range(4):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        result = ad.daily_dragon_tiger(td.strftime('%Y-%m-%d'))
        if result['total_records'] > 0:
            # Convert to website format
            stocks = []
            for s in result['stocks'][:100]:
                net = s.get('net_buy_wan', 0) or 0
                stocks.append({
                    'c': s['code'], 'n': s['name'],
                    'reason': s.get('reason', '')[:30],
                    'net': net, 'chg': s.get('change_pct', 0),
                    'turnover': s.get('turnover_pct', 0)
                })
            buy_list = sorted([s for s in stocks if s['net'] > 0], key=lambda x: -x['net'])[:15]
            sell_list = sorted([s for s in stocks if s['net'] < 0], key=lambda x: x['net'])[:15]
            return {
                'date': td.strftime('%m/%d'),
                'total': len(stocks),
                'topBuy': buy_list,
                'topSell': sell_list
            }
    return {'date': '', 'total': 0, 'topBuy': [], 'topSell': []}

# ═══════════════════════════════════════════════════════════════
# 2. 增强层 — 北向/热点/解禁/融资融券
# ═══════════════════════════════════════════════════════════════

def fetch_northbound():
    """北向资金 (同花顺 hsgtApi)"""
    hsgt = ad.hsgt_realtime()
    cst = now_cst()
    if isinstance(hsgt, dict):
        return {
            "date": cst.strftime('%Y-%m-%d'),
            "hgt_yi": round(hsgt.get('last_hgt', 0) or 0, 2),
            "sgt_yi": round(hsgt.get('last_sgt', 0) or 0, 2),
            "net_yi": round(hsgt.get('net_yi', 0) or 0, 2),
            "points": len(hsgt.get('times', [])),
            "status": "实时" if is_trading(cst) else "收盘"
        }
    # DataFrame fallback
    try:
        last = hsgt.dropna().iloc[-1]
        return {
            "date": cst.strftime('%Y-%m-%d'),
            "hgt_yi": round(last.get('hgt_yi', 0) or 0, 2),
            "sgt_yi": round(last.get('sgt_yi', 0) or 0, 2),
            "net_yi": round((last.get('hgt_yi', 0) or 0) + (last.get('sgt_yi', 0) or 0), 2),
            "points": len(hsgt),
            "status": "实时" if is_trading(cst) else "收盘"
        }
    except Exception:
        return {"date": "", "hgt_yi": 0, "sgt_yi": 0, "net_yi": 0, "points": 0, "status": "无数据"}

def fetch_hot_reasons():
    """同花顺热点归因 — 兼容 sentinel_ai.py 旧字段名"""
    data = ad.get_hot_sector_themes()
    if isinstance(data, dict):
        hs = data.get('hot_stocks', [])
        tt = data.get('top_themes', [])
        data['total'] = len(hs)
        data['topReasons'] = tt
        # 字段名映射: code→c, name→n, chg_pct→chg
        data['stocks'] = [{'c': s.get('code',''), 'n': s.get('name',''),
                           'reason': s.get('reason',''), 'chg': s.get('chg_pct',0),
                           'turnover': s.get('turnover',0)} for s in hs]
    return data

def fetch_lockup_alerts(codes):
    """限售解禁预警"""
    cst = now_cst()
    today = cst.strftime('%Y-%m-%d')
    alerts = []
    scanned = 0
    for code in (codes or [])[:60]:
        time.sleep(0.15)
        try:
            data = ad.lockup_expiry(code, today, 90)
            for u in data.get('upcoming', []):
                ratio = float(u.get('ratio', 0) or 0)
                if ratio < 0.5:
                    continue
                alerts.append({
                    'c': code, 'n': '', 'd': u['date'],
                    'type': (u.get('type', '') or '')[:20],
                    'shares': round((u.get('shares', 0) or 0) / 10000, 0),
                    'ratio': ratio
                })
            scanned += 1
        except Exception:
            pass
    alerts.sort(key=lambda x: (x['d'], -x['ratio']))
    return {"scanned": scanned, "alerts": alerts[:30], "forwardDays": 90}

def fetch_margin_summary(codes):
    """融资融券摘要"""
    from urllib.request import Request, urlopen
    summary = []
    for code in (codes or [])[:30]:
        time.sleep(0.2)
        try:
            data = ad.eastmoney_datacenter(
                "RPTA_WEB_RZRQ_GGMX",
                filter_str=f'(SCODE="{code}")',
                page_size=6,
                sort_columns="DATE", sort_types="-1",
            )
            if len(data) >= 2:
                latest = data[0]
                older = data[-1]
                rzye_now = (latest.get("RZYE") or 0) / 10000
                rzye_old = (older.get("RZYE") or 0) / 10000
                change_5d = round((rzye_now - rzye_old) / (abs(rzye_old) + 1) * 100, 1)
                summary.append({
                    'c': code,
                    'n': latest.get("SECURITY_NAME_ABBR", ""),
                    'd': str(latest.get("DATE", ""))[:10],
                    'rzye_wan': round(rzye_now, 0),
                    'change_5d': change_5d,
                    'rzmre_wan': round((latest.get("RZMRE") or 0) / 10000, 0),
                })
        except Exception:
            pass
    summary.sort(key=lambda x: -x['change_5d'])
    return {"stocks": summary, "status": "ok" if summary else "无数据"}

# ═══════════════════════════════════════════════════════════════
# 3. Tier A — 行业排名/腾讯估值/公告/研报
# ═══════════════════════════════════════════════════════════════

# 新闻采集逻辑已提取到 news_sources.py (单一数据源, 与 news_watch.py 共享)
# 新闻数据由 news_watch.py 独立写入 news.json, 不再写入 data.json
from news_sources import (
    SECTOR_KW, MARKET_KW, NOISE_KW,
    fetch_all_news, fetch_global_news,
)

# Tushare 增强（可选 — token 不可用时自动跳过）
try:
    from tushare_enrich import enrich_data, apply_enrichment, sanitize_obj
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    print("  [tushare] 模块不可用，跳过增强")

def fetch_industry_ranking(live=None, stock_sector=None):
    """
    行业板块排名 — 优先级: 个股聚合 → 东财降级
    """
    # L1: 从个股现价自算
    if live and stock_sector:
        heat = ad.compute_sector_heat_from_stocks(live, stock_sector)
        if heat:
            return [{"n": h['n'], "chg": float(h['s'].replace('%','').replace('+','')),
                     "upCnt": 0, "dnCnt": 0, "ld": "", "bk": h.get('bk','')}
                    for h in heat[:80]]

    # L2 降级: 东财
    comp = ad.industry_comparison(80)
    if comp['total'] > 0:
        return [{
            "n": r['name'], "chg": round(r['change_pct'] or 0, 2),
            "upCnt": r.get('up_count', 0) or 0, "dnCnt": r.get('down_count', 0) or 0,
            "ld": r.get('leader', '') or '', "bk": r.get('code', '')
        } for r in (comp['top'] + comp['bottom'])]

    return []

def fetch_tencent_val(codes):
    """腾讯 PE/PB/市值"""
    tx = ad.tencent_quote(codes[:80])
    return {c: {"n": q.get('name',''), "p": q.get('price',0),
                "pe": round(q.get('pe_ttm',0) or 0, 1),
                "pb": round(q.get('pb',0) or 0, 1),
                "mcap": round(q.get('mcap_yi',0) or 0, 0),
                "chg": round(q.get('change_pct',0) or 0, 2),
                "to": round(q.get('turnover_pct',0) or 0, 2)}
            for c, q in tx.items() if q.get('name')}

def fetch_cninfo_alerts(codes):
    """巨潮公告 (关键标的)"""
    alerts = []
    for code in (codes or [])[:20]:
        time.sleep(0.3)
        try:
            anns = ad.cninfo_announcements(code, 3)
            for a in anns[:3]:
                alerts.append({'c': code, 't': a['title'][:100], 'd': a['date']})
        except Exception:
            pass
    return {"alerts": alerts[:20], "status": "ok" if alerts else "no data"}

def fetch_ind_reports():
    """东财行业研报 Top10"""
    reports = ad.eastmoney_industry_reports("*", max_pages=1)
    return {
        "reports": [{"t": r.get('title','')[:100], "org": (r.get('orgSName','') or '')[:30],
                     "ind": (r.get('industryName','') or '')[:30],
                     "rating": (r.get('emRatingName','') or '')[:20],
                     "d": str(r.get('publishDate',''))[:10]}
                    for r in reports[:10]],
        "updated": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        "status": "ok" if reports else "empty"
    }

# ═══════════════════════════════════════════════════════════════
# 4. Tier B — 个股深度数据 (每30min分快慢组)
# ═══════════════════════════════════════════════════════════════

def fetch_concept_blocks(codes):
    """概念板块归属"""
    cb = {}
    for c in (codes or [])[:25]:
        try:
            blocks = ad.eastmoney_concept_blocks(c)
            if blocks.get('concept_tags'):
                cb[c] = blocks['concept_tags'][:15]
        except Exception:
            pass
        time.sleep(0.3)
    return cb

def fetch_stock_info_em(codes):
    """个股基本信息"""
    si = {}
    for c in (codes or [])[:25]:
        try:
            info = ad.eastmoney_stock_info(c)
            if info:
                si[c] = {
                    "ind": info.get("industry", ""),
                    "tot": info.get("total_shares", 0),
                    "flt": info.get("float_shares", 0),
                    "listDate": str(info.get("list_date", ""))[:10]
                }
        except Exception:
            pass
        time.sleep(0.2)
    return si

def fetch_fund_flow_min(codes):
    """资金流分钟级"""
    ff = {}
    for c in (codes or [])[:25]:
        try:
            flows = ad.eastmoney_fund_flow_minute(c)
            if flows:
                total = sum(f.get('main_net', 0) for f in flows[-10:])
                ff[c] = round(total / 10000, 1)
        except Exception:
            pass
        time.sleep(0.2)
    return ff

def fetch_stock_news_batch(codes):
    """个股新闻"""
    sn = {}
    for c in (codes or [])[:25]:
        try:
            news = ad.eastmoney_stock_news(c, 3)
            if news:
                sn[c] = [n['title'][:80] for n in news[:3]]
        except Exception:
            pass
        time.sleep(0.3)
    return sn

def fetch_fund_flow_120d_batch(codes):
    """120日资金流"""
    ff = {}
    for c in (codes or [])[:25]:
        try:
            flows = ad.stock_fund_flow_120d(c)
            if flows:
                n5d = sum(f.get('main_net', 0) for f in flows[-5:])
                n20d = sum(f.get('main_net', 0) for f in flows[-20:])
                ff[c] = {"n5d": round(n5d / 10000, 1), "n20d": round(n20d / 10000, 1)}
        except Exception:
            pass
        time.sleep(0.3)
    return ff

def fetch_dragon_seats_batch(codes):
    """龙虎榜席位(个股)"""
    ds = {}
    # 动态计算30天前的日期, 替代原来的硬编码 '2026-06-01'
    from_date = (now_cst() - timedelta(days=30)).strftime('%Y-%m-%d')
    for c in (codes or [])[:25]:
        try:
            data = ad.eastmoney_datacenter(
                "RPT_DAILYBILLBOARD_DETAILSNEW",
                filter_str=f'(SECURITY_CODE="{c}")(TRADE_DATE>=\'{from_date}\')',
                page_size=3, sort_columns="TRADE_DATE", sort_types="-1",
            )
            if data:
                latest = data[0]
                ds[c] = {
                    "d": str(latest.get("TRADE_DATE", ""))[:10],
                    "net_wan": round(float(latest.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                    "reason": (latest.get("EXPLANATION") or "")[:40],
                }
        except Exception:
            pass
        time.sleep(0.3)
    return ds

def fetch_block_trades_batch(codes):
    """大宗交易"""
    bt = {}
    for c in (codes or [])[:25]:
        try:
            data = ad.eastmoney_datacenter(
                "RPT_DATA_BLOCKTRADE",
                filter_str=f'(SECURITY_CODE="{c}")',
                page_size=3, sort_columns="TRADE_DATE", sort_types="-1",
            )
            if data:
                latest = data[0]
                close = latest.get("CLOSE_PRICE") or 0
                deal = latest.get("DEAL_PRICE") or 0
                prem = round(((deal / close - 1) * 100), 1) if close else 0
                bt[c] = {
                    "d": str(latest.get("TRADE_DATE", ""))[:10],
                    "prem": prem,
                    "amt": round(float(latest.get("DEAL_AMT") or 0) / 10000, 0),
                    "buyer": (latest.get("BUYER_NAME") or "")[:20],
                }
        except Exception:
            pass
        time.sleep(0.3)
    return bt

def fetch_holder_nums_batch(codes):
    """股东户数"""
    hn = {}
    for c in (codes or [])[:25]:
        try:
            data = ad.eastmoney_datacenter(
                "RPT_HOLDERNUMLATEST",
                filter_str=f'(SECURITY_CODE="{c}")',
                page_size=2, sort_columns="END_DATE", sort_types="-1",
            )
            if data:
                latest = data[0]
                hn[c] = {
                    "d": str(latest.get("END_DATE", ""))[:10],
                    "holders": latest.get("HOLDER_NUM", 0),
                    "chg_pct": round(float(latest.get("HOLDER_NUM_RATIO") or 0), 1),
                }
        except Exception:
            pass
        time.sleep(0.3)
    return hn

def fetch_dividends_batch(codes):
    """分红送转"""
    dh = {}
    for c in (codes or [])[:25]:
        try:
            data = ad.eastmoney_datacenter(
                "RPT_SHAREBONUS_DET",
                filter_str=f'(SECURITY_CODE="{c}")',
                page_size=3, sort_columns="EX_DIVIDEND_DATE", sort_types="-1",
            )
            if data:
                latest = data[0]
                dh[c] = {
                    "d": str(latest.get("EX_DIVIDEND_DATE", ""))[:10],
                    "bonus": round(float(latest.get("PRETAX_BONUS_RMB") or 0), 2),
                    "plan": (latest.get("ASSIGN_PROGRESS") or "")[:20],
                }
        except Exception:
            pass
        time.sleep(0.3)
    return dh

# ═══════════════════════════════════════════════════════════════
# 5. 赛道信号 + 标签
# ═══════════════════════════════════════════════════════════════

OUR_SECTORS = [
    'AI芯片','CPO/光模块','光纤光缆','连接器/铜连接',
    'PCB/覆铜板','MLCC电容','电子树脂/PPE','电子铜箔','HBM/存储芯片',
    'AI服务器/超节点','液冷散热','交换机/网络','电源/DrMOS','数据中心/AIDC',
    '半导体设备','光刻胶','先进封装CoWoS','半导体硅片',
    '六氟化钨WF₆','玻璃基板TGV','培育钻石/散热','超导/核聚变','碳纤维',
    '算电协同','电网设备/特高压','火电/电力运营','算力租赁/GPU云',
    '稀土永磁','钼/小金属','电子特气/工业气体','半导体靶材','AI眼镜/AR硬件',
    'AI应用/模型推理','核电/核能','量子计算/量子科技','卫星互联网/北斗',
    '人形机器人','商业航天','6G/通信','固态电池','低空经济eVTOL','空间计算/物理AI','钨稀土',
    '锂矿/盐湖提锂','锂电池/电解液','光伏/太阳能','风电','储能','新能源汽车',
    '煤炭','黄金/贵金属','铜铝有色','化工','钢铁',
    '银行','券商','保险','房地产开发',
    '白酒','食品饮料','医药/CRO','医疗器械','创新药/CXO','电子布/玻璃纤维'
]

def generate_sector_tags(live, stock_sector, heat_data):
    """生成每个赛道的 emoji+板均涨% 标签"""
    # Compute avg change per sector
    sec_avg = {}
    for key, v in (live or {}).items():
        code = key[2:] if len(key) > 2 else key
        sec = stock_sector.get(code, '')
        if not sec:
            continue
        chg = v.get('chg_pct', 0)
        sec_avg.setdefault(sec, []).append(chg)

    tags = {}
    for our in OUR_SECTORS:
        chgs = sec_avg.get(our, [])
        avg = sum(chgs) / len(chgs) if chgs else 0
        pct_s = '%.1f%%' % abs(avg)
        if avg >= 5:     emoji = '🔥'; prefix = '暴涨 +' + pct_s
        elif avg >= 3:   emoji = '📈'; prefix = '上涨 +' + pct_s
        elif avg >= 1:   emoji = '▲';  prefix = '偏强 +' + pct_s
        elif avg >= -1:  emoji = '➖'; prefix = '平盘'
        elif avg >= -3:  emoji = '▼';  prefix = '偏弱 -' + pct_s
        else:            emoji = '⚡'; prefix = '暴跌 -' + pct_s
        tags[our] = f"{emoji} {prefix} | {our}"
    return tags

def compute_winners_losers(live, stock_sector, heat_data):
    """计算领涨/领跌板块 (含个股明细)"""
    # Group by sector
    sec_stocks = {}
    for key, v in (live or {}).items():
        code = key[2:] if len(key) > 2 else key
        sec = stock_sector.get(code, '')
        if not sec:
            continue
        chg = v.get('chg_pct', 0)
        sec_stocks.setdefault(sec, []).append({
            'c': code, 'n': v.get('name', ''), 'chg': chg
        })

    # Sort heat — 用正则提取数字, 避免脆弱的字符串替换链
    import re as _re
    def _parse_pct(s):
        """从 '+5.7%' 或 '-3.2%' 中提取浮点数"""
        m = _re.search(r'[-+]?\d+\.?\d*', s or '')
        return float(m.group()) if m else 0.0

    sorted_heat = sorted(heat_data, key=lambda x: _parse_pct(x['s']), reverse=True)
    gainers = [h for h in sorted_heat if _parse_pct(h['s']) > 0]
    decliners = [h for h in sorted_heat if _parse_pct(h['s']) < 0]

    def match_sec(em_name):
        """Map EM sector name → our sector name"""
        for our in OUR_SECTORS:
            if len(em_name) >= 2 and len(our) >= 2 and (em_name[:2] in our or our[:2] in em_name):
                return our
        return ''

    winners, losers = [], []
    for h in gainers[:6]:
        m = match_sec(h['n'])
        stks = sec_stocks.get(m, [])
        detail = ' / '.join([f"{s['c']} {s['n']} {s['chg']:+.1f}%" for s in sorted(stks, key=lambda x: -x['chg'])[:6]])
        winners.append({'s': h['n'], 'stks': detail or h['s']})

    for h in reversed(decliners[:6]):
        m = match_sec(h['n'])
        stks = sec_stocks.get(m, [])
        detail = ' / '.join([f"{s['c']} {s['n']} {s['chg']:+.1f}%" for s in sorted(stks, key=lambda x: x['chg'])[:6]])
        losers.append({'s': h['n'], 'stks': detail or h['s']})

    return winners, losers

def auto_cycle(indices):
    """从指数自动判断市场周期"""
    if not indices or len(indices) < 2:
        return {'phase': '数据不足', 'phaseIcon': '📊', 'signals': ['等待数据更新'],
                'riskLevel': 'medium', 'riskLabel': '数据不足', 'suggestion': '等待开盘'}

    major = [i for i in indices if i['n'] in ['上证指数','深证成指','创业板指','沪深300']]
    if not major:
        major = indices[:3]

    try:
        avg_chg = sum(float(i['chg'].replace('%','').replace('+','')) for i in major) / len(major)
        up_count = sum(1 for i in major if i.get('up', False))
    except Exception:
        avg_chg = 0; up_count = 0

    if avg_chg > 1.5 and up_count >= 3:
        return {'phase': '强势上攻', 'phaseIcon': '🔥', 'riskLevel': 'medium',
                'riskLabel': '中等风险', 'suggestion': '趋势良好，可积极布局主线赛道',
                'signals': [f"指数均涨{avg_chg:+.1f}%，{up_count}/{len(major)}上涨"]}
    elif avg_chg > 0.3 and up_count >= 2:
        return {'phase': '震荡偏强', 'phaseIcon': '📈', 'riskLevel': 'low',
                'riskLabel': '较低风险', 'suggestion': '温和上涨，精选个股为主',
                'signals': [f"指数均涨{avg_chg:+.1f}%"]}
    elif avg_chg >= -0.3:
        return {'phase': '窄幅震荡', 'phaseIcon': '⚖️', 'riskLevel': 'medium',
                'riskLabel': '中等风险', 'suggestion': '方向不明确，控制仓位等待信号',
                'signals': [f"指数均涨{avg_chg:+.1f}%"]}
    elif avg_chg >= -1.5:
        return {'phase': '震荡回调', 'phaseIcon': '📉', 'riskLevel': 'medium',
                'riskLabel': '中等风险', 'suggestion': '高位止盈，关注防御板块',
                'signals': [f"指数均跌{abs(avg_chg):.1f}%"]}
    else:
        return {'phase': '恐慌下跌', 'phaseIcon': '🔴', 'riskLevel': 'high',
                'riskLabel': '高风险', 'suggestion': '现金为王，等待企稳信号',
                'signals': [f"指数均跌{abs(avg_chg):.1f}%"]}

# ═══════════════════════════════════════════════════════════════
# 6. 主函数
# ═══════════════════════════════════════════════════════════════

def main():
    cst = now_cst()
    trading = is_trading(cst)
    print(f"=== TTNB Update {cst.strftime('%Y-%m-%d %H:%M CST')} | trading={trading} ===")

    # 0. Load existing data
    old = load_data()
    # bHistory 从独立文件加载
    if os.path.exists(BHISTORY_PATH):
        try:
            with open(BHISTORY_PATH, 'r', encoding='utf-8') as f:
                old['bHistory'] = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    preserve_keys = ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout',
                     'bHistory', 'concepts', 'dynamicSectors', '_eventsMeta', 'sectorTags',
                     '_sectorTracker', '_promoteQueue', '_hot_uncovered', '_backtest']
    # 新闻字段 (_newsSector/_newsMarket/_newsMeta/globalNews) 已迁移到 news.json,
    # 由 news_watch.py 独立管理, 不再写入 data.json
    preserve = {k: old.get(k) for k in preserve_keys if k in old and old.get(k)}
    # Sync root↔briefing: 前端读双路径, AI write 路径可能不同步
    if preserve.get('picks') and not preserve.get('briefing',{}).get('picks'):
        preserve.setdefault('briefing',{})['picks'] = preserve['picks']
    if preserve.get('top3') and not preserve.get('briefing',{}).get('top3'):
        preserve.setdefault('briefing',{})['top3'] = preserve['top3']
    if preserve.get('briefing',{}).get('picks') and not preserve.get('picks'):
        preserve['picks'] = preserve['briefing']['picks']
    if preserve.get('briefing',{}).get('top3') and not preserve.get('top3'):
        preserve['top3'] = preserve['briefing']['top3']
    old_recap = old.get('recap', {})
    old_live = old.get('livePrices', {})
    old_cycle = old_recap.get('cycle')

    # 1. 健康检查 (fast=True 跳过TCP探测，节省启动时间)
    hc = ad.health_check(fast=True)
    # 始终检测通达信（K线/财务/F10是静态数据，周末也能获取，不应受交易时段限制）
    try:
        hc['mootdx'] = ad.tdx_available()
    except Exception as e:
        hc['mootdx'] = False
        print(f"  mootdx检测失败: {e}")
    print(f"  Health: {hc}")
    use_tdx = hc.get('mootdx', False)

    # 2. 提取代码
    codes = codes_from_data(old or {})
    prioritized = priority_code_list(codes, preserve)
    stock_sector = get_sector_mapping()
    print(f"  Codes: {len(codes)} stocks, {len(prioritized)} prioritized, {len(stock_sector)} sector-mapped")

    # ── 3. 实时行情 ──
    print("── L1 行情 ──")
    indices = fetch_indices()
    print(f"  indices: {len(indices)}")

    live = fetch_live_prices(codes, prefer_tdx=use_tdx)
    print(f"  livePrices: {len(live)} stocks")

    heat = fetch_sector_heat(live=live, stock_sector=stock_sector)
    print(f"  heat: {len(heat)} sectors")

    fund = []  # fund flow from industry
    try:
        r = ad.em_get('https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f3,f12,f14,f62', timeout=10)
        items = r.json().get('data',{}).get('diff',[]) or []
        fund = [{'n': i.get('f14',''), 'amt': f"{'+' if float(i.get('f62',0) or 0) > 0 else ''}{abs(float(i.get('f62',0) or 0)) / 100000000:.1f}亿"} for i in items]
    except Exception: pass

    zt = fetch_zt_ladder(cst)
    print(f"  ztLadder: {zt and zt.get('totalCount',0) or 0} stocks")

    lhb = fetch_lhb_full()
    print(f"  lhb: {lhb['total']} stocks")

    # ZT/DT count — L1: 东财全市场扫描 → L2: ztLadder总计数
    zt_count = dt_count = 0
    try:
        r = ad.em_get('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f12,f14', timeout=10)
        items = r.json().get('data',{}).get('diff',[]) or []
        zt_list = [i for i in items if i.get('f3',0) >= 9.9]
        dt_list = [i for i in items if i.get('f3',0) <= -9.9]
        zt_count = len(zt_list)
        dt_count = len(dt_list)
    except Exception:
        # 东财不通用连板池计数兜底
        if zt:
            zt_count = zt.get('totalCount', 0) or 0
        dt_count = 0  # 跌停只能用东财

    winners, losers = compute_winners_losers(live, stock_sector, heat)

    # ── 4. 增强层 ──
    print("── L3 信号 + 资金 ──")
    nb = fetch_northbound()
    print(f"  北向: 沪{nb['hgt_yi']}亿 深{nb['sgt_yi']}亿 净{nb['net_yi']}亿")

    hot = fetch_hot_reasons()
    print(f"  热点归因: {hot.get('total_stocks', 0)}只, {len(hot.get('top_themes', []))}题材")

    # Heavy ops (every 30min) / Free: run every cycle for now
    code_list = prioritized[:120]  # was codes[:80], now prioritized for briefing picks first
    lockup = fetch_lockup_alerts(code_list) if code_list else {"scanned": 0, "alerts": [], "forwardDays": 90}
    print(f"  解禁预警: {lockup['scanned']}只, {len(lockup['alerts'])}批")

    margin = fetch_margin_summary(code_list[:30]) if code_list else {"stocks": [], "status": "无数据"}
    print(f"  融资融券: {len(margin['stocks'])}只")

    # ── 5. Tier A ──
    print("── Tier A ──")
    # 新闻管道(globalNews)由 news_loop 每分钟独立更新, 此处跳过避免覆盖

    ir = fetch_industry_ranking(live=live, stock_sector=stock_sector)
    print(f"  行业排名: {len(ir)}个")

    tv = fetch_tencent_val(code_list)
    print(f"  腾讯估值: {len(tv)}只")

    ca = fetch_cninfo_alerts(code_list[:20]) if code_list else {"alerts": [], "status": "no data"}
    print(f"  巨潮公告: {len(ca.get('alerts',[]))}条")

    irp = fetch_ind_reports()
    print(f"  行业研报: {len(irp.get('reports',[]))}篇")

    # ── 5b. 缺失端点补充 (a-stock-data 28端点全覆盖) ──
    print("── L2/L6 研报+基础 ──")

    # K线数据 (前20只关键标的, 日线最近20根) — mootdx优先, eastmoney HTTP降级
    kline_data = {}
    for c in code_list[:20]:
        kl = None
        # L1: mootdx TCP (最快，不封IP)
        if use_tdx:
            try:
                kl = ad.mootdx_klines(c, category=4, offset=20)
            except Exception as e:
                if len(kline_data) < 3:
                    print(f"    mootdx K线失败 {c}: {e}")
        # L2: eastmoney HTTP 降级 (mootdx不可用或返回空时)
        # 注意: mootdx_klines可能返回DataFrame, 不能用 not kl 做布尔判断
        if kl is None or len(kl) == 0:
            try:
                pfx = ad.get_prefix(c)
                secid = f"{'1' if pfx == 'sh' else '0'}.{c}"
                r = ad.em_get(f'http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=0&lmt=20', timeout=8)
                kls = r.json().get('data', {}).get('klines', []) if r else []
                if kls:
                    kl = []
                    for row in kls[-20:]:
                        parts = row.split(',')
                        if len(parts) >= 7:
                            kl.append({'date': parts[0], 'open': float(parts[1]),
                                       'close': float(parts[2]), 'high': float(parts[3]),
                                       'low': float(parts[4]), 'vol': float(parts[5])})
            except Exception as e:
                if len(kline_data) < 3:
                    print(f"    eastmoney K线降级失败 {c}: {e}")
        if kl is not None and len(kl) > 0:
            # mootdx_klines可能返回DataFrame, 迭代得到列名(str)而非行(dict), 需统一转换
            if hasattr(kl, 'to_dict'):
                kl = kl.to_dict('records')
            kline_data[c] = [{'d': str(r.get('date','')), 'o': float(r.get('open',0)), 'c': float(r.get('close',0)), 'h': float(r.get('high',0)), 'l': float(r.get('low',0)), 'v': float(r.get('vol',0))} for r in kl[-20:]]
    print(f"  K线: {len(kline_data)}只")

    # 一致预期EPS
    eps_data = {}
    for c in code_list[:30]:
        try:
            df = ad.ths_eps_forecast(c)
            if df is not None and not df.empty:
                eps_data[c] = str(df.to_dict())  # 简化序列化
        except Exception: pass
    print(f"  一致预期EPS: {len(eps_data)}只")

    # 个股研报
    report_data = {}
    for c in code_list[:5]:
        try:
            reports = ad.eastmoney_reports(c, max_pages=1)
            if reports:
                report_data[c] = [{'t': r.get('title','')[:80], 'org': r.get('orgSName',''), 'd': str(r.get('publishDate',''))[:10], 'eps': r.get('predictThisYearEps','')} for r in reports[:3]]
        except Exception: pass
    print(f"  个股研报: {len(report_data)}只")

    # 概念板块归属 — 扩大到150只, 加长 sleep 避免风控
    concept_data = {}
    for c in code_list[:150]:
        try:
            blocks = ad.eastmoney_concept_blocks(c)
            if blocks.get('concept_tags'):
                concept_data[c] = blocks['concept_tags'][:10]
        except Exception: pass
        time.sleep(0.15)  # 0.06→0.15, 150只×0.15s≈22s, 避免东财风控
    print(f"  概念板块: {len(concept_data)}只")

    # 新浪三表
    sina_data = {}
    for c in code_list[:20]:
        try:
            lrb = ad.sina_financial_report(c, 'lrb', 4)
            if lrb:
                sina_data[c] = {'利润表': lrb[:4]}
        except Exception: pass
    print(f"  新浪三表: {len(sina_data)}只")

    # F10 公司资料
    f10_data = {}
    if use_tdx:
        for c in code_list[:20]:
            try:
                text = ad.mootdx_f10(c, '公司概况')
                if text and len(str(text)) > 50:
                    f10_data[c] = str(text)[:500]
            except Exception: pass
    print(f"  F10: {len(f10_data)}只")

    # 股东户数
    holder_data = {}
    for c in code_list[:30]:
        try:
            h = ad.holder_num_change(c, 3)
            if h:
                holder_data[c] = [{'d': r['date'], 'num': r.get('holder_num',0), 'chg': r.get('change_ratio',0)} for r in h[:3]]
        except Exception: pass
        time.sleep(0.08)
    print(f"  股东户数: {len(holder_data)}只")

    # 分红送转
    div_data = {}
    for c in code_list[:30]:
        try:
            d = ad.dividend_history(c, 5)
            if d:
                div_data[c] = [{'d': r['date'], 'bonus': r.get('bonus_rmb',0), 'plan': r.get('plan','')} for r in d[:3]]
        except Exception: pass
        time.sleep(0.08)
    print(f"  分红送转: {len(div_data)}只")

    # ── 6. 赛道标签 ──
    sec_tags = generate_sector_tags(live, stock_sector, heat)
    print(f"  sectorTags: {len(sec_tags)}")

    sector_stocks = fetch_sector_stocks(heat, OUR_SECTORS, prefer_tdx=use_tdx)
    pop = sum(1 for v in sector_stocks.values() if v)
    print(f"  sectorStocks: {pop} sectors with stocks")

    # 填充布局卡标的: sector_fixed_stocks.py + 实时价
    if preserve.get('layout'):
        preserve['layout'] = fill_layout_stocks(
            preserve['layout'], sector_stocks, SECTOR_FIXED_STOCKS
        )
        print(f"  layout stocks: filled {len(preserve['layout'])} cards")

    # ── 8. 组装 data.json ──
    # 每次都用最新指数重新生成cycle（不再保留旧判断）
    cycle = auto_cycle(indices) if indices else old_cycle

    # ── 8b. Tushare 增强（替换不稳定东财调用 + 新增资金面维度）──
    tushare_data = {}
    if TUSHARE_AVAILABLE:
        try:
            tushare_data = enrich_data(codes, cst) or {}
            # 如果 tushare 给了更好的数据，覆盖弱数据源
            if tushare_data.get('_tushare_indices') and (not indices or len(indices) < 3):
                indices = tushare_data['_tushare_indices']
                print(f"  [tushare→] 指数降级: 用 tushare 数据")
            if tushare_data.get('_tushare_zt_ladder') and not zt:
                zt = tushare_data['_tushare_zt_ladder']
                print(f"  [tushare→] 连板降级: 用 tushare 数据")
            if tushare_data.get('_tushare_zt_dt'):
                zt_dt = tushare_data['_tushare_zt_dt']
                if not zt_count:
                    zt_count = zt_dt['zt_count']
                if not dt_count:
                    dt_count = zt_dt['dt_count']
        except Exception as e:
            print(f"  [tushare] 增强异常: {e}")

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': '今日 17:00 收盘复盘' if trading else '下个交易日 9:15 开盘扫描',
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices[:6] if indices else old_recap.get('index', [])[:6],
            'heat': heat[:25] if heat else old_recap.get('heat', [])[:25],
            'flow': fund if fund else old_recap.get('flow', []),
            'winners': winners if winners else old_recap.get('winners', []),
            'losers': losers if losers else old_recap.get('losers', []),
            'ztLadder': zt,
            'ztCount': zt_count,
            'dtCount': dt_count,
            'lhb': lhb,
            'cycle': cycle,
            'note': f"{cst.strftime('%m/%d %H:%M')} a-stock-data统一更新 | {len(codes)}只 | {len(heat)}板块"
        },
        'livePrices': live if live else old_live,
        'runtime': {
            'cloud': True, 'autoUpdate': True, 'interval': '5min',
            'stockCount': len(codes), 'liveCount': len(live),
            'updateCount': int(time.time() / 900), 'trading': trading,
        },
        'sectorTags': sec_tags,
        'sectorStocks': sector_stocks,
        'sectorFixedStocks': SECTOR_FIXED_STOCKS,
        # Enriched fields
        'northbound': nb,
        'lhbFull': {'date': lhb['date'], 'total': lhb['total'], 'stocks': lhb.get('topBuy',[])+lhb.get('topSell',[]), 'status': 'ok'},
        'lockupAlerts': lockup,
        'marginSummary': margin,
        '_hotReasons': hot,
        'industryRank': ir,
        'tencentVal': tv,
        'cninfoAlerts': ca,
        'indReports': irp,
        # Health
        '_health': hc,
        # a-stock-data 28端点全覆盖: 研报/财务/K线/概念/新闻
        'klineData': kline_data,
        'epsForecast': eps_data,
        'stockReports': report_data,
        'conceptData': concept_data,
        'sinaReport': sina_data,
        'f10Data': f10_data,
        'holderData': holder_data,
        'dividendData': div_data,
    }

    # Merge preserved fields
    out.update(preserve)

    # ── Merge tushare 增强数据 ──
    if tushare_data:
        out = apply_enrichment(out, tushare_data) if TUSHARE_AVAILABLE else out
        # 额外新增字段（不影响现有数据）
        for key in ['_tushare_moneyflow', '_tushare_meta']:
            if key in tushare_data and tushare_data[key]:
                out[key] = tushare_data[key]

    # Fallback livePrices
    if not live:
        out['livePrices'] = old_live

    # 数据完整性校验（防止静默失败）
    issues = []
    checks = {
        'klineData': (kline_data, 5),
        'f10Data': (f10_data, 5),
    }
    for field, (val, min_n) in checks.items():
        actual = len(val) if val else 0
        if actual < min_n:
            issues.append(f"{field}: {actual}/{min_n}")
    if issues:
        print(f"  ⚠ 数据完整性告警: {'; '.join(issues)}")
        out.setdefault('_health', {})['issues'] = issues
    else:
        print(f"  ✓ 数据完整性校验通过")

    # Write
    save_data(out)

    # Archive at market close — 只存复盘必需字段，不存全量
    if trading and cst.hour == 15 and cst.minute < 45:
        archive_dir = os.path.join(DIR, 'archive')
        os.makedirs(archive_dir, exist_ok=True)
        date_key = cst.strftime('%Y-%m-%d')
        archive_path = os.path.join(archive_dir, f'{date_key}.json')
        # 只存复盘和简报字段，减小 archive 体积
        archive_data = {k: out.get(k) for k in ['recap','top3','picks','briefing','updated'] if k in out}
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        existing = sorted(
            [f.replace('.json','') for f in os.listdir(archive_dir)
             if f.endswith('.json') and f != 'index.json'],
            reverse=True
        )
        with open(os.path.join(archive_dir, 'index.json'), 'w') as f:
            json.dump(existing, f, ensure_ascii=False)
        print(f"📦 Archived: {date_key} ({len(existing)} snapshots)")

    print(f"✅ Done → {DATA_PATH}")
    print(f"   {len(indices)} idx | {len(heat)} sec | {len(live)} stks | "
          f"zt={zt_count} dt={dt_count} | lhb={lhb['total']} | trading={trading}")

if __name__ == '__main__':
    main()
