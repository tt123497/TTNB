#!/usr/bin/env python3
"""
TTNB Tier A — lightweight data endpoints from a-stock-data.
Runs every 5-min cycle in GitHub Actions cloud (US IP, urllib only).

Endpoints:
  A1. 东财全球资讯7x24 → data.json.globalNews
  A2. 行业板块排名增强 → data.json.industryRank
  A3. 腾讯PE/PB/市值 → data.json.tencentVal
  A4. 巨潮公告(5只关键标的) → data.json.cninfoAlerts  [30-min]
  A5. 东财行业研报(全行业) → data.json.indReports  [30-min]

Sources: simonlin1212/a-stock-data SKILL.md V3.2.4
"""
import json, os, time, random, uuid
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

# ═══ EastMoney throttle (same as fetch_enrich.py) ═══
_em_last = 0.0
EM_MIN = 1.2

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

def fetch_json(url, encoding='utf-8', extra_headers=None):
    """Plain fetch without throttle (for non-EastMoney sources)."""
    try:
        headers = {'User-Agent': UA, 'Accept': 'application/json'}
        if extra_headers:
            headers.update(extra_headers)
        req = Request(url, headers=headers)
        with urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode(encoding, errors='replace'))
    except:
        return None


# ═══ A1: 东财全球资讯7x24 ═══
def fetch_global_news():
    """东财7x24快讯 — single call, returns 25 headlines."""
    trace = str(uuid.uuid4())
    url = f"https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=25&req_trace={trace}"
    text = _em_fetch(url, extra_headers={'Referer': 'https://kuaixun.eastmoney.com/'})
    if not text:
        return {"headlines": [], "updated": "", "status": "fetch failed"}
    try:
        d = json.loads(text)
        if d.get('code') != '0' and d.get('code') != 0:
            return {"headlines": [], "updated": "", "status": f"API error: {d.get('message','?')}"}
        items = (d.get("data") or {}).get("fastNewsList", [])
        if not items:
            return {"headlines": [], "updated": "", "status": "empty"}
        headlines = []
        for item in items:
            headlines.append({
                "t": (item.get("title") or "")[:130],
                "s": (item.get("summary") or "")[:90],
                "ts": item.get("showTime", "")
            })
        return {
            "headlines": headlines[:25],
            "updated": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            "status": "ok"
        }
    except Exception as e:
        return {"headlines": [], "updated": "", "status": f"parse error: {str(e)[:60]}"}


# ═══ A2: 行业板块排名增强 ═══
def fetch_industry_ranking():
    """Enhanced sector ranking with up/down counts + leader info."""
    url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=80&po=1&np=1&fltt=2&invt=2&fs=m:90+t:2&fields=f2,f3,f4,f12,f14,f104,f105,f140&ut=bd1d9ddb04089700cf9c27f6f7426281"
    text = _em_fetch(url, extra_headers={'Referer': 'https://quote.eastmoney.com/'})
    if not text:
        return []
    try:
        d = json.loads(text)
        items = d.get("data", {}).get("diff", [])
        if not items:
            return []
        return [{
            "n": i.get("f14", ""), "chg": round(i.get("f3", 0) or 0, 2),
            "upCnt": i.get("f104", 0) or 0, "dnCnt": i.get("f105", 0) or 0,
            "ld": i.get("f140", "") or "", "bk": i.get("f12", "")
        } for i in items if i.get("f14")]
    except:
        return []


# ═══ A3: 腾讯PE/PB/市值 ═══
def fetch_tencent_val(codes):
    """Batch PE/PB/market-cap for tracked stocks via Tencent API (no IP ban)."""
    if not codes:
        return {}
    prefixed = []
    for c in codes[:80]:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        else:
            prefixed.append(f"sz{c}")
    if not prefixed:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=12) as r:
            data = r.read().decode("gbk", errors="replace")
    except:
        return {}
    result = {}
    for line in data.strip().split("\n"):
        if "=" not in line:
            continue
        parts = line.split('"')
        if len(parts) < 2:
            continue
        vals = parts[1].split("~")
        if len(vals) < 53:
            continue
        code = vals[2]
        if not code or len(code) != 6:
            continue
        result[code] = {
            "n": vals[1], "p": float(vals[3]) if vals[3] else 0,
            "pe": round(float(vals[39]), 1) if vals[39] else 0,
            "pb": round(float(vals[46]), 1) if vals[46] else 0,
            "mcap": round(float(vals[45]) or 0, 0),
            "chg": round(float(vals[32]) if vals[32] else 0, 2),
            "to": round(float(vals[38]) if vals[38] else 0, 2),
        }
    return result


# ═══ A4: 巨潮公告(5只关键标的) ═══
def fetch_cninfo_alerts(codes):
    """Latest 3 announcements for top-5 key stocks from cninfo."""
    alerts = []
    for code in codes[:5]:
        time.sleep(0.5)
        try:
            orgId = _cninfo_orgid(code)
            if not orgId:
                continue
            url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
            params = f"pageNum=1&pageSize=3&column=szse&tabName=fulltext&stock={code}&orgId={orgId}"
            req = Request(url, data=params.encode('utf-8'),
                          headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
            with urlopen(req, timeout=12) as r:
                d = json.loads(r.read().decode('utf-8'))
            for ann in d.get("announcements", []):
                alerts.append({
                    "c": code,
                    "t": (ann.get("announcementTitle") or "")[:100],
                    "d": (ann.get("announcementTime") or "")[:10],
                })
        except:
            pass
    return {"alerts": alerts[:20], "status": "ok" if alerts else "no data"}


def _cninfo_orgid(code):
    """Lookup orgId for stock code (cached)."""
    org_map = {
        "600519": "gssz0600519", "000858": "gssz0000858",
        "601318": "gssh0601318", "600549": "gssh0600549",
        "002085": "gssz0002085", "603986": "gssh0603986",
        "002460": "gssz0002460", "688017": "gssh0688017",
        "300750": "gssz0300750", "002475": "gssz0002475",
    }
    return org_map.get(code, f"gssz0{code}" if code.startswith(("0","3")) else f"gssh0{code}")


# ═══ A5: 东财行业研报 ═══
def fetch_ind_reports():
    """Latest 10 industry reports from EastMoney reportapi (qType=1)."""
    url = "https://reportapi.eastmoney.com/report/list"
    params = "cb=&pageSize=10&pageNo=1&qType=1&industryCode=*&beginTime=&endTime="
    text = _em_fetch(f"{url}?{params}")
    if not text:
        return {"reports": [], "status": "fetch failed"}
    try:
        d = json.loads(text)
        items = d.get("data", [])
        reports = []
        for it in items[:10]:
            reports.append({
                "t": (it.get("title") or "")[:100],
                "org": (it.get("orgName") or "")[:30],
                "ind": (it.get("industryName") or "")[:30],
                "rating": (it.get("rating") or "")[:20],
                "d": str(it.get("publishDate") or "")[:10],
            })
        return {"reports": reports, "updated": datetime.now(timezone.utc).strftime('%Y-%m-%d'), "status": "ok"}
    except:
        return {"reports": [], "status": "parse error"}


# ═══ Main ═══
def main():
    if not os.path.exists(DATA_PATH):
        print("data.json not found — run fetch_data.py first")
        return

    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        d = json.load(f)

    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    is_heavy = (cst.minute % 30 < 5)
    print(f"=== TierA {cst.strftime('%Y-%m-%d %H:%M CST')} heavy={is_heavy} ===")

    # ── A1: Global news (every cycle, ~1.5s) ──
    gn = fetch_global_news()
    d['globalNews'] = gn
    print(f"  {'✅' if gn['headlines'] else '⚠️'} 东财7x24: {len(gn['headlines'])}条 | {gn['status']}")

    # ── A2: Industry ranking (every cycle, ~1.5s) ──
    ir = fetch_industry_ranking()
    d['industryRank'] = ir
    top3 = ', '.join([f"{r['n']} {r['chg']:+.1f}%" for r in ir[:3]])
    print(f"  {'✅' if ir else '⚠️'} 行业排名: {len(ir)}个 | Top: {top3}")

    # ── A3: Tencent valuation (every cycle, ~1.5s) ──
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
    code_list = sorted(codes)[:80]

    tv = fetch_tencent_val(code_list)
    d['tencentVal'] = tv
    print(f"  {'✅' if tv else '⚠️'} 腾讯估值: {len(tv)}只")

    # ── A4+A5: Heavy (every 30 min) ──
    if is_heavy:
        ca = fetch_cninfo_alerts(code_list[:5])
        d['cninfoAlerts'] = ca
        print(f"  {'✅' if ca['alerts'] else '⚠️'} 巨潮公告: {len(ca['alerts'])}条 [30min]")

        irp = fetch_ind_reports()
        d['indReports'] = irp
        print(f"  {'✅' if irp['reports'] else '⚠️'} 行业研报: {len(irp['reports'])}篇 [30min]")
    else:
        if 'cninfoAlerts' not in d:
            d['cninfoAlerts'] = {"alerts": [], "status": "pending"}
        if 'indReports' not in d:
            d['indReports'] = {"reports": [], "status": "pending"}
        print(f"  ⏭️  巨潮公告+行业研报: skipped (next at :00/:30)")

    # ── Save ──
    d['updated'] = cst.strftime('%Y-%m-%d %H:%M CST') + ' (tierA)'
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

    print(f"TierA done → {DATA_PATH}")


if __name__ == '__main__':
    main()
