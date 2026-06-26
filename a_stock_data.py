#!/usr/bin/env python3
"""
a-stock-data — A股全栈数据模块 V1.0
来源: simonlin1212/a-stock-data SKILL.md V3.2.4 (Apache 2.0)
提取所有28个端点实测代码，内置降级链：通达信 > 腾讯 > 同花顺 > 东财 > 新浪

七层架构:
  L1 行情: mootdx(TCP) + 腾讯(HTTP) + 百度K线 → 三源互备
  L2 研报: 东财reportapi + 同花顺THS + iwencai
  L3 信号: 同花顺热点 + 北向 + 东财slist/push2/龙虎榜/解禁/行业排名
  L4 资金: 融资融券 + 大宗 + 股东户数 + 分红 + 资金流120日
  L5 新闻: 东财个股新闻 + 全球资讯7x24
  L6 基础: mootdx财务/F10 + 东财个股信息 + 新浪三表
  L7 公告: 巨潮cninfo + mootdx F10摘要

优先级原则 (来自上游设计):
  通达信(TCP,不封IP) > 腾讯(HTTP,不封IP) > 同花顺(低风险) > 东财(有风控,限流) > 新浪(兜底)
"""

import json, os, re, time, random, socket, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
UA_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 通达信备用服务器 (2026-06 验证可用)
_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]

# 东财数据中心 base URL
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ═══════════════════════════════════════════════════════════════
# 0. 基础设施 — mootdx 客户端 + 东财限流 + 代码工具
# ═══════════════════════════════════════════════════════════════

# ── mootdx 客户端 (规避 0.11.x BESTIP 空串 bug) ──
def _probe_tdx(ip, port, timeout=2.0):
    """TCP 握手探测"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

_tdx_client_cache = None

def tdx_client(market='std'):
    """创建 mootdx 客户端，顺序探测 → bestip → 裸 factory"""
    global _tdx_client_cache
    if _tdx_client_cache is not None:
        return _tdx_client_cache
    try:
        from mootdx.quotes import Quotes
        for ip, port in _TDX_SERVERS:
            if _probe_tdx(ip, port):
                _tdx_client_cache = Quotes.factory(market=market, server=(ip, port))
                return _tdx_client_cache
        try:
            _tdx_client_cache = Quotes.factory(market=market, bestip=True)
            return _tdx_client_cache
        except Exception:
            pass
        _tdx_client_cache = Quotes.factory(market=market)
        return _tdx_client_cache
    except Exception as e:
        raise RuntimeError(f"所有 mootdx 服务器不可达: {e}")

def tdx_available():
    """检查通达信是否可达"""
    try:
        tdx_client()
        return True
    except Exception:
        return False


# ── 东财防封：全局节流 + 会话复用 ──
try:
    import requests as _requests
    EM_SESSION = _requests.Session()
    EM_SESSION.headers.update({"User-Agent": UA})
    HAS_REQUESTS = True
except ImportError:
    EM_SESSION = None
    HAS_REQUESTS = False

EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA"""
    if not HAS_REQUESTS:
        return _em_get_urllib(url, params, headers, timeout)
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        if headers:
            h = dict(EM_SESSION.headers)
            h.update(headers)
        else:
            h = None
        return EM_SESSION.get(url, params=params, headers=h, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

def _em_get_urllib(url, params=None, headers=None, timeout=15):
    """urllib fallback for em_get"""
    from urllib.request import Request, urlopen
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        if params:
            from urllib.parse import urlencode
            url = url + '?' + urlencode(params)
        hdrs = {'User-Agent': UA}
        if headers:
            hdrs.update(headers)
        req = Request(url, headers=hdrs)
        with urlopen(req, timeout=timeout) as r:
            from io import BytesIO
            import io
            class FakeResponse:
                def __init__(self, data, status):
                    self._data = data
                    self.status_code = status
                    self.text = data.decode('utf-8', errors='replace')
                def json(self):
                    return json.loads(self.text)
            return FakeResponse(r.read(), r.status)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name, columns="ALL", filter_str="",
                          page_size=50, sort_columns="", sort_types="-1"):
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ── 代码工具 ──
def get_prefix(code):
    """6位代码 → 市场前缀"""
    code = str(code).replace("SH","").replace("SZ","").replace("BJ","").replace(".sh","").replace(".sz","").replace(".bj","")
    code = code[:6]
    if code.startswith(("6", "9")): return "sh"
    elif code.startswith("8"): return "bj"
    return "sz"

def normalize_code(code):
    """任意格式 → 纯6位数字"""
    return str(code).replace("SH","").replace("SZ","").replace("BJ","").replace(".sh","").replace(".sz","").replace(".bj","")[:6]


# ═══════════════════════════════════════════════════════════════
# Layer 1: 行情层 (实时，不封IP)
# ═══════════════════════════════════════════════════════════════

# ── 1.1 mootdx — K线 + 五档盘口 + 逐笔成交 ──
def mootdx_klines(symbol, category=4, offset=10):
    """通达信K线。category: 4=日线,5=周线,6=月线"""
    client = tdx_client()
    result = client.bars(symbol=str(symbol)[:6], category=category, offset=offset)
    if result is not None and len(result) > 0:
        return result
    return None

def mootdx_quotes(symbols):
    """通达信实时报价 (46字段包括五档盘口)。返回 {code: {...}} 或 None"""
    try:
        client = tdx_client()
        codes = [str(s)[:6] for s in symbols[:80]]
        result = client.quotes(symbol=codes)
        if result is not None and len(result) > 0:
            out = {}
            for row in result:
                code = str(row.get('code', ''))
                if code:
                    out[code] = {
                        'price': row.get('price', 0),
                        'open': row.get('open', 0),
                        'high': row.get('high', 0),
                        'low': row.get('low', 0),
                        'last_close': row.get('last_close', 0),
                        'vol': row.get('vol', 0),
                        'amount': row.get('amount', 0),
                        'bid1': row.get('bid1', 0), 'ask1': row.get('ask1', 0),
                        'bid_vol1': row.get('bid_vol1', 0), 'ask_vol1': row.get('ask_vol1', 0),
                        'server_time': str(row.get('servertime', '')),
                    }
            return out
    except Exception:
        pass
    return None

def mootdx_finance(symbol):
    """通达信季报快照 (37字段: EPS/ROE/净利/营收等)"""
    client = tdx_client()
    market = 1 if str(symbol)[:1] in ('6','9') else 0
    return client.finance(symbol=str(symbol)[:6])

def mootdx_f10(symbol, category='最新提示'):
    """通达信 F10 公司文本资料"""
    client = tdx_client()
    return client.F10(symbol=str(symbol)[:6], name=category)


# ── 1.2 腾讯财经 — PE/PB/市值/换手率/涨跌停/指数/ETF ──
def tencent_quote(codes):
    """
    腾讯财经批量行情。返回 {code: {name,price,pe_ttm,pb,mcap,...}}
    不封IP，HTTP GBK编码。
    """
    from urllib.request import Request, urlopen
    if not codes:
        return {}
    prefixed = []
    for c in codes:
        c = normalize_code(c)
        p = get_prefix(c)
        prefixed.append(f"{p}{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    try:
        req = Request(url)
        req.add_header("User-Agent", UA)
        resp = urlopen(req, timeout=10)
        data = resp.read().decode("gbk", errors='replace')
    except Exception:
        return {}

    result = {}
    for line in data.strip().split("\n"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = vals[2]
        if not code or len(code) != 6:
            continue
        try:
            result[code] = {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "last_close": float(vals[4]) if vals[4] else 0,
                "open": float(vals[5]) if vals[5] else 0,
                "change_amt": float(vals[31]) if vals[31] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "high": float(vals[33]) if vals[33] else 0,
                "low": float(vals[34]) if vals[34] else 0,
                "amount_wan": float(vals[37]) if vals[37] else 0,
                "turnover_pct": float(vals[38]) if vals[38] else 0,
                "pe_ttm": float(vals[39]) if vals[39] else 0,
                "amplitude_pct": float(vals[43]) if vals[43] else 0,
                "mcap_yi": float(vals[44]) if vals[44] else 0,       # 总市值(亿)
                "float_mcap_yi": float(vals[45]) if vals[45] else 0,  # 流通市值(亿)
                "pb": float(vals[46]) if vals[46] else 0,
                "limit_up": float(vals[47]) if vals[47] else 0,
                "limit_down": float(vals[48]) if vals[48] else 0,
                "vol_ratio": float(vals[49]) if vals[49] else 0,
                "pe_static": float(vals[52]) if vals[52] else 0,
            }
        except (ValueError, IndexError):
            continue
    return result

def tencent_indices(index_codes=None):
    """
    腾讯财经指数行情。默认: 上证/深证/创业板/科创50/沪深300/上证50
    """
    if index_codes is None:
        index_codes = ["000001", "399001", "399006", "000688", "000300", "000016"]
    return tencent_quote(index_codes)


# ── 1.3 百度股市通 K线 (带MA5/10/20) ──
def baidu_kline_with_ma(code, start_time=""):
    """百度股市通K线，返回自带 MA5/MA10/MA20"""
    if not HAS_REQUESTS:
        return None
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = {
        "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
        "isFutures": "false", "isStock": "true", "newFormat": "1",
        "group": "quotation_kline_ab", "finClientType": "pc",
        "code": normalize_code(code), "start_time": start_time, "ktype": "1",
    }
    headers = {
        "User-Agent": UA, "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com", "Referer": "https://gushitong.baidu.com/",
    }
    try:
        r = _requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        result = d.get("Result", {})
        md = result.get("newMarketData", {})
        return {"keys": md.get("keys", []), "rows": md.get("marketData", "").split(";")}
    except Exception:
        return None


# ── 🔥 行情优先级组合函数 ──
def get_stock_quotes(codes, prefer_tdx=True):
    """
    获取个股实时行情 — 优先级: 通达信 > 腾讯 > 东财push2
    返回: {code: {price, chg_pct, name, pe, pb, mcap, ...}}
    """
    codes = [normalize_code(c) for c in (codes or [])]
    if not codes:
        return {}

    # L1: 通达信 TCP (最快，不封IP)
    if prefer_tdx:
        try:
            tdx = mootdx_quotes(codes)
            if tdx and len(tdx) >= max(1, len(codes) * 0.3):
                return tdx
        except Exception:
            pass

    # L2: 腾讯 HTTP (不封IP，含PE/PB/市值)
    tx = tencent_quote(codes)
    if tx:
        return tx

    # L3: 东财 push2 (有风控)
    return _eastmoney_batch_prices(codes)


def _eastmoney_batch_prices(codes):
    """东财批量现价 (HTTP, 有风控)"""
    from urllib.request import Request, urlopen
    results = {}
    secids = []
    for c in codes:
        if c.startswith(('60', '68')):
            secids.append(f'1.{c}')
        elif c.startswith(('00', '30')):
            secids.append(f'0.{c}')
        else:
            secids.append(f'1.{c}')

    for i in range(0, len(secids), 100):
        batch = secids[i:i+100]
        url = f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={",".join(batch)}&ut=bd1d9ddb04089700cf9c27f6f7426281'
        try:
            req = Request(url, headers={'User-Agent': UA_WIN})
            with urlopen(req, timeout=10) as r:
                items = json.loads(r.read().decode('utf-8')).get('data', {}).get('diff', [])
            for s in items:
                c = s.get('f12', '')
                pfx = get_prefix(c)
                results[f"{pfx}{c}"] = {
                    'price': s.get('f2', 0), 'chg_pct': s.get('f3', 0),
                    'name': s.get('f14', '')
                }
        except Exception:
            pass
        time.sleep(0.1)
    return results


def get_index_quotes():
    """
    获取指数行情 — 优先级: 腾讯 > 通达信 > 新浪
    返回: [{n, v, chg, up}]
    """
    names = {'000001': '上证指数', '399001': '深证成指', '399006': '创业板指',
             '000688': '科创50', '000300': '沪深300', '000016': '上证50'}

    # L1: 腾讯
    tx = tencent_indices(list(names.keys()))
    if tx:
        results = []
        for code in names:
            q = tx.get(code, {})
            if q:
                results.append({
                    'n': names[code], 'v': f"{q['price']:.0f}",
                    'chg': f"{q['change_pct']:+.2f}%", 'up': q['change_pct'] >= 0
                })
        if results:
            return results

    # L2: 通达信
    try:
        client = tdx_client()
        idx_codes = ['000001', '399001', '399006', '000688', '000300', '000016']
        q = client.quotes(symbol=idx_codes)
        if q is not None:
            results = []
            for i, row in enumerate(q):
                n = names.get(idx_codes[i], idx_codes[i])
                chg = row.get('change_pct', 0)
                results.append({'n': n, 'v': f"{row.get('price', 0):.0f}",
                                'chg': f"{chg:+.2f}%", 'up': chg >= 0})
            if results:
                return results
    except Exception:
        pass

    # L3: 新浪兜底
    return _sina_index_fallback(names)


def _sina_index_fallback(names):
    """新浪指数兜底"""
    from urllib.request import Request, urlopen
    sina_names = {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006',
                  '000688': 'sh000688', '000300': 'sh000300', '000016': 'sh000016'}
    try:
        urls = ','.join([f's_{v}' for v in sina_names.values()])
        req = Request(f'https://hq.sinajs.cn/list={urls}',
                     headers={'User-Agent': UA_WIN, 'Referer': 'https://finance.sina.com.cn/'})
        with urlopen(req, timeout=10) as r:
            text = r.read().decode('gbk', errors='replace')
        results = []
        labels = list(names.values())
        rev = {v: k for k, v in sina_names.items()}
        for i, line in enumerate(text.strip().split('\n')):
            if '=' not in line:
                continue
            data = line.split('"')[1] if '"' in line else ''
            parts = data.split(',')
            if len(parts) < 4:
                continue
            pct = float(parts[3]) if parts[3] else 0
            code_from_url = line.split('=')[0].replace('var hq_str_s_', '')
            idx = i
            results.append({
                'n': labels[idx] if idx < len(labels) else code_from_url,
                'v': f"{float(parts[1]):.0f}" if parts[1] else '0',
                'chg': f'{pct:+.2f}%', 'up': pct >= 0
            })
        return results
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# Layer 2: 研报层
# ═══════════════════════════════════════════════════════════════

REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

def eastmoney_reports(code, max_pages=5):
    """拉取指定股票的研报列表 (qType=0)"""
    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": normalize_code(code), "rcode": "",
        }
        r = em_get(REPORT_API, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        all_records.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
    return all_records


def eastmoney_industry_reports(industry_code="*", max_pages=5, begin="2024-01-01"):
    """拉取行业研报列表 (qType=1)"""
    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": industry_code, "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin, "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "1",
        }
        r = em_get(REPORT_API, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        all_records.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
    return all_records


def download_pdf(record, target_dir="./reports"):
    """下载单份研报PDF，返回保存路径或None"""
    info_code = record.get("infoCode", "")
    if not info_code:
        return None
    date = (record.get("publishDate") or "")[:10]
    org = record.get("orgSName") or "未知"
    title = re.sub(r'[\\/:*?"<>|]', "_", record.get("title", ""))[:80]
    fname = f"{date}_{org}_{title}.pdf"
    target = Path(target_dir) / fname
    if target.exists():
        return str(target)
    url = PDF_TPL.format(info_code=info_code)
    r = em_get(url, headers={"Referer": "https://data.eastmoney.com/"}, timeout=60)
    if r.status_code == 200 and len(r.content) >= 1024:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(r.content)
        return str(target)
    return None


def ths_eps_forecast(code):
    """同花顺机构一致预期EPS"""
    if not HAS_REQUESTS:
        return None
    try:
        import pandas as pd
        from io import StringIO
        url = f"https://basic.10jqka.com.cn/new/{normalize_code(code)}/worth.html"
        headers = {
            "User-Agent": UA,
            "Referer": "https://basic.10jqka.com.cn/",
        }
        r = _requests.get(url, headers=headers, timeout=15)
        r.encoding = "gbk"
        dfs = pd.read_html(StringIO(r.text))
        for df in dfs:
            cols = [str(c) for c in df.columns]
            if any("每股收益" in c or "均值" in c for c in cols):
                return df
        return dfs[0] if dfs else pd.DataFrame()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# Layer 3: 信号层
# ═══════════════════════════════════════════════════════════════

# ── 3.1 同花顺热点 — 当日强势股 + 题材归因 ──
def ths_hot_reason(date=None):
    """同花顺当日强势股归因。返回 [{code,name,reason,chg_pct,turnover,amount}]"""
    if HAS_REQUESTS:
        return _ths_hot_reason_requests(date)
    return _ths_hot_reason_urllib(date)

def _ths_hot_reason_requests(date=None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/"
           f"date/{date}/orderby/date/orderway/desc/charset/GBK/")
    headers = {"User-Agent": UA_WIN}
    try:
        r = _requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("errocode", 0) != 0:
            return []
        rows = data.get("data") or []
        return [{
            "code": r.get("code", ""), "name": r.get("name", ""),
            "reason": r.get("reason", ""),
            "chg_pct": float(r.get("zhangfu", 0) or 0),
            "turnover": float(r.get("huanshou", 0) or 0),
            "amount": r.get("chengjiaoe", 0),
        } for r in rows]
    except Exception:
        return []

def _ths_hot_reason_urllib(date=None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    from urllib.request import Request, urlopen
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/"
           f"date/{date}/orderby/date/orderway/desc/charset/GBK/")
    try:
        req = Request(url, headers={"User-Agent": UA_WIN})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
        if data.get("errocode", 0) != 0:
            return []
        rows = data.get("data") or []
        return [{
            "code": r.get("code", ""), "name": r.get("name", ""),
            "reason": r.get("reason", ""),
            "chg_pct": float(r.get("zhangfu", 0) or 0),
            "turnover": float(r.get("huanshou", 0) or 0),
            "amount": r.get("chengjiaoe", 0),
        } for r in rows]
    except Exception:
        return []


# ── 3.2 同花顺北向资金 — 实时分钟流向 ──
def hsgt_realtime():
    """沪深股通当日实时分钟流向。返回 DataFrame-like 或 dict"""
    HSGT_HEADERS = {
        "User-Agent": UA_WIN, "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }
    if HAS_REQUESTS:
        try:
            import pandas as pd
            r = _requests.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/",
                            headers=HSGT_HEADERS, timeout=10)
            d = r.json()
            times = d.get("time", [])
            hgt = d.get("hgt", [])
            sgt = d.get("sgt", [])
            n = len(times)
            return pd.DataFrame({
                "time": times,
                "hgt_yi": hgt[:n] + [None] * (n - len(hgt)),
                "sgt_yi": sgt[:n] + [None] * (n - len(sgt)),
            })
        except Exception:
            pass

    # urllib fallback
    from urllib.request import Request, urlopen
    try:
        req = Request("https://data.hexin.cn/market/hsgtApi/method/dayChart/", headers=HSGT_HEADERS)
        with urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode('utf-8'))
        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])
        last_hgt = None; last_sgt = None
        for v in reversed(hgt or []):
            if v is not None: last_hgt = v; break
        for v in reversed(sgt or []):
            if v is not None: last_sgt = v; break
        return {
            "times": times, "hgt": hgt, "sgt": sgt,
            "last_hgt": last_hgt or 0, "last_sgt": last_sgt or 0,
            "net_yi": round((last_hgt or 0) + (last_sgt or 0), 2)
        }
    except Exception:
        return {"times": [], "hgt": [], "sgt": [], "last_hgt": 0, "last_sgt": 0, "net_yi": 0}


# ── 3.3 东财 concept blocks — 个股所属板块/概念归属 ──
def eastmoney_concept_blocks(code):
    """个股所属板块/概念归属 (东财 slist)"""
    code = normalize_code(code)
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception:
        return {"total": 0, "boards": [], "concept_tags": []}

    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = []
    for it in items:
        boards.append({
            "name": it.get("f14", ""),
            "code": it.get("f12", ""),
            "change_pct": it.get("f3", ""),
            "lead_stock": it.get("f128", ""),
        })
    return {"total": len(boards), "boards": boards,
            "concept_tags": [b["name"] for b in boards]}


# ── 3.4 东财 push2 个股资金流向 (分钟级) ──
def eastmoney_fund_flow_minute(code):
    """个股资金流向 (分钟级, 当日盘中)"""
    code = normalize_code(code)
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {"secid": secid, "klt": 1, "fields1": "f1,f2,f3,f7",
              "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception:
        return []

    rows = []
    for line in (d.get("data", {}).get("klines", []) or []):
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0], "main_net": float(parts[1]),
                "small_net": float(parts[2]), "mid_net": float(parts[3]),
                "large_net": float(parts[4]), "super_net": float(parts[5]),
            })
    return rows


# ── 3.5 龙虎榜席位 (个股) ──
def dragon_tiger_board(code, trade_date, look_back=30):
    """个股龙虎榜数据聚合"""
    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1",
    )
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    if records:
        latest_date = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10, sort_columns="BUY", sort_types="-1",
        )
        for row in buy_data[:5]:
            seats["buy"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                "net": round((row.get("NET") or 0) / 10000, 1),
            })
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10, sort_columns="SELL", sort_types="-1",
        )
        for row in sell_data[:5]:
            seats["sell"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                "net": round((row.get("NET") or 0) / 10000, 1),
            })

    institution = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
    for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
        for row in detail_data:
            if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                amt = (row.get("BUY") or 0) if side == "buy" else (row.get("SELL") or 0)
                if side == "buy":
                    institution["buy_amt"] += amt
                else:
                    institution["sell_amt"] += amt
    institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
    institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
    institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)

    return {"records": records, "seats": seats, "institution": institution}


# ── 3.6 全市场龙虎榜 ──
def daily_dragon_tiger(trade_date=None, min_net_buy=None):
    """每日全市场龙虎榜汇总"""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=500, sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    if not data:
        return {"date": trade_date, "total_records": 0, "stocks": []}

    actual_date = str(data[0].get("TRADE_DATE", ""))[:10] if data else trade_date
    stocks = []
    for row in data:
        net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
        if min_net_buy is not None and net_buy < min_net_buy:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": (row.get("EXPLANATION", "") or "")[:40],
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": actual_date, "total_records": len(stocks), "stocks": stocks}


# ── 3.7 限售解禁日历 ──
def lockup_expiry(code, trade_date, forward_days=90):
    """限售解禁日历: 历史 + 未来90天"""
    history_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=15, sort_columns="FREE_DATE", sort_types="-1",
    )
    history = [{
        "date": str(row.get("FREE_DATE", ""))[:10],
        "type": row.get("LIMITED_STOCK_TYPE", ""),
        "shares": row.get("FREE_SHARES_NUM", 0),
        "ratio": row.get("FREE_RATIO", 0),
    } for row in history_data]

    end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
    end_str = end_date.strftime("%Y-%m-%d")
    upcoming_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{code}\")(FREE_DATE>='{trade_date}')(FREE_DATE<='{end_str}')",
        page_size=20, sort_columns="FREE_DATE", sort_types="1",
    )
    upcoming = [{
        "date": str(row.get("FREE_DATE", ""))[:10],
        "type": row.get("LIMITED_STOCK_TYPE", ""),
        "shares": row.get("FREE_SHARES_NUM", 0),
        "ratio": row.get("FREE_RATIO", 0),
    } for row in upcoming_data]

    return {"history": history, "upcoming": upcoming}


# ── 3.8 行业板块排名 ──
def industry_comparison(top_n=20):
    """全行业涨跌幅排名 (东财 push2, ~100行业). 失败返回空"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    headers = {"User-Agent": UA}
    try:
        r = em_get(url, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        if not items:
            return {"top": [], "bottom": [], "total": 0}

        rows = []
        for i, item in enumerate(items):
            rows.append({
                "rank": i + 1,
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
                "code": item.get("f12", ""),
                "up_count": item.get("f104", 0),
                "down_count": item.get("f105", 0),
                "leader": item.get("f140", ""),
                "leader_change": item.get("f136", 0),
            })
        return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}
    except Exception:
        return {"top": [], "bottom": [], "total": 0}


def compute_sector_heat_from_stocks(live_prices, stock_sector_map, min_stocks=3):
    """
    🔥 降级方案: 从个股现价自己算赛道平均涨跌，不依赖东财。
    live_prices: {sh600519: {chg_pct: 1.5}, ...}
    stock_sector_map: {600519: '白酒', ...}
    返回: [{n, s, c, bk}, ...] 与东财 industry_comparison 兼容格式
    """
    sec_changes = {}
    for key, v in (live_prices or {}).items():
        code = key[2:] if len(key) > 2 else key
        sec = stock_sector_map.get(code, '')
        if not sec:
            continue
        chg = v.get('chg_pct', 0) if isinstance(v, dict) else 0
        sec_changes.setdefault(sec, []).append(chg)

    result = []
    for sec, chgs in sec_changes.items():
        if len(chgs) < min_stocks:
            continue
        avg = sum(chgs) / len(chgs)
        result.append({
            'n': sec,
            's': f'{avg:+.1f}%',
            'c': 'var(--red)' if avg > 0 else 'var(--green)',
            'bk': ''
        })
    result.sort(key=lambda x: -float(x['s'].replace('%','').replace('+','')))
    return result


# ── 3.9 涨停池 ──
def get_zt_pool(date_str=None):
    """东财涨停池 (连板梯队)"""
    if date_str is None:
        cst = datetime.now(timezone.utc) + timedelta(hours=8)
        for attempt in range(3):
            d = cst - timedelta(days=attempt)
            if d.weekday() < 5:
                date_str = d.strftime('%Y%m%d')
                break
        if not date_str:
            return None

    from urllib.request import Request, urlopen
    url = (f'http://push2ex.eastmoney.com/getTopicZTPool'
           f'?ut=7eea3edcaed734bea9cbfc24409ed989'
           f'&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date={date_str}')
    try:
        req = Request(url, headers={'User-Agent': UA_WIN, 'Referer': 'http://quote.eastmoney.com/'})
        with urlopen(req, timeout=12) as r:
            text = r.read().decode('utf-8', errors='replace')
        if text.startswith('callback('):
            text = text[9:-1]
        elif 'jQuery' in text[:20]:
            text = text[text.index('(')+1:-1]
        data = json.loads(text)
        items = data.get('data', {}).get('pool', [])
        if not items:
            return None

        tiers = {}
        for item in items:
            lbc = item.get('lbc', 1) or 1
            stock = {
                'c': item.get('c', ''), 'n': item.get('n', ''),
                'industry': item.get('hybk', ''),
                'p': (item.get('p', 0) or 0) / 1000 if item.get('p', 0) else 0,
                'zdf': item.get('zdp', 0)
            }
            tiers.setdefault(lbc, []).append(stock)

        sorted_tiers = sorted(tiers.items(), reverse=True)
        return {
            'tiers': [{'boardCount': k, 'stocks': sorted(v, key=lambda s: s.get('n',''))}
                      for k, v in sorted_tiers],
            'maxBoard': sorted_tiers[0][0] if sorted_tiers else 0,
            'totalCount': len(items)
        }
    except Exception:
        return None


# ── 🔥 信号层组合: 题材热度 + 北向验证 ──
def get_hot_sector_themes():
    """拉当日强势股 reason，做词频统计 → Top 10 题材热度"""
    df = ths_hot_reason()
    if not df:
        return {"top_themes": [], "total_stocks": 0, "hot_stocks": []}
    all_tags = []
    for item in df:
        reason = item.get('reason', '')
        if reason:
            tags = [t.strip() for t in reason.replace('+', ' ').replace('/', ' ').split() if len(t.strip()) >= 2]
            all_tags.extend(tags)
    cnt = Counter(all_tags)
    return {
        "top_themes": [{"tag": t, "count": n} for t, n in cnt.most_common(20)],
        "total_stocks": len(df),
        "hot_stocks": df[:80]
    }


# ═══════════════════════════════════════════════════════════════
# Layer 4: 资金面 / 筹码层
# ═══════════════════════════════════════════════════════════════

def margin_trading(code, page_size=30):
    """融资融券明细 (日级)"""
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX", filter_str=f'(SCODE="{normalize_code(code)}")',
        page_size=page_size, sort_columns="DATE", sort_types="-1",
    )
    return [{
        "date": str(row.get("DATE", ""))[:10],
        "rzye": row.get("RZYE", 0), "rzmre": row.get("RZMRE", 0),
        "rzche": row.get("RZCHE", 0), "rqye": row.get("RQYE", 0),
        "rqmcl": row.get("RQMCL", 0), "rqchl": row.get("RQCHL", 0),
        "rzrqye": row.get("RZRQYE", 0),
    } for row in data]


def block_trade(code, page_size=20):
    """大宗交易记录"""
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE", filter_str=f'(SECURITY_CODE="{normalize_code(code)}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1",
    )
    rows = []
    for row in data:
        close = row.get("CLOSE_PRICE") or 0
        deal_price = row.get("DEAL_PRICE") or 0
        premium = ((deal_price / close - 1) * 100) if close else 0
        rows.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "price": deal_price, "close": close,
            "premium_pct": round(premium, 2),
            "vol": row.get("DEAL_VOLUME", 0),
            "amount": row.get("DEAL_AMT", 0),
            "buyer": row.get("BUYER_NAME", ""),
            "seller": row.get("SELLER_NAME", ""),
        })
    return rows


def holder_num_change(code, page_size=10):
    """股东户数变化 (季度级)"""
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST", filter_str=f'(SECURITY_CODE="{normalize_code(code)}")',
        page_size=page_size, sort_columns="END_DATE", sort_types="-1",
    )
    return [{
        "date": str(row.get("END_DATE", ""))[:10],
        "holder_num": row.get("HOLDER_NUM", 0),
        "change_num": row.get("HOLDER_NUM_CHANGE", 0),
        "change_ratio": row.get("HOLDER_NUM_RATIO", 0),
        "avg_shares": row.get("AVG_FREE_SHARES", 0),
    } for row in data]


def dividend_history(code, page_size=20):
    """分红送转历史"""
    data = eastmoney_datacenter(
        "RPT_SHAREBONUS_DET", filter_str=f'(SECURITY_CODE="{normalize_code(code)}")',
        page_size=page_size, sort_columns="EX_DIVIDEND_DATE", sort_types="-1",
    )
    return [{
        "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
        "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),
        "transfer_ratio": row.get("TRANSFER_RATIO", 0),
        "bonus_ratio": row.get("BONUS_RATIO", 0),
        "plan": row.get("ASSIGN_PROGRESS", ""),
    } for row in data]


def stock_fund_flow_120d(code):
    """个股资金流 (日级, 最近120交易日)"""
    code = normalize_code(code)
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception:
        return []

    rows = []
    for line in (d.get("data", {}).get("klines", []) or []):
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return rows


# ═══════════════════════════════════════════════════════════════
# Layer 5: 新闻层
# ═══════════════════════════════════════════════════════════════

def eastmoney_stock_news(code, page_size=20):
    """东财个股新闻 (JSONP 接口)"""
    code = normalize_code(code)
    cb = "jQuery_news"
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner_params = json.dumps({
        "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                  "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
    }, separators=(',', ':'))
    params = {"cb": cb, "param": inner_params}
    headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=15)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
        articles = (d.get("result", {}).get("cmsArticleWebOld", []) or [])
        return [{
            "title": re.sub(r'<[^>]+>', '', a.get("title", "")),
            "content": re.sub(r'<[^>]+>', '', a.get("content", ""))[:200],
            "time": a.get("date", ""),
            "source": a.get("mediaName", ""),
            "url": a.get("url", ""),
        } for a in articles]
    except Exception:
        return []


def eastmoney_global_news(page_size=50):
    """东方财富全球财经资讯 (7x24)"""
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102",
        "sortEnd": "", "pageSize": str(page_size),
        "req_trace": str(uuid.uuid4()),
    }
    headers = {"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        return [{
            "title": item.get("title", ""),
            "summary": (item.get("summary", "") or "")[:200],
            "time": item.get("showTime", ""),
        } for item in (d.get("data", {}).get("fastNewsList", []) or [])]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# Layer 6: 基础数据层
# ═══════════════════════════════════════════════════════════════

def eastmoney_stock_info(code):
    """东财个股基本面信息"""
    code = normalize_code(code)
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "fltt": "2", "invt": "2",
        "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
        "secid": f"{market_code}.{code}",
    }
    headers = {"User-Agent": UA}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json().get("data", {})
        return {
            "code": d.get("f57", ""), "name": d.get("f58", ""),
            "industry": d.get("f127", ""),
            "total_shares": d.get("f84", 0),
            "float_shares": d.get("f85", 0),
            "mcap": d.get("f116", 0),
            "float_mcap": d.get("f117", 0),
            "list_date": str(d.get("f189", "")),
            "price": d.get("f43", 0),
        }
    except Exception:
        return None


def sina_financial_report(code, report_type="lrb", num=8):
    """新浪财报三表。report_type: fzb(资产负债表)/lrb(利润表)/llb(现金流量表)"""
    if not HAS_REQUESTS:
        return []
    code = normalize_code(code)
    prefix = "sh" if code.startswith("6") else "sz"
    paper_code = f"{prefix}{code}"
    url = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
    params = {"paperCode": paper_code, "source": report_type, "type": "0", "page": "1", "num": str(num)}
    headers = {"User-Agent": UA}
    try:
        r = _requests.get(url, params=params, headers=headers, timeout=15)
        report_list = r.json().get("result", {}).get("data", {}).get("report_list", {}) or {}
        rows = []
        for period in sorted(report_list.keys(), reverse=True)[:num]:
            obj = report_list[period]
            rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
            for it in (obj.get("data", []) or []):
                title = it.get("item_title", "")
                if not title or it.get("item_value") is None:
                    continue
                rec[title] = it.get("item_value")
                tongbi = it.get("item_tongbi")
                if tongbi not in (None, ""):
                    rec[title + "_同比"] = tongbi
            rows.append(rec)
        return rows
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# Layer 7: 公告层
# ═══════════════════════════════════════════════════════════════

_CNINFO_ORGID_MAP = {}

def _cninfo_orgid(code):
    """巨潮 orgId 动态查询 (模块级缓存)"""
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        try:
            if HAS_REQUESTS:
                r = _requests.get("http://www.cninfo.com.cn/new/data/szse_stock.json",
                                 headers={"User-Agent": UA}, timeout=15)
                _CNINFO_ORGID_MAP = {s["code"]: s["orgId"]
                                     for s in r.json().get("stockList", [])}
            else:
                from urllib.request import Request, urlopen
                req = Request("http://www.cninfo.com.cn/new/data/szse_stock.json",
                             headers={"User-Agent": UA})
                with urlopen(req, timeout=15) as r:
                    _CNINFO_ORGID_MAP = {s["code"]: s["orgId"]
                                         for s in json.loads(r.read().decode('utf-8')).get("stockList", [])}
        except Exception:
            pass
    org = _CNINFO_ORGID_MAP.get(code)
    if org:
        return org
    if code.startswith("6"):
        return f"gssh0{code}"
    elif code.startswith("8") or code.startswith("4"):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def cninfo_announcements(code, page_size=30):
    """巨潮公告全文检索"""
    if not HAS_REQUESTS:
        return _cninfo_urllib(code, page_size)
    code = normalize_code(code)
    org_id = _cninfo_orgid(code)
    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    payload = {
        "stock": f"{code},{org_id}", "tabName": "fulltext",
        "pageSize": str(page_size), "pageNum": "1",
        "column": "", "category": "", "plate": "", "seDate": "",
        "searchkey": "", "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    headers = {
        "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
        "Origin": "https://www.cninfo.com.cn",
    }
    try:
        r = _requests.post(url, data=payload, headers=headers, timeout=15)
        d = r.json()
        return [{
            "title": item.get("announcementTitle", ""),
            "type": item.get("announcementTypeName", ""),
            "date": _cninfo_ts_to_date(item.get("announcementTime")),
            "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
        } for item in (d.get("announcements", []) or [])]
    except Exception:
        return []

def _cninfo_ts_to_date(ts):
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    return str(ts)[:10] if ts else ""

def _cninfo_urllib(code, page_size=30):
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    code = normalize_code(code)
    org_id = _cninfo_orgid(code)
    payload = urlencode({
        "stock": f"{code},{org_id}", "tabName": "fulltext",
        "pageSize": str(page_size), "pageNum": "1",
        "column": "", "category": "", "plate": "", "seDate": "",
        "searchkey": "", "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true",
    })
    headers = {
        "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
        "Origin": "https://www.cninfo.com.cn",
    }
    req = Request("https://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload.encode('utf-8'), headers=headers)
    try:
        with urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode('utf-8'))
        return [{
            "title": item.get("announcementTitle", ""),
            "type": item.get("announcementTypeName", ""),
            "date": _cninfo_ts_to_date(item.get("announcementTime")),
            "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
        } for item in (d.get("announcements", []) or [])]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# iwencai — NL语义搜索研报 (唯一能力, 需API Key)
# ═══════════════════════════════════════════════════════════════

_IWENCAI_KEY = os.environ.get("IWENCAI_API_KEY", "")
_IWENCAI_BASE = os.environ.get("IWENCAI_BASE_URL", "https://openapi.iwencai.com")

def _claw_headers(call_type="normal"):
    """SkillHub 2.0 X-Claw 鉴权头"""
    import secrets as _secrets
    return {
        "X-Claw-Call-Type": call_type,
        "X-Claw-Skill-Id": "report-search",
        "X-Claw-Skill-Version": "2.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": _secrets.token_hex(32),
    }

def iwencai_search(query, channel="report", size=50):
    """
    iwencai 语义搜索研报。
    channel: report(研报)/announcement(公告)/news(新闻)
    若无 API Key 则返回空列表。
    """
    if not _IWENCAI_KEY or not HAS_REQUESTS:
        return []
    headers = {
        "Authorization": f"Bearer {_IWENCAI_KEY}",
        "Content-Type": "application/json",
        **_claw_headers(),
    }
    payload = {"channels": [channel], "app_id": "AIME_SKILL", "query": query, "size": size}
    try:
        r = _requests.post(f"{_IWENCAI_BASE}/v1/comprehensive/search",
                          json=payload, headers=headers, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status_code", 0) != 0:
            return []
        return data.get("data") or []
    except Exception:
        return []

def iwencai_query(query, page=1, limit=50):
    """iwencai NL数据查询 (结构化字段)"""
    if not _IWENCAI_KEY or not HAS_REQUESTS:
        return []
    headers = {
        "Authorization": f"Bearer {_IWENCAI_KEY}",
        "Content-Type": "application/json",
        **_claw_headers(),
    }
    payload = {"query": query, "page": str(page), "limit": str(limit),
               "is_cache": "1", "expand_index": "true"}
    try:
        r = _requests.post(f"{_IWENCAI_BASE}/v1/query2data",
                          json=payload, headers=headers, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("status_code", 0) != 0:
            return []
        return data.get("datas") or []
    except Exception:
        return []

def dedup_articles(articles):
    """同一 uid 仅保留 score 最高的段落"""
    best = {}
    for a in (articles or []):
        uid = a.get("uid", "") or f"{a.get('title','')}|{a.get('publish_date','')}"
        score = float(a.get("score", 0))
        if uid not in best or score > float(best[uid].get("score", 0)):
            best[uid] = a
    return sorted(best.values(), key=lambda x: x.get("publish_date", ""), reverse=True)


# ═══════════════════════════════════════════════════════════════
# 北向资金本地缓存
# ═══════════════════════════════════════════════════════════════

def _northbound_cache_path():
    p = Path.home() / ".tradingagents" / "cache" / "northbound_daily.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def save_northbound_snapshot(date_str, hgt, sgt):
    """写入/更新当天北向收盘数据到 CSV"""
    path = _northbound_cache_path()
    rows = {}
    if path.exists():
        for line in path.read_text().strip().split("\n")[1:]:
            parts = line.split(",")
            if len(parts) == 3:
                rows[parts[0]] = line
    rows[date_str] = f"{date_str},{hgt},{sgt}"
    with open(path, "w") as f:
        f.write("date,hgt,sgt\n")
        for d in sorted(rows.keys()):
            f.write(rows[d] + "\n")

def load_northbound_history(n=20):
    """读取最近 N 天北向历史"""
    path = _northbound_cache_path()
    if not path.exists():
        return []
    history = []
    for line in path.read_text().strip().split("\n")[1:]:
        parts = line.split(",")
        if len(parts) == 3:
            history.append({"date": parts[0], "hgt": float(parts[1]), "sgt": float(parts[2])})
    return history[-n:]


# ═══════════════════════════════════════════════════════════════
# mootdx 逐笔成交 (非交易时间返回空)
# ═══════════════════════════════════════════════════════════════

def mootdx_transaction(symbol, date=None):
    """通达信逐笔成交数据"""
    if date is None:
        date = datetime.now().strftime('%Y%m%d')
    try:
        client = tdx_client()
        trades = client.transaction(symbol=str(symbol)[:6], date=date)
        if trades is not None and len(trades) > 0:
            return trades
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# 完整单票估值 (30秒)
# ═══════════════════════════════════════════════════════════════

def full_valuation(code):
    """单票完整估值分析: 腾讯行情 + 同花顺一致预期 → PE/PEG/消化年限"""
    import math
    code = normalize_code(code)
    # L1: 腾讯实时行情
    tx = tencent_quote([code])
    q = tx.get(code, {})
    if not q:
        return {"error": "无法获取行情", "code": code}

    price = q.get("price", 0)
    pe_ttm = q.get("pe_ttm", 0)
    pb = q.get("pb", 0)
    mcap = q.get("mcap_yi", 0)

    # L2: 同花顺一致预期
    eps_cur = eps_next = None
    analyst_count = 0
    try:
        df = ths_eps_forecast(code)
        if df is not None:
            try:
                empty = df.empty
            except Exception:
                empty = len(df) == 0
            if not empty and len(df.columns) >= 3:
                for i, row in df.iterrows():
                    try:
                        v2 = float(row.iloc[2])
                    except (ValueError, TypeError):
                        v2 = None
                    try:
                        v1 = int(row.iloc[1])
                    except (ValueError, TypeError):
                        v1 = 0
                    if i == 0:
                        eps_cur = v2
                        analyst_count = v1
                    elif i == 1:
                        eps_next = v2
    except Exception:
        pass

    pe_fwd = price / eps_cur if eps_cur and eps_cur > 0 else None
    cagr = (eps_next / eps_cur - 1) if (eps_cur and eps_next and eps_cur > 0) else 0
    peg = (pe_fwd / (cagr * 100)) if pe_fwd and cagr > 0 else None
    digest = (math.log(pe_fwd / 30) / math.log(1 + cagr)) if (pe_fwd and pe_fwd > 30 and cagr > 0) else 0

    return {
        "name": q.get("name", ""), "code": code,
        "price": price, "mcap_yi": mcap, "pe_ttm": pe_ttm, "pb": pb,
        "eps_cur": eps_cur, "eps_next": eps_next,
        "pe_fwd": round(pe_fwd, 1) if pe_fwd else None,
        "cagr_pct": round(cagr * 100, 0) if cagr else None,
        "peg": round(peg, 2) if peg else None,
        "digest_years": round(digest, 1),
        "analyst_count": analyst_count,
    }


# ═══════════════════════════════════════════════════════════════
# 估值计算
# ═══════════════════════════════════════════════════════════════

def forward_pe(price, eps_forecast):
    """前向PE = 当前股价 / 一致预期EPS"""
    if eps_forecast <= 0:
        return float("inf")
    return price / eps_forecast

def pe_digestion(current_pe, cagr, target_pe=30):
    """PE消化时间 (年)"""
    import math
    if current_pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return float("inf")
    return math.log(current_pe / target_pe) / math.log(1 + cagr)

def calc_peg(pe, cagr):
    """PEG = 前向PE / (CAGR * 100)"""
    if cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)


# ═══════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════

def health_check(fast=True):
    """快速检测各数据源连通性。fast=True 跳过慢速 TCP 探测"""
    results = {}
    # 通达信 (fast 模式跳过TCP探测)
    if fast:
        results['mootdx'] = False  # 跳过TCP探测，节省15秒
    else:
        results['mootdx'] = tdx_available()
    # 腾讯
    try:
        q = tencent_quote(['000001'])
        results['tencent'] = len(q) > 0
    except:
        results['tencent'] = False
    # 东财
    try:
        r = em_get('https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&po=1&np=1&fltt=2&invt=2&fs=m:0+t:1&fields=f12', timeout=10)
        results['eastmoney'] = r.status_code == 200
    except:
        results['eastmoney'] = False
    # 同花顺
    try:
        hot = ths_hot_reason()
        results['10jqka'] = len(hot) > 0
    except:
        results['10jqka'] = False
    return results


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("=== a-stock-data 健康检查 ===")
    hc = health_check()
    for k, v in hc.items():
        print(f"  {k}: {'✅ OK' if v else '❌ FAIL'}")
    print(f"  requests lib: {'✅' if HAS_REQUESTS else '❌ (urllib fallback)'}")
