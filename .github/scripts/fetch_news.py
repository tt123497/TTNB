#!/usr/bin/env python3
"""
Real-time A-share news fetcher. Runs every 15 min, feeds AI sentinel.
Sources:
  1. Sina Finance rolling news (A-stock + stock channels)
  2. EastMoney announcements (market-moving types)
  3. Sector-keyword filtering for our 62 sectors

Output: _newsFeed array in data.json with {t, b, s, u, time} items.
AI sentinel reads _newsFeed to write briefing with real source data.
"""
import json, os, re, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# Our 62 sector keywords for filtering
SECTOR_KW = [
    '六氟化钨', 'WF6', '电子特气', '钨', '钼', '稀土',
    'AI芯片', 'GPU', '算力', '寒武纪', '海光',
    'CPO', '硅光', '光模块', '中际旭创', '天孚', '新易盛',
    'PCB', '覆铜板', 'MLCC', '电容', '电子树脂', 'PPE', '铜箔',
    'HBM', '存储', '佰维', '江波龙',
    '服务器', '液冷', '散热', '交换机', '数据中心', 'AIDC',
    '半导体', '光刻胶', '先进封装', 'CoWoS', '硅片',
    '机器人', 'Optimus', '特斯拉', '宇树', '绿的谐波',
    '商业航天', 'SpaceX', '千帆', '卫星', '朱雀',
    '固态电池', '低空经济', 'eVTOL', '民航法',
    '电网', '特高压', '火电', '电力',
    '风电', '光伏', '储能', '锂矿', '锂电池', '新能源车',
    '煤炭', '黄金', '铜', '铝', '化工', '钢铁',
    '银行', '券商', '保险', '房地产', '地产',
    '白酒', '茅台', '五粮液', '医药', 'CRO', '医疗器械',
    'MLCC', '钕铁硼', '永磁', '核电', '量子',
]

def fetch_json(url, timeout=10, retries=2):
    for attempt in range(retries):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/json', 'Referer': 'https://finance.sina.com.cn/'})
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', errors='replace'))
        except:
            if attempt < retries - 1:
                time.sleep(1)
    return None

def fetch_sina_news():
    """Fetch A-stock related news from Sina finance channels."""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    all_news = []

    # Sina finance channels: 2512=股票, 2516=A股, 2509=7x24全球财经, 1689=产业
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
                ts = datetime.fromtimestamp(int(ctime_str))
            except:
                ts = cst

            # Filter: keep news matching sector keywords OR general A-share market news
            A_SHARE_KW = ['A股','沪指','深指','创业板','科创板','涨停','跌停','板块',
                         '券商','基金','北向','主力','机构','IPO','上市','退市','分红',
                         '业绩','财报','半年报','年报','季报','预告','快报',
                         '央行','降息','降准','LPR','MLF','社融','M2','证监会','交易所',
                         '锂','钴','镍','钢','煤','油','气','电','矿',
                         '芯片','半导体','光模块','光伏','电池','汽车','机器人',
                         '卫健委','医保','集采','审批','获批','政策','法规','环保',
                         '国际','美国','欧洲','日本','韩国','印度','越南',
                         '华','腾','阿','百','字','美','京东','拼','网','数据',
                         '国常会','国务院','发改委','工信部','商务部','财政部','外交部']
            if not (any(kw in title for kw in SECTOR_KW) or any(kw in title for kw in A_SHARE_KW)):
                continue

            # Remove duplicates by title
            all_news.append({
                't': title.strip()[:100],
                'b': '',
                's': [],
                'u': url_link,
                'time': ts.strftime('%H:%M'),
                'src': 'sina_' + ch_name
            })

    return all_news[:30]

def fetch_em_announcements():
    """Fetch significant A-share announcements from EastMoney."""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    news = []

    # Only fetch announcements that could be market-moving
    for ann_type in ['A', 'SFA', 'SHA']:
        url = f'https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=20&page_index=1&ann_type={ann_type}&sr=-1&client_source=web'
        data = fetch_json(url)
        if not data or data.get('success') != 1:
            continue

        items = data.get('data', {}).get('list', [])
        for it in items:
            title = it.get('title', '') or ''
            date_str = (it.get('notice_date', '') or '')[:10]

            # Skip routine stuff (董事会/监事会/制度修订/独立董事/审计委员会)
            skip_words = ['董事会第', '监事会第', '独立董事', '审计委员会', '薪酬与考核', '制度修订',
                         '工作细则', '管理制度', '信息知情人', '防控控股股东', '重大信息内部',
                         '总经理工作细则', '对外投资管理制度', '募集资金使用管理', '离职管理',
                         '内幕信息', '专项管理制度', '登记管理', '网上申购']
            if any(w in title for w in skip_words):
                continue

            # Only keep significant announcements
            sig_words = ['业绩', '盈利', '亏损', '分红', '回购', '增持', '减持', '重组',
                        '停牌', '退市', '上市', '首发', 'IPO', '非公开', '配股', '可转债',
                        '质押', '冻结', '拍卖', '预亏', '预增', '扭亏', '合同', '中标',
                        '重大', '诉讼', '*ST', 'ST', '股权转让', '要约', '收购', '合并',
                        '涨价', '停产', '限产', '减产', '投产', '量产', '获批', '通过',
                        'H股', 'A股', '科创板', '创业板', '北交所', '纳斯达克']
            if not any(w in title for w in sig_words):
                continue

            # Filter by our 62 sector keywords
            if not any(kw in title for kw in SECTOR_KW):
                continue

            # Extract stock info
            codes_list = it.get('codes', [])
            stock_code = codes_list[0].get('stock_code', '') if codes_list else ''
            stock_name = codes_list[0].get('short_name', '') if codes_list else ''

            news.append({
                't': f'{stock_name}: {title[:80]}' if stock_name else title[:100],
                'b': '',
                's': [f'{stock_code} {stock_name}'] if stock_code else [],
                'u': f'https://data.eastmoney.com/notices/detail/{stock_code}.html' if stock_code else '',
                'time': date_str[-5:] if len(date_str) >= 5 else date_str,
                'src': 'em_ann_' + ann_type
            })

    return news[:15]

def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)

    print('Fetching Sina news...')
    sina_news = fetch_sina_news()
    print(f'  Sina: {len(sina_news)} sector-matching news')

    print('Fetching EM announcements...')
    em_news = fetch_em_announcements()
    print(f'  EM: {len(em_news)} sector-matching announcements')

    # Merge
    all_news = sina_news + em_news

    # Deduplicate by title prefix
    seen = set()
    deduped = []
    for n in all_news:
        key = n['t'][:40]
        if key not in seen:
            seen.add(key)
            deduped.append(n)

    deduped.sort(key=lambda n: n.get('time', ''), reverse=True)

    # Write to data.json
    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                pass

    data['_newsFeed'] = deduped[:40]
    data['_newsMeta'] = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'total': len(deduped),
        'sina': len(sina_news),
        'em': len(em_news),
        'sectors': sorted(set(kw for n in deduped for kw in SECTOR_KW if kw in (n.get('t','') or ''))),
    }

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'NewsFeed: {len(deduped)} items saved')
    if deduped:
        t = deduped[0].get('time','?')
        title = (deduped[0].get('t','') or '')[:80]
        print(f'  Latest: {t} {title}')


if __name__ == '__main__':
    main()
