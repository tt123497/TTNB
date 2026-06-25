#!/usr/bin/env python3
"""
TTNB 数据增强层 — 接入 a-stock-data 的4大核心端点
来源: simonlin1212/a-stock-data SKILL V3.2.4
适配: GitHub Actions 云端环境 (US IP, urllib only, 零新依赖)

新增数据维度:
  1. 北向资金 (同花顺 hsgtApi) → data.json.northbound
  2. 全市场龙虎榜 (东财 datacenter) → data.json.lhbFull (替代基础 lhb)
  3. 限售解禁预警 (东财 datacenter) → data.json.lockupAlerts
  4. 同花顺热点归因 (ths hot reason) → data.json._hotReasons (供 AI Sentinel 参考)
  5. 融资融券摘要 (东财 datacenter) → data.json.marginSummary (关键标的)
"""
import json, os, time, random
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

# ═══════════════════════════════════════════════════════════════
# 东财统一请求（内置限流防封，同 a-stock-data em_get 逻辑）
# ═══════════════════════════════════════════════════════════════
_em_last = 0.0
EM_MIN = 1.2  # seconds between EastMoney requests

def _em_fetch(url, encoding='utf-8', extra_headers=None, retries=2):
    """EastMoney throttle-safe fetch. Auto spacing + retry."""
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
        except Exception as e:
            if i == retries - 1:
                _em_last = time.time()
                return None
            time.sleep(2)

def em_datacenter(report_name, filter_str="", page_size=50,
                  sort_columns="", sort_types="-1"):
    """东财数据中心统一查询（等效 a-stock-data eastmoney_datacenter）"""
    params = (
        f"reportName={report_name}"
        f"&columns=ALL"
        f"&filter={filter_str}"
        f"&pageNumber=1&pageSize={page_size}"
        f"&sortColumns={sort_columns}&sortTypes={sort_types}"
        f"&source=WEB&client=WEB"
    )
    url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?{params}"
    text = _em_fetch(url)
    if not text:
        return []
    try:
        d = json.loads(text)
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except:
        pass
    return []


# ═══════════════════════════════════════════════════════════════
# 1. 北向资金（同花顺 hsgtApi）
# ═══════════════════════════════════════════════════════════════
def fetch_northbound():
    """
    获取当日沪深股通实时分钟流向。
    返回: {date, hgt_yi(沪股通累计净买入亿), sgt_yi(深股通累计净买入亿),
           net_yi(合计), points(分钟点数), status}
    """
    url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
    headers = {
        "User-Agent": UA,
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=12) as r:
            d = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {"date": "", "hgt_yi": 0, "sgt_yi": 0, "net_yi": 0,
                "points": 0, "status": f"获取失败: {e}"}

    times = d.get("time", [])
    hgt = d.get("hgt", [])
    sgt = d.get("sgt", [])

    if not times:
        return {"date": "", "hgt_yi": 0, "sgt_yi": 0, "net_yi": 0,
                "points": 0, "status": "非交易时间无数据"}

    # 取最后有效值
    last_hgt = None
    last_sgt = None
    for v in reversed(hgt):
        if v is not None:
            last_hgt = v
            break
    for v in reversed(sgt):
        if v is not None:
            last_sgt = v
            break

    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    return {
        "date": cst.strftime('%Y-%m-%d'),
        "hgt_yi": round(last_hgt or 0, 2),   # 沪股通累计净买入(亿)
        "sgt_yi": round(last_sgt or 0, 2),   # 深股通累计净买入(亿)
        "net_yi": round((last_hgt or 0) + (last_sgt or 0), 2),
        "points": len(times),
        "status": "实时" if cst.hour < 15 else "收盘"
    }


# ═══════════════════════════════════════════════════════════════
# 2. 全市场龙虎榜（东财 datacenter）
# ═══════════════════════════════════════════════════════════════
def fetch_full_lhb():
    """
    当日全市场龙虎榜汇总。
    返回: {date, total, stocks: [{code, name, reason, close, chg_pct,
           net_buy_wan, buy_wan, sell_wan, turnover_pct}], status}
    """
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    # 找最近交易日
    for attempt in range(4):
        try_date = cst - timedelta(days=attempt)
        if try_date.weekday() >= 5:
            continue
        date_str = try_date.strftime('%Y-%m-%d')

        data = em_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE>='{date_str}')(TRADE_DATE<='{date_str}')",
            page_size=300,
            sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
        )
        if data:
            stocks = []
            for row in data:
                net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
                stocks.append({
                    "c": row.get("SECURITY_CODE", ""),
                    "n": row.get("SECURITY_NAME_ABBR", ""),
                    "reason": (row.get("EXPLANATION", "") or "")[:40],
                    "close": row.get("CLOSE_PRICE") or 0,
                    "chg": round(float(row.get("CHANGE_RATE") or 0), 2),
                    "net": round(net_buy, 1),          # 净买入(万)
                    "buy": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
                    "sell": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
                    "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
                })
            return {
                "date": date_str,
                "total": len(stocks),
                "stocks": stocks[:100],  # Top 100 by net buy
                "status": "ok"
            }

    return {"date": "", "total": 0, "stocks": [], "status": "无数据(非交易日?)"}


# ═══════════════════════════════════════════════════════════════
# 3. 限售解禁预警（扫描关键标的池）
# ═══════════════════════════════════════════════════════════════
def fetch_lockup_alerts(codes, forward_days=90):
    """
    扫描给定代码池的未来限售解禁。
    codes: list of 6-digit stock codes
    返回: [{code, name, date, type, shares(万股), ratio(%)}]
    """
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today_str = cst.strftime('%Y-%m-%d')
    end_date = cst + timedelta(days=forward_days)
    end_str = end_date.strftime('%Y-%m-%d')

    alerts = []
    scanned = 0
    for code in codes[:60]:  # max 60 stocks to avoid rate limit
        time.sleep(0.15)  # gentle spacing
        try:
            data = em_datacenter(
                "RPT_LIFT_STAGE",
                filter_str=f"(SECURITY_CODE=\"{code}\")(FREE_DATE>='{today_str}')(FREE_DATE<='{end_str}')",
                page_size=5,
                sort_columns="FREE_DATE", sort_types="1",
            )
            for row in data:
                shares_wan = round((row.get("FREE_SHARES_NUM") or 0) / 10000, 0)
                ratio = round(float(row.get("FREE_RATIO") or 0), 2)
                if ratio < 0.5:  # skip negligible (<0.5%)
                    continue
                alerts.append({
                    "c": code,
                    "n": row.get("SECURITY_NAME_ABBR", ""),
                    "d": str(row.get("FREE_DATE", ""))[:10],
                    "type": (row.get("LIMITED_STOCK_TYPE", "") or "")[:20],
                    "shares": shares_wan,
                    "ratio": ratio,
                })
            scanned += 1
        except:
            pass

    # Sort by date, then ratio desc
    alerts.sort(key=lambda x: (x['d'], -x['ratio']))
    return {"scanned": scanned, "alerts": alerts[:30], "forwardDays": forward_days}


# ═══════════════════════════════════════════════════════════════
# 4. 同花顺热点归因
# ═══════════════════════════════════════════════════════════════
def fetch_hot_reasons():
    """
    同花顺当日强势股 + 题材归因 reason tags。
    返回: [{code, name, reason, chg_pct, turnover, amount}]
    """
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    date_str = cst.strftime('%Y-%m-%d')

    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/"
        f"date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    )
    headers = {"User-Agent": UA}
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {"date": date_str, "total": 0, "stocks": [],
                "status": f"获取失败: {e}"}

    if data.get("errocode", 0) != 0:
        return {"date": date_str, "total": 0, "stocks": [],
                "status": data.get("errormsg", "API错误")}

    rows = data.get("data") or []
    stocks = []
    for r in rows:
        reason = r.get("reason", "")
        if not reason:
            continue  # skip stocks without reason tags
        stocks.append({
            "c": r.get("code", ""),
            "n": r.get("name", ""),
            "reason": reason,
            "chg": round(float(r.get("zhangfu", 0) or 0), 2),
            "turnover": round(float(r.get("huanshou", 0) or 0), 2),
            "amount": r.get("chengjiaoe", 0),
        })

    # Build sector frequency from reason tags
    reason_freq = {}
    for s in stocks:
        for tag in s['reason'].replace('+', ' ').replace('/', ' ').split():
            tag = tag.strip()
            if len(tag) >= 2:
                reason_freq[tag] = reason_freq.get(tag, 0) + 1
    top_reasons = sorted(reason_freq.items(), key=lambda x: -x[1])[:20]

    return {
        "date": date_str,
        "total": len(stocks),
        "stocks": stocks[:80],       # cap at 80
        "topReasons": [{"tag": t, "count": c} for t, c in top_reasons],
        "status": "ok" if stocks else "盘后数据未更新(15:30后刷新)"
    }


# ═══════════════════════════════════════════════════════════════
# 5. 融资融券摘要（关键赛道标的扫描）
# ═══════════════════════════════════════════════════════════════
def fetch_margin_summary(codes):
    """
    获取关键标的最近融资余额和趋势。
    返回: [{code, name, date, rzye_wan(融资余额万), change_5d(5日变化)}]
    """
    summary = []
    for code in codes[:30]:  # max 30
        time.sleep(0.2)
        try:
            data = em_datacenter(
                "RPTA_WEB_RZRQ_GGMX",
                filter_str=f'(SCODE="{code}")',
                page_size=6,  # last 6 trading days
                sort_columns="DATE", sort_types="-1",
            )
            if len(data) >= 2:
                latest = data[0]
                older = data[-1]  # ~5 days ago
                rzye_now = (latest.get("RZYE") or 0) / 10000
                rzye_old = (older.get("RZYE") or 0) / 10000
                change_5d = round((rzye_now - rzye_old) / (abs(rzye_old) + 1) * 100, 1)
                summary.append({
                    "c": code,
                    "n": latest.get("SECURITY_NAME_ABBR", ""),
                    "d": str(latest.get("DATE", ""))[:10],
                    "rzye_wan": round(rzye_now, 0),
                    "change_5d": change_5d,  # positive = 加杠杆
                    "rzmre_wan": round((latest.get("RZMRE") or 0) / 10000, 0),  # 当日买入
                })
        except:
            pass

    # Sort: biggest recent margin increase first (bullish)
    summary.sort(key=lambda x: -x['change_5d'])
    return {"stocks": summary, "status": "ok" if summary else "无数据"}


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    # Load existing data.json
    if not os.path.exists(DATA_PATH):
        print("data.json not found — run fetch_data.py first")
        return

    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"ERROR: corrupted data.json, cannot continue: {e}")
        return

    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15
    print(f"=== Enrich {cst.strftime('%Y-%m-%d %H:%M CST')} | trading={is_trading} ===")

    # ── Time gating for heavy ops ──
    # Light ops (northbound + lhb + hot reasons): every cycle (~5s total)
    # Heavy ops (lockup scan + margin): every 10 min (reduced from 30 for freshness)
    run_heavy = (cst.minute % 10 < 3)  # first 3 min of each 10-min block

    # ── 1. 北向资金 (always run, non-EastMoney, ~1s) ──
    nb = fetch_northbound()
    d['northbound'] = nb
    status = '✅' if nb.get('net_yi', 0) != 0 or nb.get('points', 0) > 0 else '⚠️'
    print(f"  {status} 北向: 沪{nb['hgt_yi']}亿 深{nb['sgt_yi']}亿 净{nb['net_yi']}亿 | {nb['points']}点 | {nb['status']}")

    # ── 2. 全市场龙虎榜 (light, ~2s) ──
    lhb_full = fetch_full_lhb()
    d['lhbFull'] = lhb_full
    print(f"  {'✅' if lhb_full['total'] else '⚠️'} 龙虎榜: {lhb_full['total']}条 | {lhb_full['status']}")

    # ── 3. 同花顺热点 (always run, non-EastMoney, ~1s) ──
    hot = fetch_hot_reasons()
    d['_hotReasons'] = hot
    top_tags = ', '.join([f"{t['tag']}({t['count']})" for t in hot.get('topReasons', [])[:8]])
    print(f"  {'✅' if hot['total'] else '⚠️'} 热点归因: {hot['total']}只 | Top: {top_tags} | {hot.get('status','')}")

    # ── Code list extraction (always, used by heavy ops) ──
    codes_to_scan = set()
    for lev in d.get('layout', []):
        for s in lev.get('stocks', []):
            parts = s.split() if s else []
            if parts and len(parts[0]) == 6:
                codes_to_scan.add(parts[0])
    for sec, stocks in d.get('sectorStocks', {}).items():
        for s in stocks:
            c = s.get('c', '') if isinstance(s, dict) else (s.split()[0] if s else '')
            if c and len(c) == 6:
                codes_to_scan.add(c)
    code_list = sorted(codes_to_scan)[:80]

    # ── 4. 限售解禁 (heavy, every 30min) ──
    if run_heavy:

        lockup = fetch_lockup_alerts(code_list) if code_list else {"scanned": 0, "alerts": [], "forwardDays": 90}
        d['lockupAlerts'] = lockup
        lockup_icon = '🔴' if lockup['alerts'] else '✅'
        print(f"  {lockup_icon} 解禁预警: 扫描{lockup['scanned']}只, {len(lockup['alerts'])}批待解禁 [30min batch]")
    else:
        if 'lockupAlerts' not in d:
            d['lockupAlerts'] = {"scanned": 0, "alerts": [], "forwardDays": 90, "status": "pending next cycle"}
        print(f"  ⏭️  解禁预警: skipped (next at :00/:30)")

    # ── 5. 融资融券 (heavy, every 30min) ──
    if run_heavy and code_list:
        top_codes = code_list[:30]
        margin = fetch_margin_summary(top_codes)
        d['marginSummary'] = margin
        inc = sum(1 for s in margin['stocks'] if s.get('change_5d', 0) > 0)
        print(f"  ✅ 融资融券: {len(margin['stocks'])}只, {inc}只加杠杆 [30min batch]")
    elif not run_heavy:
        # Preserve existing or set empty defaults
        if 'lockupAlerts' not in d:
            d['lockupAlerts'] = {"scanned": 0, "alerts": [], "forwardDays": 90, "status": "pending next cycle"}
        if 'marginSummary' not in d:
            d['marginSummary'] = {"stocks": [], "status": "pending next cycle"}
        print(f"  ⏭️  融资融券/解禁: skipped (next at :00/:30)")
    else:
        print(f"  ⚠️  融资融券: no codes to scan")

    # ── Save (atomic write: temp file → rename) ──
    d['updated'] = cst.strftime('%Y-%m-%d %H:%M CST') + ' (enriched)'
    tmp_path = DATA_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_PATH)

    print(f"Enrich done → {DATA_PATH}")


if __name__ == '__main__':
    main()
