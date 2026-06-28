#!/usr/bin/env python3
"""
news_sources.py — 新闻采集公共模块

提取自 run_update.py 和 news_watch.py 的重复逻辑。
两个脚本都 import 此模块, 确保关键词列表和采集逻辑一致。

用法:
  from news_sources import SECTOR_KW, MARKET_KW, NOISE_KW, fetch_all_news, fetch_global_news
"""
import json, time, uuid
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

CST = timezone(timedelta(hours=8))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# ═══════════════════════════════════════════════════════════════
# 关键词列表 — 单一数据源, 不再在两个文件中各维护一份
# ═══════════════════════════════════════════════════════════════

SECTOR_KW = [
    '六氟化钨','WF6','电子特气','钨矿','钨精矿','钼矿','稀土永磁','钕铁硼',
    'AI芯片','GPU','算力','HBM','CPO','硅光','光模块','光芯片',
    '中际旭创','天孚','新易盛','PCB','覆铜板','MLCC','电容','被动元件',
    '电子树脂','PPE','铜箔','HVLP','存储','佰维','江波龙',
    '液冷','散热','交换机','服务器','超节点','数据中心','AIDC',
    '半导体','光刻胶','先进封装','CoWoS','硅片','靶材',
    '机器人','Optimus','宇树','绿的谐波','拓普',
    '商业航天','SpaceX','千帆','卫星','朱雀',
    '固态电池','低空经济','eVTOL',
    '电网设备','特高压','火电','变压器','风电','光伏','储能',
    '锂矿','锂电池','新能源车','电解液','隔膜',
    '煤炭','黄金','铜','铝','钢铁','化工','银行','券商','保险',
    '白酒','茅台','医药','CRO','医疗器械',
    '钼','钨','稀土','小金属','核能','量子',
    'AI眼镜','6G','连接器','电源','DrMOS',
    '培育钻石','碳纤维','盐湖提锂','钠电池','锰','钒电池',
]

MARKET_KW = [
    'A股','沪指','深指','创业板','科创板','沪深300',
    '涨停','跌停','北向资金','主力资金','机构','游资',
    'ETF','央行','降息','降准','LPR','MLF','社融','M2',
    '证监会','交易所','国常会','国务院','发改委','工信部',
    '人民币','汇率','美元','美联储','FOMC',
    'GDP','PMI','CPI','PPI',
    '半年报','年报','季报','业绩预告','分红','回购','增持','减持','解禁',
    '牛市','熊市','美股','港股','纳指','标普','道指',
    '非农','美债','地缘','中东','俄罗斯','伊朗','朝鲜','关税','制裁',
    '英伟达','苹果','微软','谷歌','特斯拉','亚马逊','Meta',
    '台积电','三星','SK海力士','ASML',
    '原油','布伦特','WTI','黄金期货','LME',
    'IPO','并购重组','万亿',
]

NOISE_KW = [
    '足球','世界杯','奥运','NBA','英超','欧冠','比赛','联赛',
    '明星','婚礼','离婚','八卦','娱乐','综艺','唱歌','电影',
    '天气预报','地震','洪水','动物','猫','狗','熊猫',
    '围棋','象棋','电竞','游戏','手游',
]

# ═══════════════════════════════════════════════════════════════
# 采集函数
# ═══════════════════════════════════════════════════════════════

def _fetch(url, timeout=10):
    """HTTP GET JSON — 统一封装"""
    try:
        req = Request(url, headers={
            'User-Agent': UA,
            'Referer': 'https://finance.sina.com.cn/',
        })
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', errors='replace'))
    except Exception:
        return None

def _now():
    return datetime.now(timezone.utc) + timedelta(hours=8)

def _is_trading(cst):
    return cst.weekday() < 5 and 9 <= cst.hour < 15

def fetch_sina_news():
    """新浪4频道: 股票/A股/7x24/产业"""
    cst = _now()
    sn, mn = [], []
    for ch, nm in [('2512','股票'), ('2516','A股'), ('2509','7x24'), ('1689','产业')]:
        d = _fetch(f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid={ch}&k=&num=60&page=1&r={time.time()}')
        if not d or not d.get('result'): continue
        for it in d['result'].get('data', []):
            t = it.get('title','') or it.get('intro','')
            if not t or any(k in t for k in NOISE_KW): continue
            try:
                ts = datetime.fromtimestamp(int(it.get('ctime','0')), tz=timezone.utc) + timedelta(hours=8)
            except Exception:
                ts = cst
            max_age = 0.5 if _is_trading(cst) else 24
            if (cst - ts).total_seconds() / 3600 > max_age: continue
            e = {'t': t.strip()[:120], 'u': it.get('url',''), 'time': ts.strftime('%H:%M'), 'src': 'sina_'+nm}
            if any(k in t for k in SECTOR_KW): sn.append(e)
            elif any(k in t for k in MARKET_KW): mn.append(e)
    return sn, mn

def fetch_em_announcements():
    """东财公告"""
    SIG = ['业绩','盈利','亏损','分红','回购','增持','减持','重组','停牌','退市',
           '上市','首发','IPO','非公开','配股','质押','冻结','拍卖','预亏','预增',
           '扭亏','合同','中标','重大','诉讼','*ST','ST','股权转让','要约','收购',
           '合并','涨价','停产','限产','减产','投产','量产','获批','通过']
    SKIP = ['董事会第','监事会第','独立董事','审计委员会','薪酬与考核','制度修订',
            '工作细则','管理制度','信息知情人','防控控股','网上申购','中签率']
    sn, mn = [], []
    for tp in ['A','SFA','SHA']:
        d = _fetch(f'https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=40&page_index=1&ann_type={tp}&sr=-1&client_source=web')
        if not d or d.get('success') != 1: continue
        for it in d.get('data',{}).get('list',[]):
            t = it.get('title','') or ''
            if any(w in t for w in SKIP) or not any(w in t for w in SIG): continue
            cds = it.get('codes',[])
            sc = cds[0].get('stock_code','') if cds else ''
            sm = cds[0].get('short_name','') if cds else ''
            ds = (it.get('notice_date','') or '')[:10]
            e = {
                't': f'{sm}: {t[:90]}' if sm else t[:110],
                'u': f'https://data.eastmoney.com/notices/detail/{sc}.html' if sc else '',
                'time': ds[-5:] if len(ds) >= 5 else ds,
                'src': 'em_ann',
            }
            (sn if any(k in t for k in SECTOR_KW) else mn).append(e)
    return sn, mn

def fetch_wallstreetcn():
    """华尔街见闻"""
    cst = _now()
    rs = []
    for ch, nm in [('global-channel','全球'), ('china-channel','中国')]:
        d = _fetch(f'https://api-one.wallstcn.com/apiv1/content/lives?channel={ch}&client=pc&limit=40&first=1', timeout=10)
        if not d or not d.get('data'): continue
        for it in d['data'].get('items',[]):
            t = it.get('title','') or it.get('content_text','') or ''
            u = it.get('uri','') or ''
            if u and not u.startswith('http'): u = 'https://wallstreetcn.com' + u
            try:
                ts = datetime.fromtimestamp(it.get('display_time',0) or 0, tz=timezone.utc) + timedelta(hours=8)
            except Exception:
                ts = cst
            if (cst - ts).total_seconds() / 3600 > 1: continue
            if any(k in t for k in SECTOR_KW) or any(k in t for k in MARKET_KW):
                rs.append({'t': t.strip()[:120], 'u': u, 'time': ts.strftime('%H:%M'), 'src': 'wscn_'+nm})
        time.sleep(0.3)
    return rs

def fetch_em_7x24():
    """东财7x24全球资讯"""
    u = f'https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=30&req_trace={uuid.uuid4()}'
    d = _fetch(u, timeout=8)
    if not d:
        return {'headlines': [], 'updated': '', 'status': 'fail'}
    vs = d.get('data',{}).get('fastNewsList',[]) or []
    return {
        'headlines': [
            {'t': (v.get('title','') or '')[:130],
             's': (v.get('summary','') or '')[:90],
             'ts': v.get('showTime','')}
            for v in vs[:25]
        ],
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'status': 'ok' if vs else 'empty',
    }

def _dedup(news_list):
    """去重 + 按时间倒序"""
    seen = set()
    result = []
    for n in news_list:
        key = n['t'][:50]
        if key not in seen:
            seen.add(key)
            result.append(n)
    result.sort(key=lambda n: n.get('time',''), reverse=True)
    return result

def fetch_all_news():
    """
    采集全部新闻源, 返回 (sector_news, market_news)
    用于 run_update.py
    """
    sina_s, sina_m = fetch_sina_news()
    em_s, em_m = fetch_em_announcements()
    wscn = fetch_wallstreetcn()
    sector_all = _dedup(sina_s + em_s)
    market_all = _dedup(sina_m + em_m + wscn)
    return sector_all[:50], market_all[:50]

def fetch_global_news():
    """
    东财7x24全球资讯 (用于 run_update.py 的 globalNews 字段)
    """
    return fetch_em_7x24()


if __name__ == '__main__':
    # 测试
    s, m = fetch_all_news()
    g = fetch_global_news()
    print(f'赛道新闻: {len(s)} 条')
    print(f'市场新闻: {len(m)} 条')
    print(f'7x24快讯: {len(g.get("headlines",[]))} 条')
