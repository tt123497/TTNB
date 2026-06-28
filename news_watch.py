#!/usr/bin/env python3
"""news_watch — 60秒快讯守护进程, 全HTTP零封禁

架构说明 (2026-06-28 修复并发写入竞态):
  本进程只写 news.json, 不再读写 data.json。
  run_update.py (GitHub Actions) 只写 data.json。
  两者写不同文件, git rebase 不再冲突, 不再丢数据。
  index.html 分别 fetch data.json 和 news.json。
"""
import json, os, sys, time, re, uuid
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_PATH = os.path.join(DIR, 'news.json')   # 独立文件, 不再碰 data.json
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
CST = timezone(timedelta(hours=8))

# 关键词列表 — 与 news_sources.py 保持一致 (单一数据源)
try:
    from news_sources import SECTOR_KW, MARKET_KW, NOISE_KW
except ImportError:
    # 兜底: news_sources.py 不存在时用内置列表
    SECTOR_KW = ['六氟化钨','WF6','AI芯片','GPU','HBM','CPO','硅光','光模块','PCB','MLCC','电子树脂','PPE','铜箔','HVLP','存储','液冷','服务器','数据中心','AIDC','半导体','光刻胶','先进封装','CoWoS','靶材','机器人','Optimus','商业航天','SpaceX','卫星','固态电池','低空经济','eVTOL','电网','特高压','火电','风电','光伏','储能','锂矿','锂电池','新能源车','稀土','小金属','核能','量子','6G','连接器','AI眼镜','碳纤维','钨','钼','钠电池']
    MARKET_KW = ['A股','沪指','跌停','涨停','北向资金','主力资金','央行','降息','降准','LPR','证监会','人民币','汇率','美联储','GDP','PMI','CPI','半年报','红利','回购','增持','减持','解禁','IPO','美股','港股','纳指','标普','英伟达','苹果','特斯拉','台积电','原油','黄金','地缘','中东','关税','制裁','非农']
    NOISE_KW = ['足球','世界杯','奥运','NBA','联赛','明星','婚礼','八卦','娱乐','综艺','电影','地震','洪水','猫','狗','熊猫','围棋','电竞','游戏','手游']

def _fetch(url, extra_headers=None, timeout=10):
    try:
        h = {'User-Agent': UA, 'Referer': 'https://finance.sina.com.cn/'}
        if extra_headers: h.update(extra_headers)
        with urlopen(Request(url, headers=h), timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', errors='replace'))
    except Exception: return None

def _now(): return datetime.now(timezone.utc) + timedelta(hours=8)

def _is_trading(cst):
    """交易时段判断 — 周一到周五 9-15点 (节假日判断由 run_update 的 chinese_calendar 负责)"""
    return cst.weekday() < 5 and 9 <= cst.hour < 15

def _sina_news():
    cst, sn, mn = _now(), [], []
    for ch, nm in [('2512','股票'),('2516','A股'),('2509','7x24'),('1689','产业')]:
        d = _fetch(f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid={ch}&k=&num=60&page=1&r={time.time()}')
        if not d or not d.get('result'): continue
        for it in d['result'].get('data',[]):
            t = it.get('title','') or it.get('intro','')
            if not t or any(k in t for k in NOISE_KW): continue
            try: ts = datetime.fromtimestamp(int(it.get('ctime','0')), tz=timezone.utc) + timedelta(hours=8)
            except Exception: ts = cst
            max_age = 0.5 if _is_trading(cst) else 24
            if (cst-ts).total_seconds()/3600 > max_age: continue
            e = {'t': t.strip()[:120], 'u': it.get('url',''), 'time': ts.strftime('%H:%M'), 'src': 'sina_'+nm}
            if any(k in t for k in SECTOR_KW): sn.append(e)
            elif any(k in t for k in MARKET_KW): mn.append(e)
    return sn, mn

def _em_ann():
    SIG = ['业绩','盈利','亏损','分红','回购','增持','减持','重组','停牌','IPO','配股','质押','冻结','预亏','预增','扭亏','合同','中标','重大','诉讼','*ST','ST','股权转让','要约','收购','合并','涨价','停产','限产','减产','投产','量产','获批']
    SKIP = ['董事会第','监事会第','独立董事','审计委员会','薪酬与考核','制度修订','工作细则','管理制度','知情人','申购','中签率']
    sn, mn = [], []
    for tp in ['A','SFA','SHA']:
        d = _fetch(f'https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=40&page_index=1&ann_type={tp}&sr=-1&client_source=web')
        if not d or d.get('success')!=1: continue
        for it in d.get('data',{}).get('list',[]):
            t = it.get('title','') or ''
            if any(w in t for w in SKIP) or not any(w in t for w in SIG): continue
            cds = it.get('codes',[]); sc = cds[0].get('stock_code','') if cds else ''; sm = cds[0].get('short_name','') if cds else ''
            ds = (it.get('notice_date','') or '')[:10]
            e = {'t': f'{sm}: {t[:90]}' if sm else t[:110], 'u': f'https://data.eastmoney.com/notices/detail/{sc}.html' if sc else '', 'time': ds[-5:] if len(ds)>=5 else ds, 'src': 'em_ann'}
            (sn if any(k in t for k in SECTOR_KW) else mn).append(e)
    return sn, mn

def _wscn():
    cst, rs = _now(), []
    for ch, nm in [('global-channel','全球'),('china-channel','中国')]:
        d = _fetch(f'https://api-one.wallstcn.com/apiv1/content/lives?channel={ch}&client=pc&limit=40&first=1')
        if not d or not d.get('data'): continue
        for it in d['data'].get('items',[]):
            t = it.get('title','') or it.get('content_text','') or ''
            u = it.get('uri','') or ''
            if u and not u.startswith('http'): u = 'https://wallstreetcn.com'+u
            try: ts = datetime.fromtimestamp(it.get('display_time',0) or 0, tz=timezone.utc) + timedelta(hours=8)
            except Exception: ts = cst
            if (cst-ts).total_seconds()/3600 > 1: continue
            if any(k in t for k in SECTOR_KW) or any(k in t for k in MARKET_KW):
                rs.append({'t': t.strip()[:120], 'u': u, 'time': ts.strftime('%H:%M'), 'src': 'wscn_'+nm})
        time.sleep(0.2)
    return rs

def _em_7x24():
    u = f'https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=30&req_trace={uuid.uuid4()}'
    d = _fetch(u, timeout=8)
    if not d: return {'headlines':[], 'updated':'', 'status':'fail'}
    vs = d.get('data',{}).get('fastNewsList',[]) or []
    return {'headlines': [{'t': (v.get('title','') or '')[:130], 's': (v.get('summary','') or '')[:90], 'ts': v.get('showTime','')} for v in vs[:25]], 'updated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'status': 'ok'}

def _dedup(ns):
    seen=set(); rs=[]
    for n in ns:
        k=n['t'][:50]
        if k not in seen: seen.add(k); rs.append(n)
    rs.sort(key=lambda n: n.get('time',''), reverse=True)
    return rs

def _save_news(news_data):
    """原子写入 news.json (不再写 data.json)"""
    tmp = NEWS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(news_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NEWS_PATH)

def _git_push():
    """只 commit + push news.json, 不碰 data.json — 避免与 run_update.py 冲突"""
    for i in range(3):
        cmd = (f'cd {DIR} && git add news.json 2>/dev/null '
               f'&& git commit -m "📡 {_now().strftime("%H:%M")} 快讯" 2>/dev/null '
               f'&& git pull --rebase origin main 2>/dev/null '
               f'&& git push origin main 2>/dev/null')
        if os.system(cmd) == 0:
            return True
        time.sleep(2)
    return False

def main_loop():
    print(f'📡 news_watch 启动: 新浪4频道 + 东财公告 + 华尔街见闻 + 东财7x24 (全HTTP, 零封禁)')
    print(f'   写入目标: news.json (独立文件, 不再写 data.json)')
    while True:
        try:
            cst = _now()
            s1,m1 = _sina_news(); s2,m2 = _em_ann(); w = _wscn(); g = _em_7x24()
            ns = _dedup(s1+s2); nm = _dedup(m1+m2+w)
            print(f'[{cst.strftime("%H:%M:%S")}] 赛道:{len(ns)} 市场:{len(nm)} 7x24:{len(g.get("headlines",[]))}')

            # 只写 news.json, 不再读写 data.json
            news_data = {
                '_newsSector': ns[:50],
                '_newsMarket': nm[:50],
                '_newsMeta': {
                    'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
                    'sector': len(ns),
                    'market': len(nm),
                },
                'globalNews': g,
            }
            _save_news(news_data)
            _git_push()
        except Exception as e:
            print(f'ERR: {e}')
        time.sleep(60)

if __name__ == '__main__':
    os.chdir(DIR)
    main_loop()
