#!/usr/bin/env python3
"""news_fetch_once — 单次快讯抓取, 60秒内完成, 全HTTP零封禁"""
import json, os, sys, time, re, uuid
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_PATH = os.path.join(DIR, 'news.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
CST = timezone(timedelta(hours=8))
SECTOR_KW = ['六氟化钨','WF6','AI芯片','GPU','HBM','CPO','硅光','光模块','光纤光缆','PCB','MLCC','电子树脂','PPE','铜箔','HVLP','存储','液冷','服务器','数据中心','AIDC','半导体','光刻胶','先进封装','CoWoS','靶材','机器人','Optimus','商业航天','SpaceX','卫星','固态电池','低空经济','eVTOL','电网','特高压','火电','风电','光伏','储能','锂矿','锂电池','新能源车','稀土','小金属','核能','量子','6G','连接器','AI眼镜','碳纤维','钨','钼','钠电池','玻璃基板','TGV','培育钻石','DrMOS','电源','算电协同','Token工厂','医药','CRO','医疗器械','白酒','食品','银行','券商','保险','房地产','煤炭','黄金','铜铝','贵金属','钢铁','化工','超导','空间计算','交换机']
MARKET_KW = [
    # 指数/市场宽度
    'A股','沪指','深指','创业板','科创板','沪深300','上证50','中证500','中证1000',
    '涨停','跌停','跌停潮','涨停潮','炸板','封板','连板',
    '北向资金','主力资金','机构','游资','ETF','公募','私募','GJD','国家队',
    '成交额','成交量','万亿','缩量','放量','地量','天量',
    # IPO/退市/并购
    'IPO','上市','退市','借壳','并购重组',
    # 央行/货币政策
    '央行','降息','降准','加息','LPR','MLF','逆回购','SLF','社融','M2','M1',
    '存款利率','贷款利率','房贷利率',
    # 监管/政策
    '证监会','交易所','国常会','国务院','发改委','工信部','商务部','财政部',
    # 财政/债务
    '赤字','国债','地方债','特别国债','专项债',
    # 汇率/外围
    '人民币','汇率','美元','美联储','FOMC','降息路径',
    # 宏观数据
    'GDP','PMI','CPI','PPI','社零','固投','进出口','外汇储备',
    # 业绩/报表
    '半年报','年报','季报','业绩预告','业绩快报','预增','预减',
    # 公司行动
    '分红','回购','增持','减持','锁定期','解禁','股权激励',
    # 市场情绪
    '牛市','熊市','踏空','追高','抄底','多空',
    # 海外市场
    '外围','美股','港股','日股','欧股','纳指','标普','道指',
    '非农','美债','美指','鲍威尔',
    # 地缘
    '地缘','中东','俄罗斯','伊朗','朝鲜','关税','制裁',
    '以色列','贝鲁特','加沙','莫斯科','基辅','北约',
    # 大市值个股/国际巨头
    '英伟达','苹果','微软','谷歌','特斯拉','亚马逊','Meta',
    '台积电','三星','SK海力士','ASML','东京电子','OpenAI',
    # 大宗商品
    '原油','布伦特','WTI','黄金期货','伦敦金','LME','黄金',
    # 其他宏观
    '救市','平准基金','资本市场','改革开放','注册制','科创50',
    '券商研报','策略报告','年度策略','下半年','政策发力',
    '信贷','不良','拨备','资本充足率','系统重要性',
    '大股东','举牌','要约收购','资产注入','整体上市','分拆上市',
    '养老金','社保基金','保险资金','企业年金',
    '印花税','交易经手费','过户费',
]
NOISE_KW = ['足球','世界杯','奥运','NBA','联赛','明星','婚礼','八卦','娱乐','综艺','电影','地震','洪水','猫','狗','熊猫','围棋','电竞','游戏','手游']

def _fetch(url, extra_headers=None, timeout=10):
    try:
        h = {'User-Agent': UA, 'Referer': 'https://finance.sina.com.cn/'}
        if extra_headers: h.update(extra_headers)
        with urlopen(Request(url, headers=h), timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', errors='replace'))
    except: return None

def _now(): return datetime.now(timezone.utc) + timedelta(hours=8)

def _sina_news():
    cst, sn, mn = _now(), [], []
    for ch, nm in [('2512','股票'),('2516','A股'),('2509','7x24'),('1689','产业')]:
        d = _fetch(f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid={ch}&k=&num=60&page=1&r={time.time()}')
        if not d or not d.get('result'): continue
        for it in d['result'].get('data',[]):
            t = it.get('title','') or it.get('intro','')
            if not t or any(k in t for k in NOISE_KW): continue
            try: ts = datetime.fromtimestamp(int(it.get('ctime','0')), tz=timezone.utc) + timedelta(hours=8)
            except: ts = cst
            if (cst-ts).total_seconds()/3600 > (0.5 if 9<=cst.hour<15 and cst.weekday()<5 else 24): continue
            e = {'t': t.strip()[:120], 'u': it.get('url',''), 'time': ts.strftime('%H:%M'), 'src': 'sina_'+nm}
            is_sector = any(k in t for k in SECTOR_KW)
            is_market = any(k in t for k in MARKET_KW)
            if is_sector: sn.append(e)
            if is_market: mn.append(e)
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
            is_s = any(k in t for k in SECTOR_KW); is_m = any(k in t for k in MARKET_KW)
            if is_s: sn.append(e)
            if is_m: mn.append(e)
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
            except: ts = cst
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
    return {'headlines': [{'t': v.get('title','')[:130], 's': (v.get('summary','') or '')[:90], 'ts': v.get('showTime','')} for v in vs[:25]], 'updated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'status': 'ok'}

def _dedup(ns):
    seen=set(); rs=[]
    for n in ns:
        k=n['t'][:50]
        if k not in seen: seen.add(k); rs.append(n)
    rs.sort(key=lambda n: n.get('time',''), reverse=True)
    return rs

if __name__ == '__main__':
    os.chdir(DIR)
    # Single-run mode: fetch once, write news.json, exit (for cloud CI pipeline)
    LOG = os.path.join(DIR, 'news_watch_output.log')
    try:
        cst = _now()
        s1,m1 = _sina_news(); s2,m2 = _em_ann(); w = _wscn(); g = _em_7x24()
        ns = _dedup(s1+s2); nm = _dedup(m1+m2+w)
        msg = f'[{cst.strftime("%H:%M:%S")}] 赛道:{len(ns)} 市场:{len(nm)} 7x24:{len(g.get("headlines",[]))}'
        with open(LOG,'a',encoding='utf-8') as lf: lf.write(msg+'\n')

        news = {}
        if os.path.exists(NEWS_PATH):
            try: news = json.load(open(NEWS_PATH,'r',encoding='utf-8'))
            except: pass
        news['_newsSector'] = ns[:50]; news['_newsMarket'] = nm[:50]
        news['_newsMeta'] = {'updated': cst.strftime('%Y-%m-%d %H:%M CST'), 'sector': len(ns), 'market': len(nm)}
        news['globalNews'] = g
        tmp = NEWS_PATH+'.tmp'
        json.dump(news, open(tmp,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
        os.replace(tmp, NEWS_PATH)

        # 只写本地 news.json, 不推 (由 news-watch.yml 统一推送)
    except Exception as e:
        with open(LOG,'a',encoding='utf-8') as lf: lf.write(f'ERR: {e}\n')
