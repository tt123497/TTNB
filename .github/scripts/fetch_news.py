#!/usr/bin/env python3
"""
Real-time A-share news fetcher. Two separate feeds:
  1. _newsSector — our 62 sector news (for pre-positioning / layout)
  2. _newsMarket — macro / A-share market news (央行/证监会/北向/大盘 etc.)

Sources: Sina Finance (4 channels) + EastMoney announcements (market-moving types).
Runs every 5 min via live-update.yml. AI sentinel reads both feeds.
"""
import json, os, re, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# ═══ Sector keywords (62 sectors) ═══
SECTOR_KW = [
    '六氟化钨','WF6','电子特气','钨矿','钨精矿','钼矿','稀土永磁','钕铁硼',
    'AI芯片','GPU','算力','算电','HBM','存算一体',
    'CPO','硅光','光模块','光芯片','中际旭创','天孚','新易盛','源杰',
    'PCB','覆铜板','MLCC','电容','被动元件','电子树脂','PPE','铜箔','HVLP',
    '存储','佰维','江波龙','长江存储','长鑫',
    '液冷','散热','交换机','服务器','超节点','数据中心','AIDC',
    '半导体','光刻胶','先进封装','CoWoS','硅片','靶材',
    '机器人','Optimus','宇树','绿的谐波','拓普','三花','执行器',
    '商业航天','SpaceX','千帆','卫星','朱雀','星链',
    '固态电池','低空经济','eVTOL','民航法','飞行汽车',
    '电网设备','特高压','火电','电力','变压器','GIS','电缆',
    '风电','光伏','储能','锂矿','锂电池','新能源车','电解液','隔膜',
    '煤炭','黄金','铜','铝','钢铁','化工','MDI',
    '银行','券商','保险','地产','房贷',
    '白酒','茅台','五粮液','医药','CRO','医疗器械','迈瑞','联影',
    '钼','钨','稀土','小金属','核能','量子',
]

# ═══ Market/macro keywords ═══
MARKET_KW = [
    'A股','沪指','深指','创业板','科创板','沪深300','上证50','中证500',
    '涨停','跌停','跌停潮','涨停潮','炸板','封板','连板',
    '北向资金','主力资金','机构','游资','ETF','公募','私募',
    'IPO','上市','退市','借壳','并购重组','IPO暂缓','IPO重启',
    '央行','降息','降准','加息','LPR','MLF','逆回购','SLF','社融','M2',
    '证监会','交易所','国常会','国务院','发改委','工信部','商务部',
    '赤字','国债','地方债','特别国债',
    '人民币','汇率','美元','美联储','FOMC','降息路径',
    'GDP','PMI','CPI','PPI','社零','固投','进出口',
    '半年报','年报','季报','业绩预告','业绩快报',
    '分红','回购','增持','减持','锁定期','解禁',
    '2万亿','万亿','百万亿','千亿',
    '牛市','熊市','踏空','追高','抄底','多空',
    '外围','美股','港股','日股','欧股','纳指','标普','道指',
    '美联储','FOMC','非农','CPI','PPI','美债','美指',
    '地缘','中东','俄罗斯','伊朗','朝鲜','关税','制裁',
    '以色列','贝鲁特','加沙','莫斯科','基辅','北约',
    '英伟达','苹果','微软','谷歌','特斯拉','亚马逊','Meta',
    '台积电','三星','SK海力士','ASML','东京电子',
    '原油','布伦特','WTI','黄金期货','伦敦金','LME',
]

# ═══ Noise patterns to drop ═══
NOISE_KW = [
    # Pure non-market content only — geopolitics/foreign events pass through
    '足球','世界杯','奥运','NBA','英超','欧冠','比赛','联赛','杯赛','决赛',
    '明星','婚礼','离婚','八卦','娱乐','综艺','节目','歌曲','电影',
    '天气预报','地震','洪水','飓风','海啸','火山',
    '动物','猫','狗','熊猫','企鹅','鲸鱼',
    '机器人杯','围棋','象棋','桥牌','牌类','电竞','游戏','手游',
]

def fetch_json(url, timeout=10, retries=2):
    for attempt in range(retries):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/json',
                'Referer': 'https://finance.sina.com.cn/'})
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', errors='replace'))
        except:
            if attempt < retries - 1:
                time.sleep(1)
    return None

def fetch_sina_news():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    sector_news = []
    market_news = []

    # Channels: 2512=股票, 2516=A股, 2509=7x24财经, 1689=产业
    channels = [('2512', '股票'), ('2516', 'A股'), ('2509', '7x24财经'), ('1689', '产业')]
    for ch_id, ch_name in channels:
        url = f'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid={ch_id}&k=&num=30&page=1&r={time.time()}'
        data = fetch_json(url)
        if not data or not data.get('result'):
            continue
        items = data['result'].get('data', [])
        for it in items:
            title = it.get('title', '') or it.get('intro', '')
            url_link = it.get('url', '')
            ctime_str = it.get('ctime', '0')
            try:
                ts = datetime.fromtimestamp(int(ctime_str), tz=timezone.utc) + timedelta(hours=8)
            except:
                ts = cst

            # Drop noise + old news (>6 hours)
            if any(kw in title for kw in NOISE_KW):
                continue
            age_h = (cst - ts).total_seconds() / 3600
            if age_h > 6:
                continue

            is_sector = any(kw in title for kw in SECTOR_KW)
            is_market = any(kw in title for kw in MARKET_KW)

            entry = {
                't': title.strip()[:120],
                'u': url_link,
                'time': ts.strftime('%H:%M'),
                'src': 'sina_' + ch_name
            }

            if is_sector:
                sector_news.append(entry)
            elif is_market:
                market_news.append(entry)
            # If neither sector nor market, drop it

    return sector_news, market_news

def fetch_em_announcements():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    sector_news = []

    SIG_WORDS = ['业绩','盈利','亏损','分红','回购','增持','减持','重组',
                '停牌','退市','上市','首发','IPO','非公开','配股','可转债',
                '质押','冻结','拍卖','预亏','预增','扭亏','合同','中标',
                '重大','诉讼','*ST','ST','股权转让','要约','收购','合并',
                '涨价','停产','限产','减产','投产','量产','获批','通过']
    SKIP_WORDS = ['董事会第','监事会第','独立董事','审计委员会','薪酬与考核',
                 '制度修订','工作细则','管理制度','信息知情人','防控控股',
                 '网上申购','中签率']

    for ann_type in ['A', 'SFA', 'SHA']:
        url = f'https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=20&page_index=1&ann_type={ann_type}&sr=-1&client_source=web'
        data = fetch_json(url)
        if not data or data.get('success') != 1:
            continue

        items = data.get('data', {}).get('list', [])
        for it in items:
            title = it.get('title', '') or ''
            date_str = (it.get('notice_date', '') or '')[:10]

            if any(w in title for w in SKIP_WORDS):
                continue
            if not any(w in title for w in SIG_WORDS):
                continue
            # Must match sector keyword (announcements without sector link are noise)
            if not any(kw in title for kw in SECTOR_KW):
                continue

            codes_list = it.get('codes', [])
            stock_code = codes_list[0].get('stock_code', '') if codes_list else ''
            stock_name = codes_list[0].get('short_name', '') if codes_list else ''

            sector_news.append({
                't': f'{stock_name}: {title[:90]}' if stock_name else title[:110],
                'u': f'https://data.eastmoney.com/notices/detail/{stock_code}.html' if stock_code else '',
                'time': date_str[-5:] if len(date_str) >= 5 else date_str,
                'src': 'em_announcement',
                's': f'{stock_code} {stock_name}' if stock_code else ''
            })

    return sector_news

def dedup(news_list):
    seen = set()
    result = []
    for n in news_list:
        key = n['t'][:50]
        if key not in seen:
            seen.add(key)
            result.append(n)
    result.sort(key=lambda n: n.get('time', ''), reverse=True)
    return result

def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)

    print('Fetching Sina...')
    sina_sector, sina_market = fetch_sina_news()
    print(f'  Sina sector: {len(sina_sector)}, market: {len(sina_market)}')

    print('Fetching announcements...')
    em_sector = fetch_em_announcements()
    print(f'  EM sector: {len(em_sector)}')

    # Merge + dedup
    sector_all = dedup(sina_sector + em_sector)
    market_all = dedup(sina_market)

    # Write
    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                pass

    # Strip temp field 's' before saving
    for a in sector_all:
        a.pop('s', None)

    data['_newsSector'] = sector_all[:25]
    data['_newsMarket'] = market_all[:20]
    data['_newsMeta'] = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'sector': len(sector_all),
        'market': len(market_all),
        'match_sectors': sorted(set(
            kw for n in sector_all for kw in SECTOR_KW if kw in (n.get('t','') or '')
        ))[:30]
    }

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total = len(sector_all) + len(market_all)
    print(f'Done: {len(sector_all)} sector + {len(market_all)} market = {total} news')
    if sector_all:
        print(f'  Top sector: {sector_all[0].get("time","?")} {sector_all[0]["t"][:80]}')
    if market_all:
        print(f'  Top market: {market_all[0].get("time","?")} {market_all[0]["t"][:80]}')

if __name__ == '__main__':
    main()
