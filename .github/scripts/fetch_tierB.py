#!/usr/bin/env python3
"""
TTNB Tier B — per-stock data scans from a-stock-data.
Runs alternating 30-min batch groups in GitHub Actions cloud.

B-fast (even half-hours: :00-:04, :30-:34):
  B1. 概念板块归属 → data.json.conceptBlocks
  B2. 个股基本信息 → data.json.stockInfo_em
  B3. 个股资金流分钟 → data.json.fundFlowMin
  B4. 个股新闻(东财) → data.json.stockNews

B-slow (odd half-hours: :15-:19, :45-:49):
  B5. 个股资金流120日 → data.json.fundFlow120
  B6. 龙虎榜席位(个股) → data.json.dragonSeats
  B7. 大宗交易 → data.json.blockTrades
  B8. 股东户数 → data.json.holderNum
  B9. 分红送转 → data.json.dividendHist

Scan cap: 25 stocks per batch, 1.3s interval between requests.
"""
import json, os, time, random
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

_em_last = 0.0
EM_MIN = 1.3

def _em_fetch(url, encoding='utf-8', extra_headers=None, retries=2):
    global _em_last
    wait = EM_MIN - (time.time() - _em_last)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    for i in range(retries):
        try:
            headers = {'User-Agent': UA, 'Accept': '*/*',
                       'Referer': 'https://data.eastmoney.com/'}
            if extra_headers:
                headers.update(extra_headers)
            req = Request(url, headers=headers)
            with urlopen(req, timeout=15) as r:
                result = r.read().decode(encoding, errors='replace')
                _em_last = time.time()
                return result
        except Exception:
            if i == retries - 1:
                _em_last = time.time()
                return None
            time.sleep(2)

def em_datacenter(report_name, filter_str="", page_size=10,
                  sort_columns="", sort_types="-1"):
    params = (
        f"reportName={report_name}&columns=ALL"
        f"&filter={filter_str}&pageNumber=1&pageSize={page_size}"
        f"&sortColumns={sort_columns}&sortTypes={sort_types}"
        f"&source=WEB&client=WEB"
    )
    url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?{params}"
    text = _em_fetch(url)
    if not text:
        return []
    try:
        d = json.loads(text)
        return d.get("result", {}).get("data", []) if d.get("result") else []
    except:
        return []


def get_secid(code):
    """6-digit code → EastMoney secid."""
    return f"{1 if code.startswith('6') else 0}.{code}"


# ═══ B1: 概念板块归属 ═══
def fetch_concept_blocks(code):
    try:
        secid = get_secid(code)
        url = f"https://push2.eastmoney.com/api/qt/slist/get?fltt=2&invt=2&secid={secid}&spt=3&pi=0&pz=50&po=1&fields=f12,f14"
        text = _em_fetch(url)
        if not text:
            return []
        d = json.loads(text)
        diff = (d.get("data") or {}).get("diff") or {}
        return [it.get("f14", "") for it in (diff.values() if isinstance(diff, dict) else diff) if it.get("f14")]
    except:
        return []


# ═══ B2: 个股基本信息 ═══
def fetch_stock_info_em(code):
    try:
        secid = get_secid(code)
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f84,f85,f116,f117,f127"
        text = _em_fetch(url)
        if not text:
            return None
        d = json.loads(text).get("data", {})
        return {
            "ind": d.get("f127", ""), "tot": d.get("f84", 0), "flt": d.get("f85", 0),
            "eps": d.get("f57", 0), "bvps": d.get("f58", 0),
            "listDate": d.get("f117", ""),
        } if d else None
    except:
        return None


# ═══ B3: 个股资金流分钟 ═══
def fetch_fund_flow_min(code):
    try:
        secid = get_secid(code)
        url = f"https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?secid={secid}&klt=1&lmt=60"
        text = _em_fetch(url)
        if not text:
            return None
        d = json.loads(text)
        items = d.get("data", {}).get("klines", [])
        if not items:
            return None
        # Get today's accumulated flow
        total_net = 0
        for it in items[-10:]:
            parts = it.split(",")
            if len(parts) >= 5:
                total_net += float(parts[4] or 0) / 10000
        return round(total_net, 1)
    except:
        return None


# ═══ B4: 个股新闻 ═══
def fetch_stock_news(code):
    try:
        url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=j&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{code}%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A3%7D"
        text = _em_fetch(url)
        if not text or "j(" not in text:
            return []
        j = json.loads(text[2:-1])
        articles = j.get("result", {}).get("cmsArticleWebOld", [])
        return [(a.get("title") or "")[:80] for a in (articles or [])[:3]]
    except:
        return []


# ═══ B5: 个股资金流120日 ═══
def fetch_fund_flow_120d(code):
    try:
        secid = get_secid(code)
        url = f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?secid={secid}&lmt=120&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56"
        text = _em_fetch(url)
        if not text:
            return None
        d = json.loads(text)
        items = d.get("data", {}).get("klines", [])
        if not items:
            return None
        net_5d = 0
        for it in items[-5:]:
            parts = it.split(",")
            if len(parts) >= 4:
                net_5d += float(parts[3] or 0) / 10000
        # Also get net_20d
        net_20d = 0
        for it in items[-20:]:
            parts = it.split(",")
            if len(parts) >= 4:
                net_20d += float(parts[3] or 0) / 10000
        return {"n5d": round(net_5d, 1), "n20d": round(net_20d, 1)}
    except:
        return None


# ═══ B6: 龙虎榜席位(个股) ═══
def fetch_dragon_seats(code):
    try:
        data = em_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'2026-06-01\')',
            page_size=3,
            sort_columns="TRADE_DATE", sort_types="-1",
        )
        if not data:
            return None
        latest = data[0]
        return {
            "d": str(latest.get("TRADE_DATE", ""))[:10],
            "net_wan": round(float(latest.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "reason": (latest.get("EXPLANATION") or "")[:40],
        }
    except:
        return None


# ═══ B7: 大宗交易 ═══
def fetch_block_trade(code):
    try:
        data = em_datacenter(
            "RPT_DATA_BLOCKTRADE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=3,
            sort_columns="TRADE_DATE", sort_types="-1",
        )
        if not data:
            return None
        latest = data[0]
        close = latest.get("CLOSE_PRICE") or 0
        deal = latest.get("DEAL_PRICE") or 0
        premium = round(((deal / close - 1) * 100), 1) if close else 0
        return {
            "d": str(latest.get("TRADE_DATE", ""))[:10],
            "prem": premium, "amt": round(float(latest.get("DEAL_AMT") or 0) / 10000, 0),
            "buyer": (latest.get("BUYER_NAME") or "")[:20],
        }
    except:
        return None


# ═══ B8: 股东户数 ═══
def fetch_holder_num(code):
    try:
        data = em_datacenter(
            "RPT_HOLDERNUMLATEST",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=2,
            sort_columns="END_DATE", sort_types="-1",
        )
        if len(data) < 1:
            return None
        latest = data[0]
        return {
            "d": str(latest.get("END_DATE", ""))[:10],
            "holders": latest.get("HOLDER_NUM", 0),
            "chg_pct": round(float(latest.get("HOLDER_NUM_RATIO") or 0), 1),
        }
    except:
        return None


# ═══ B9: 分红送转 ═══
def fetch_dividend(code):
    try:
        data = em_datacenter(
            "RPT_SHAREBONUS_DET",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=3,
            sort_columns="EX_DIVIDEND_DATE", sort_types="-1",
        )
        if not data:
            return None
        latest = data[0]
        return {
            "d": str(latest.get("EX_DIVIDEND_DATE", ""))[:10],
            "bonus": round(float(latest.get("PRETAX_BONUS_RMB") or 0), 2),
            "plan": (latest.get("ASSIGN_PROGRESS") or "")[:20],
        }
    except:
        return None


# ═══ Main ═══
def main():
    if not os.path.exists(DATA_PATH):
        print("data.json not found")
        return

    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"ERROR: corrupted data.json, cannot continue: {e}")
        return

    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    minute = cst.minute

    # Determine batch group
    is_fast = (minute % 30 < 5)
    is_slow = (15 <= minute % 30 < 20)
    if not (is_fast or is_slow):
        print(f"TierB skip: minute={minute} (fast=:00/:30, slow=:15/:45)")
        if 'conceptBlocks' not in d:
            d['conceptBlocks'] = {}
        return

    # Extract stock codes (capped at 25)
    codes = set()
    for lev in d.get('layout', []):
        for s in lev.get('stocks', []):
            parts = s.split() if s else []
            if parts and len(parts[0]) == 6:
                codes.add(parts[0])
    for sec, stocks in d.get('sectorStocks', {}).items():
        for s in stocks:
            c = s.get('c', '') if isinstance(s, dict) else (s.split()[0] if s else '')
            if c and len(c) == 6:
                codes.add(c)
    code_list = sorted(codes)[:25]

    batch_label = "B-fast" if is_fast else "B-slow"
    print(f"=== TierB {batch_label} {cst.strftime('%H:%M')} | {len(code_list)} stocks ===")

    if is_fast:
        # B1: concept blocks
        cb = {}
        for c in code_list:
            tags = fetch_concept_blocks(c)
            if tags:
                cb[c] = tags[:15]
        d['conceptBlocks'] = cb
        print(f"  B1 概念板块: {len(cb)}只")

        # B2: stock info
        si = {}
        for c in code_list:
            info = fetch_stock_info_em(c)
            if info:
                si[c] = info
        d['stockInfo_em'] = si
        print(f"  B2 个股信息: {len(si)}只")

        # B3: fund flow minute
        ff = {}
        for c in code_list:
            val = fetch_fund_flow_min(c)
            if val is not None:
                ff[c] = val
        d['fundFlowMin'] = ff
        print(f"  B3 资金流分钟: {len(ff)}只")

        # B4: stock news
        sn = {}
        for c in code_list:
            titles = fetch_stock_news(c)
            if titles:
                sn[c] = titles
        d['stockNews'] = sn
        print(f"  B4 个股新闻: {len(sn)}只")

    elif is_slow:
        # B5: fund flow 120d
        ff120 = {}
        for c in code_list:
            val = fetch_fund_flow_120d(c)
            if val is not None:
                ff120[c] = val
        d['fundFlow120'] = ff120
        print(f"  B5 资金流120日: {len(ff120)}只")

        # B6: dragon seats
        ds = {}
        for c in code_list:
            val = fetch_dragon_seats(c)
            if val:
                ds[c] = val
        d['dragonSeats'] = ds
        print(f"  B6 龙虎榜席位: {len(ds)}只")

        # B7: block trades
        bt = {}
        for c in code_list:
            val = fetch_block_trade(c)
            if val:
                bt[c] = val
        d['blockTrades'] = bt
        print(f"  B7 大宗交易: {len(bt)}只")

        # B8: holder num
        hn = {}
        for c in code_list:
            val = fetch_holder_num(c)
            if val:
                hn[c] = val
        d['holderNum'] = hn
        print(f"  B8 股东户数: {len(hn)}只")

        # B9: dividends
        dh = {}
        for c in code_list:
            val = fetch_dividend(c)
            if val:
                dh[c] = val
        d['dividendHist'] = dh
        print(f"  B9 分红送转: {len(dh)}只")

    # Save (atomic)
    d['updated'] = cst.strftime('%Y-%m-%d %H:%M CST') + f' (tierB-{batch_label})'
    tmp_path = DATA_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_PATH)

    print(f"TierB done → {DATA_PATH}")


if __name__ == '__main__':
    main()
