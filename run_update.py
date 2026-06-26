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

DATA_PATH = os.path.join(DIR, 'data.json')
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

def save_data(d):
    """原子写入 data.json"""
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)

def codes_from_data(d):
    """从 data.json 提取所有6位代码"""
    codes = set()
    for lev in d.get('layout', []):
        for s in lev.get('stocks', []):
            parts = (s or '').split()
            if parts and len(parts[0]) == 6:
                codes.add(parts[0])
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
    return cst.weekday() < 5 and 9 <= cst.hour < 15

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
    优先级: 东财 push2 行业板块 → 从个股现价自算
    """
    # L1: 东财行业板块 (独有数据，但可能被风控)
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
        if sectors:
            return sectors

    # L2 降级: 从个股现价自算赛道平均涨跌
    if live and stock_sector:
        return ad.compute_sector_heat_from_stocks(live, stock_sector)

    return []

def fetch_sector_stocks(heat_data, our_names):
    """每个赛道从东财板块API拉取领涨股"""
    # Build board name → code
    name_to_bcode = {h['n']: h.get('bk', '') for h in heat_data if h.get('bk')}

    # Build all boards list
    all_boards = {}
    for mkt in ['m:90+t:3', 'm:90+t:2']:
        try:
            url = f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs={mkt}&fields=f2,f3,f12,f14"
            r = ad.em_get(url, timeout=10)
            for h in r.json().get('data', {}).get('diff', []):
                n = h.get('f14', '')
                if n and n not in all_boards:
                    all_boards[n] = h.get('f12', '')
        except:
            pass

    def find_bcode(sec_name):
        # Direct match
        if sec_name in name_to_bcode:
            return name_to_bcode[sec_name]
        # Substring
        for bn, bc in name_to_bcode.items():
            if len(sec_name) >= 2 and sec_name[:2] in bn:
                return bc
        # All boards
        for bn, bc in all_boards.items():
            if len(sec_name) >= 2 and sec_name[:2] in bn:
                return bc
        return ''

    result = {}
    for sec in our_names:
        bcode = find_bcode(sec)
        if not bcode:
            result[sec] = []
            continue

        stocks = []
        try:
            url = f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=25&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:{bcode}&fields=f2,f3,f12,f14"
            r = ad.em_get(url, timeout=10)
            for s in r.json().get('data', {}).get('diff', []):
                code = s.get('f12', '')
                name = s.get('f14', '')
                chg = s.get('f3', 0)
                if code and name:
                    stocks.append({'c': code, 'n': name, 'chg': round(chg, 1)})
        except:
            pass

        stocks.sort(key=lambda x: x['chg'], reverse=True)
        cyb_kcb = [s for s in stocks if s['c'].startswith(('300','301','688','689'))]
        main_bd = [s for s in stocks if s['c'].startswith(('600','601','603','605','000','001','002','003'))]
        filtered = cyb_kcb[:3] + main_bd
        filtered.sort(key=lambda x: x['chg'], reverse=True)
        up_stocks = [s for s in filtered if s['chg'] > 0]
        if len(up_stocks) >= 3:
            filtered = up_stocks
        result[sec] = filtered[:8]
    return result

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
    except:
        return {"date": "", "hgt_yi": 0, "sgt_yi": 0, "net_yi": 0, "points": 0, "status": "无数据"}

def fetch_hot_reasons():
    """同花顺热点归因"""
    data = ad.get_hot_sector_themes()
    if isinstance(data, dict):
        hs = data.get('hot_stocks', [])
        tt = data.get('top_themes', [])
        data['total'] = len(hs)
        data['topReasons'] = tt
        data['stocks'] = hs
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
        except:
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
        except:
            pass
    summary.sort(key=lambda x: -x['change_5d'])
    return {"stocks": summary, "status": "ok" if summary else "无数据"}

# ═══════════════════════════════════════════════════════════════
# 3. Tier A — 全球资讯/行业排名/腾讯估值/公告/研报
# ═══════════════════════════════════════════════════════════════

def fetch_global_news():
    """东财7x24全球资讯"""
    news = ad.eastmoney_global_news(25)
    return {
        "headlines": [{"t": n['title'][:130], "s": n['summary'][:90], "ts": n['time']} for n in news],
        "updated": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        "status": "ok" if news else "empty"
    }

def fetch_industry_ranking(live=None, stock_sector=None):
    """
    行业板块排名 — 优先级: 东财 → 个股聚合降级
    """
    comp = ad.industry_comparison(80)
    if comp['total'] > 0:
        return [{
            "n": r['name'], "chg": round(r['change_pct'] or 0, 2),
            "upCnt": r.get('up_count', 0) or 0, "dnCnt": r.get('down_count', 0) or 0,
            "ld": r.get('leader', '') or '', "bk": r.get('code', '')
        } for r in (comp['top'] + comp['bottom'])]

    # 降级: 从个股现价自算
    if live and stock_sector:
        heat = ad.compute_sector_heat_from_stocks(live, stock_sector)
        return [{"n": h['n'], "chg": float(h['s'].replace('%','').replace('+','')),
                 "upCnt": 0, "dnCnt": 0, "ld": "", "bk": h.get('bk','')}
                for h in heat[:80]]
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
    for code in (codes or [])[:5]:
        time.sleep(0.5)
        try:
            anns = ad.cninfo_announcements(code, 3)
            for a in anns[:3]:
                alerts.append({'c': code, 't': a['title'][:100], 'd': a['date']})
        except:
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
        except:
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
        except:
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
        except:
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
        except:
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
        except:
            pass
        time.sleep(0.3)
    return ff

def fetch_dragon_seats_batch(codes):
    """龙虎榜席位(个股)"""
    ds = {}
    for c in (codes or [])[:25]:
        try:
            data = ad.eastmoney_datacenter(
                "RPT_DAILYBILLBOARD_DETAILSNEW",
                filter_str=f'(SECURITY_CODE="{c}")(TRADE_DATE>=\'2026-06-01\')',
                page_size=3, sort_columns="TRADE_DATE", sort_types="-1",
            )
            if data:
                latest = data[0]
                ds[c] = {
                    "d": str(latest.get("TRADE_DATE", ""))[:10],
                    "net_wan": round(float(latest.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                    "reason": (latest.get("EXPLANATION") or "")[:40],
                }
        except:
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
        except:
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
        except:
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
        except:
            pass
        time.sleep(0.3)
    return dh

# ═══════════════════════════════════════════════════════════════
# 5. 赛道信号 + 标签
# ═══════════════════════════════════════════════════════════════

OUR_SECTORS = [
    'AI芯片','CPO/硅光','光模块','光纤光缆','连接器/铜连接',
    'PCB/覆铜板','MLCC电容','电子树脂/PPE','电子铜箔','HBM/存储芯片',
    'AI服务器/超节点','液冷散热','交换机/网络','电源/DrMOS','数据中心/AIDC',
    '半导体设备','光刻胶','先进封装CoWoS','半导体硅片',
    '六氟化钨WF₆','玻璃基板TGV','培育钻石/散热','超导/核聚变','碳纤维',
    '算电协同','电网设备/特高压','火电/电力运营','算力租赁/GPU云','Token工厂/模型推理',
    '稀土永磁','钼/小金属','电子特气/工业气体','半导体靶材','AI眼镜/AR硬件',
    'AI智能体/应用','核电/核能','量子计算/量子科技','卫星互联网/北斗',
    '人形机器人','商业航天','6G/通信','固态电池','低空经济eVTOL','空间计算/物理AI','钨稀土',
    '锂矿/盐湖提锂','锂电池/电解液','光伏/太阳能','风电','储能','新能源汽车',
    '煤炭','黄金/贵金属','铜铝有色','化工','钢铁',
    '银行','券商','保险','房地产开发',
    '白酒','食品饮料','医药/CRO','医疗器械'
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
        if avg >= 5: emoji = '🔥'; prefix = '板均涨' + pct_s
        elif avg >= 3: emoji = '🔥'; prefix = '板均涨' + pct_s
        elif avg >= 1: emoji = '🟢'; prefix = '偏强 +' + pct_s
        elif avg >= -1: emoji = '🟡'; prefix = '平盘'
        elif avg >= -3: emoji = '🔴'; prefix = '偏弱 -' + pct_s
        else: emoji = '🔴'; prefix = '回调 -' + pct_s
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

    # Sort heat
    sorted_heat = sorted(heat_data, key=lambda x:
        float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)
    gainers = [h for h in sorted_heat if float(h['s'].replace('%','').replace('+','')) > 0]
    decliners = [h for h in sorted_heat if float(h['s'].replace('%','').replace('+','')) < 0]

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
    except:
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
    preserve_keys = ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout',
                     'bHistory', 'concepts', 'dynamicSectors', '_newsSector',
                     '_newsMarket', '_newsMeta', '_eventsMeta', 'sectorTags',
                     '_sectorTracker', '_promoteQueue', '_hot_uncovered', '_backtest']
    preserve = {k: old.get(k) for k in preserve_keys if k in old and old.get(k)}
    old_recap = old.get('recap', {})
    old_live = old.get('livePrices', {})
    old_cycle = old_recap.get('cycle')

    # 1. 健康检查 (fast=True 跳过TCP探测，节省启动时间)
    hc = ad.health_check(fast=True)
    # 交易时段再认真测通达信
    if trading:
        try:
            hc['mootdx'] = ad.tdx_available()
        except:
            pass
    print(f"  Health: {hc}")
    use_tdx = hc.get('mootdx', False)

    # 2. 提取代码
    codes = codes_from_data(old or {})
    stock_sector = get_sector_mapping()
    print(f"  Codes: {len(codes)} stocks, {len(stock_sector)} sector-mapped")

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
    except: pass

    zt = fetch_zt_ladder(cst)
    print(f"  ztLadder: {zt and zt.get('totalCount',0) or 0} stocks")

    lhb = fetch_lhb_full()
    print(f"  lhb: {lhb['total']} stocks")

    # ZT/DT count from clist
    zt_count = dt_count = 0
    try:
        r = ad.em_get('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f12,f14', timeout=10)
        items = r.json().get('data',{}).get('diff',[]) or []
        zt_list = [i for i in items if i.get('f3',0) >= 9.9]
        dt_list = [i for i in items if i.get('f3',0) <= -9.9]
        zt_count = len(zt_list)
        dt_count = len(dt_list)
    except: pass

    winners, losers = compute_winners_losers(live, stock_sector, heat)

    # ── 4. 增强层 ──
    print("── L3 信号 + 资金 ──")
    nb = fetch_northbound()
    print(f"  北向: 沪{nb['hgt_yi']}亿 深{nb['sgt_yi']}亿 净{nb['net_yi']}亿")

    hot = fetch_hot_reasons()
    print(f"  热点归因: {hot.get('total_stocks', 0)}只, {len(hot.get('top_themes', []))}题材")

    # Heavy ops (every 30min) / Free: run every cycle for now
    code_list = codes[:80]
    lockup = fetch_lockup_alerts(code_list) if code_list else {"scanned": 0, "alerts": [], "forwardDays": 90}
    print(f"  解禁预警: {lockup['scanned']}只, {len(lockup['alerts'])}批")

    margin = fetch_margin_summary(code_list[:30]) if code_list else {"stocks": [], "status": "无数据"}
    print(f"  融资融券: {len(margin['stocks'])}只")

    # ── 5. Tier A ──
    print("── Tier A ──")
    gn = fetch_global_news()
    print(f"  全球资讯: {len(gn['headlines'])}条")

    ir = fetch_industry_ranking(live=live, stock_sector=stock_sector)
    print(f"  行业排名: {len(ir)}个")

    tv = fetch_tencent_val(code_list)
    print(f"  腾讯估值: {len(tv)}只")

    ca = fetch_cninfo_alerts(code_list[:5]) if code_list else {"alerts": [], "status": "no data"}
    print(f"  巨潮公告: {len(ca.get('alerts',[]))}条")

    irp = fetch_ind_reports()
    print(f"  行业研报: {len(irp.get('reports',[]))}篇")

    # ── 6. 赛道标签 ──
    sec_tags = generate_sector_tags(live, stock_sector, heat)
    print(f"  sectorTags: {len(sec_tags)}")

    sector_stocks = fetch_sector_stocks(heat, OUR_SECTORS)
    pop = sum(1 for v in sector_stocks.values() if v)
    print(f"  sectorStocks: {pop} sectors with stocks")

    # ── 8. 组装 data.json ──
    cycle = old_cycle or auto_cycle(indices)

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
        # Enriched fields
        'northbound': nb,
        'lhbFull': {'date': lhb['date'], 'total': lhb['total'], 'stocks': lhb.get('topBuy',[])+lhb.get('topSell',[]), 'status': 'ok'},
        'lockupAlerts': lockup,
        'marginSummary': margin,
        '_hotReasons': hot,
        'globalNews': gn,
        'industryRank': ir,
        'tencentVal': tv,
        'cninfoAlerts': ca,
        'indReports': irp,
        # Health
        '_health': hc,
    }

    # Merge preserved fields
    out.update(preserve)

    # Fallback livePrices
    if not live:
        out['livePrices'] = old_live

    # Write
    save_data(out)

    # Archive at market close
    if trading and cst.hour == 15 and cst.minute < 45:
        archive_dir = os.path.join(DIR, 'archive')
        os.makedirs(archive_dir, exist_ok=True)
        date_key = cst.strftime('%Y-%m-%d')
        archive_path = os.path.join(archive_dir, f'{date_key}.json')
        shutil.copy2(DATA_PATH, archive_path)
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
