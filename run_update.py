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

def save_data(d):
    """原子写入 data.json，bHistory 单独写到 briefing-history.json"""
    bHistory = d.pop('bHistory', None)
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)
    # bHistory 独立文件，减少 data.json 体积
    if bHistory is not None:
        btmp = BHISTORY_PATH + '.tmp'
        with open(btmp, 'w', encoding='utf-8') as f:
            json.dump(bHistory, f, ensure_ascii=False, indent=2)
        os.replace(btmp, BHISTORY_PATH)

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

# ═══════════════════════════════════════════════════════════════
# 3b. 多源新闻管道 (新浪4频道 + 东财公告 + 华尔街见闻)
# 原 fetch_news.py 完整逻辑迁移
# ═══════════════════════════════════════════════════════════════

SECTOR_KW = ['六氟化钨','WF6','电子特气','钨矿','钨精矿','钼矿','稀土永磁','钕铁硼','AI芯片','GPU','算力','HBM','CPO','硅光','光模块','光芯片','中际旭创','天孚','新易盛','PCB','覆铜板','MLCC','电容','被动元件','电子树脂','PPE','铜箔','HVLP','存储','佰维','江波龙','液冷','散热','交换机','服务器','超节点','数据中心','AIDC','半导体','光刻胶','先进封装','CoWoS','硅片','靶材','机器人','Optimus','宇树','绿的谐波','拓普','商业航天','SpaceX','千帆','卫星','朱雀','固态电池','低空经济','eVTOL','电网设备','特高压','火电','变压器','风电','光伏','储能','锂矿','锂电池','新能源车','电解液','隔膜','煤炭','黄金','铜','铝','钢铁','化工','银行','券商','保险','白酒','茅台','医药','CRO','医疗器械','钼','钨','稀土','小金属','核能','量子','AI眼镜','6G','连接器','电源','DrMOS','培育钻石','碳纤维','锂矿','盐湖提锂','钠电池','锰','钒电池']
MARKET_KW = ['A股','沪指','深指','创业板','科创板','沪深300','涨停','跌停','北向资金','主力资金','机构','游资','ETF','央行','降息','降准','LPR','MLF','社融','M2','证监会','交易所','国常会','国务院','发改委','工信部','人民币','汇率','美元','美联储','FOMC','GDP','PMI','CPI','PPI','半年报','年报','季报','业绩预告','分红','回购','增持','减持','解禁','牛市','熊市','美股','港股','纳指','标普','道指','非农','美债','地缘','中东','俄罗斯','伊朗','朝鲜','关税','制裁','英伟达','苹果','微软','谷歌','特斯拉','亚马逊','Meta','台积电','三星','SK海力士','ASML','原油','布伦特','WTI','黄金期货','LME','IPO','并购重组','万亿']
NOISE_KW = ['足球','世界杯','奥运','NBA','英超','欧冠','比赛','联赛','明星','婚礼','离婚','八卦','娱乐','综艺','唱歌','电影','天气预报','地震','洪水','动物','猫','狗','熊猫','围棋','象棋','电竞','游戏','手游']

def _fetch_json(url, timeout=10):
    from urllib.request import Request, urlopen
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': 'https://finance.sina.com.cn/'})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', errors='replace'))
    except: return None

def fetch_sina_news():
    cst = now_cst()
    sector_news, market_news = [], []
    channels = [('2512','股票'), ('2516','A股'), ('2509','7x24财经'), ('1689','产业')]
    for ch_id, ch_name in channels:
        url = f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid={ch_id}&k=&num=60&page=1&r={time.time()}'
        data = _fetch_json(url)
        if not data or not data.get('result'): continue
        for it in data['result'].get('data', []):
            title = it.get('title','') or it.get('intro','')
            if not title or any(kw in title for kw in NOISE_KW): continue
            try: ts = datetime.fromtimestamp(int(it.get('ctime','0')), tz=timezone.utc) + timedelta(hours=8)
            except: ts = cst
            age_h = (cst - ts).total_seconds() / 3600
            max_age = 0.5 if (9 <= cst.hour < 15 and cst.weekday() < 5) else 24
            if age_h > max_age: continue
            entry = {'t': title.strip()[:120], 'u': it.get('url',''), 'time': ts.strftime('%H:%M'), 'src': 'sina_'+ch_name}
            if any(kw in title for kw in SECTOR_KW): sector_news.append(entry)
            elif any(kw in title for kw in MARKET_KW): market_news.append(entry)
    return sector_news, market_news

def fetch_em_announcements():
    SIG_WORDS = ['业绩','盈利','亏损','分红','回购','增持','减持','重组','停牌','退市','上市','首发','IPO','非公开','配股','质押','冻结','拍卖','预亏','预增','扭亏','合同','中标','重大','诉讼','*ST','ST','股权转让','要约','收购','合并','涨价','停产','限产','减产','投产','量产','获批','通过']
    SKIP_WORDS = ['董事会第','监事会第','独立董事','审计委员会','薪酬与考核','制度修订','工作细则','管理制度','信息知情人','防控控股','网上申购','中签率']
    sector_news, market_news = [], []
    for ann_type in ['A','SFA','SHA']:
        url = f'https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=40&page_index=1&ann_type={ann_type}&sr=-1&client_source=web'
        data = _fetch_json(url)
        if not data or data.get('success') != 1: continue
        for it in data.get('data',{}).get('list',[]):
            title = it.get('title','') or ''
            if any(w in title for w in SKIP_WORDS) or not any(w in title for w in SIG_WORDS): continue
            codes = it.get('codes',[])
            stock_code = codes[0].get('stock_code','') if codes else ''
            stock_name = codes[0].get('short_name','') if codes else ''
            date_str = (it.get('notice_date','') or '')[:10]
            entry = {'t': f'{stock_name}: {title[:90]}' if stock_name else title[:110], 'u': f'https://data.eastmoney.com/notices/detail/{stock_code}.html' if stock_code else '', 'time': date_str[-5:] if len(date_str)>=5 else date_str, 'src': 'em_announcement'}
            if any(kw in title for kw in SECTOR_KW): sector_news.append(entry)
            else: market_news.append(entry)
    return sector_news, market_news

def fetch_wallstreetcn():
    cst = now_cst()
    all_news = []
    for ch, ch_name in [('global-channel','全球'), ('china-channel','中国')]:
        url = f'https://api-one.wallstcn.com/apiv1/content/lives?channel={ch}&client=pc&limit=40&first=1'
        data = _fetch_json(url, timeout=10)
        if not data or not data.get('data'): continue
        for it in data['data'].get('items',[]):
            title = it.get('title','') or it.get('content_text','') or ''
            url_link = it.get('uri','') or ''
            if url_link and not url_link.startswith('http'): url_link = 'https://wallstreetcn.com' + url_link
            try: ts = datetime.fromtimestamp(it.get('display_time',0) or 0, tz=timezone.utc) + timedelta(hours=8)
            except: ts = cst
            age_h = (cst - ts).total_seconds() / 3600
            max_age = 0.5 if (9 <= cst.hour < 15 and cst.weekday() < 5) else 24
            if age_h > max_age: continue
            if not (any(kw in title for kw in SECTOR_KW) or any(kw in title for kw in MARKET_KW)): continue
            all_news.append({'t': title.strip()[:120], 'u': url_link, 'time': ts.strftime('%H:%M'), 'src': 'wscn_'+ch_name})
        time.sleep(0.3)
    return all_news

def _dedup(news_list):
    seen = set(); result = []
    for n in news_list:
        key = n['t'][:50]
        if key not in seen: seen.add(key); result.append(n)
    result.sort(key=lambda n: n.get('time',''), reverse=True)
    return result

def fetch_all_news():
    sina_s, sina_m = fetch_sina_news()
    em_s, em_m = fetch_em_announcements()
    wscn = fetch_wallstreetcn()
    sector_all = _dedup(sina_s + em_s)
    market_all = _dedup(sina_m + em_m + wscn)
    return sector_all[:50], market_all[:50]

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

    # ZT/DT count — L1: 东财全市场扫描 → L2: ztLadder总计数
    zt_count = dt_count = 0
    try:
        r = ad.em_get('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f12,f14', timeout=10)
        items = r.json().get('data',{}).get('diff',[]) or []
        zt_list = [i for i in items if i.get('f3',0) >= 9.9]
        dt_list = [i for i in items if i.get('f3',0) <= -9.9]
        zt_count = len(zt_list)
        dt_count = len(dt_list)
    except:
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
    code_list = codes[:80]
    lockup = fetch_lockup_alerts(code_list) if code_list else {"scanned": 0, "alerts": [], "forwardDays": 90}
    print(f"  解禁预警: {lockup['scanned']}只, {len(lockup['alerts'])}批")

    margin = fetch_margin_summary(code_list[:30]) if code_list else {"stocks": [], "status": "无数据"}
    print(f"  融资融券: {len(margin['stocks'])}只")

    # ── 5. Tier A ──
    print("── Tier A ──")
    gn = fetch_global_news()
    print(f"  全球资讯: {len(gn['headlines'])}条")

    # 多源新闻管道: 新浪4频道 + 东财公告 + 华尔街见闻
    ns_sector, ns_market = fetch_all_news()
    print(f"  赛道新闻: {len(ns_sector)}条, 市场新闻: {len(ns_market)}条")

    ir = fetch_industry_ranking(live=live, stock_sector=stock_sector)
    print(f"  行业排名: {len(ir)}个")

    tv = fetch_tencent_val(code_list)
    print(f"  腾讯估值: {len(tv)}只")

    ca = fetch_cninfo_alerts(code_list[:5]) if code_list else {"alerts": [], "status": "no data"}
    print(f"  巨潮公告: {len(ca.get('alerts',[]))}条")

    irp = fetch_ind_reports()
    print(f"  行业研报: {len(irp.get('reports',[]))}篇")

    # ── 5b. 缺失端点补充 (a-stock-data 28端点全覆盖) ──
    print("── L2/L6 研报+基础 ──")

    # K线数据 (前5只关键标的, 日线最近20根)
    kline_data = {}
    for c in code_list[:5]:
        try:
            kl = ad.mootdx_klines(c, category=4, offset=20)
            if kl is not None and len(kl) > 0:
                kline_data[c] = [{'d': str(r.get('date','')), 'o': float(r.get('open',0)), 'c': float(r.get('close',0)), 'h': float(r.get('high',0)), 'l': float(r.get('low',0)), 'v': float(r.get('vol',0))} for r in kl[-20:]]
        except: pass
    print(f"  K线: {len(kline_data)}只")

    # 一致预期EPS
    eps_data = {}
    for c in code_list[:10]:
        try:
            df = ad.ths_eps_forecast(c)
            if df is not None and not df.empty:
                eps_data[c] = str(df.to_dict())  # 简化序列化
        except: pass
    print(f"  一致预期EPS: {len(eps_data)}只")

    # 财务快照
    fin_data = {}
    if use_tdx:
        for c in code_list[:5]:
            try:
                fin = ad.mootdx_finance(c)
                if fin:
                    fin_data[c] = {k: str(v) for k, v in fin.items() if k in ['eps','roe','bvps','profit','income','liutongguben','zongguben']}
            except: pass
    print(f"  财务快照: {len(fin_data)}只 (tdx={use_tdx})")

    # 个股研报
    report_data = {}
    for c in code_list[:5]:
        try:
            reports = ad.eastmoney_reports(c, max_pages=1)
            if reports:
                report_data[c] = [{'t': r.get('title','')[:80], 'org': r.get('orgSName',''), 'd': str(r.get('publishDate',''))[:10], 'eps': r.get('predictThisYearEps','')} for r in reports[:3]]
        except: pass
    print(f"  个股研报: {len(report_data)}只")

    # 概念板块归属
    concept_data = {}
    for c in code_list[:50]:
        try:
            blocks = ad.eastmoney_concept_blocks(c)
            if blocks.get('concept_tags'):
                concept_data[c] = blocks['concept_tags'][:10]
        except: pass
        time.sleep(0.1)
    print(f"  概念板块: {len(concept_data)}只")

    # 个股新闻
    stock_news_data = {}
    for c in code_list[:10]:
        try:
            news = ad.eastmoney_stock_news(c, 5)
            if news:
                stock_news_data[c] = [{'t': n['title'][:80], 'ts': n['time'], 'src': n['source']} for n in news[:3]]
        except: pass
        time.sleep(0.1)
    print(f"  个股新闻: {len(stock_news_data)}只")

    # 新浪三表
    sina_data = {}
    for c in code_list[:5]:
        try:
            lrb = ad.sina_financial_report(c, 'lrb', 4)
            if lrb:
                sina_data[c] = {'利润表': lrb[:4]}
        except: pass
    print(f"  新浪三表: {len(sina_data)}只")

    # F10 公司资料
    f10_data = {}
    if use_tdx:
        for c in code_list[:5]:
            try:
                text = ad.mootdx_f10(c, '公司概况')
                if text and len(str(text)) > 50:
                    f10_data[c] = str(text)[:500]
            except: pass
    print(f"  F10: {len(f10_data)}只")

    # 股东户数
    holder_data = {}
    for c in code_list[:10]:
        try:
            h = ad.holder_num_change(c, 3)
            if h:
                holder_data[c] = [{'d': r['date'], 'num': r.get('holder_num',0), 'chg': r.get('change_ratio',0)} for r in h[:3]]
        except: pass
        time.sleep(0.15)
    print(f"  股东户数: {len(holder_data)}只")

    # 分红送转
    div_data = {}
    for c in code_list[:10]:
        try:
            d = ad.dividend_history(c, 5)
            if d:
                div_data[c] = [{'d': r['date'], 'bonus': r.get('bonus_rmb',0), 'plan': r.get('plan','')} for r in d[:3]]
        except: pass
        time.sleep(0.15)
    print(f"  分红送转: {len(div_data)}只")

    # ── 6. 赛道标签 ──
    sec_tags = generate_sector_tags(live, stock_sector, heat)
    print(f"  sectorTags: {len(sec_tags)}")

    sector_stocks = fetch_sector_stocks(heat, OUR_SECTORS, prefer_tdx=use_tdx)
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
        'sectorFixedStocks': SECTOR_FIXED_STOCKS,
        # Enriched fields
        'northbound': nb,
        'lhbFull': {'date': lhb['date'], 'total': lhb['total'], 'stocks': lhb.get('topBuy',[])+lhb.get('topSell',[]), 'status': 'ok'},
        'lockupAlerts': lockup,
        'marginSummary': margin,
        '_hotReasons': hot,
        'globalNews': gn,
        '_newsSector': ns_sector,
        '_newsMarket': ns_market,
        '_newsMeta': {'updated': cst.strftime('%Y-%m-%d %H:%M CST'), 'sector': len(ns_sector), 'market': len(ns_market)},
        'industryRank': ir,
        'tencentVal': tv,
        'cninfoAlerts': ca,
        'indReports': irp,
        # Health
        '_health': hc,
        # a-stock-data 28端点全覆盖: 研报/财务/K线/概念/新闻
        'klineData': kline_data,
        'epsForecast': eps_data,
        'finSnapshot': fin_data,
        'stockReports': report_data,
        'conceptData': concept_data,
        'stockNewsData': stock_news_data,
        'sinaReport': sina_data,
        'f10Data': f10_data,
        'holderData': holder_data,
        'dividendData': div_data,
    }

    # Merge preserved fields
    out.update(preserve)

    # Fallback livePrices
    if not live:
        out['livePrices'] = old_live

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
