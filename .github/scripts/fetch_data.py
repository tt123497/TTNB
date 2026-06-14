#!/usr/bin/env python3
"""GitHub Actions data fetcher - runs in cloud every 15 min during A-share hours"""
import json, os, re, time, shutil, glob as _glob
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

def fetch(url, encoding='gbk', retries=2, extra_headers=None):
    for i in range(retries):
        try:
            headers = {'User-Agent': UA, 'Accept': '*/*'}
            if extra_headers: headers.update(extra_headers)
            req = Request(url, headers=headers)
            enc = encoding if 'eastmoney' not in url and 'push2ex' not in url else 'utf-8'
            with urlopen(req, timeout=12) as r:
                return r.read().decode(enc, errors='replace')
        except Exception as e:
            if i == retries - 1: return None
            time.sleep(2)

def get_indices():
    """Use EastMoney API (works from GitHub Actions US IPs, unlike Sina)"""
    names = {'1.000001':'上证指数','0.399001':'深证成指','0.399006':'创业板指',
             '1.000688':'科创50','1.000300':'沪深300','1.000016':'上证50'}
    secids = ','.join(names.keys())
    text = fetch(f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f12,f14&secids={secids}&ut=bd1d9ddb04089700cf9c27f6f7426281', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        results = []
        for i in items:
            n = names.get(i.get('f12',''), i.get('f14',''))
            p = i.get('f2', 0)
            chg = i.get('f3', 0)
            results.append({'n': n, 'v': f'{p:.0f}' if p else '0', 'chg': f'{chg:+.2f}%', 'up': chg >= 0})
        return results
    except: return []

def get_sector_heat():
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f2,f3,f12,f14', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'n':i.get('f14',''),'s':f"{i.get('f3',0):+.1f}%",'c':'var(--red)' if i.get('f3',0)>0 else 'var(--green)','bk':i.get('f12','')} for i in items[:50]]
    except: return []

def get_stock_codes():
    html_path = os.path.join(DIR, 'index.html')
    codes = set()
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()):
                codes.add(m.group(1))
    except: pass
    return sorted(codes)

def get_sector_mapping():
    """Extract {stock_code: sector_name} from index.html D.groups st:[] blocks"""
    mapping = {}
    html_path = os.path.join(DIR, 'index.html')
    if not os.path.exists(html_path): return mapping
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
    st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)
    for i in range(min(len(id_names), len(st_blocks))):
        _, sec_name = id_names[i]
        for c in re.findall(r'\{c:"(\d{6})"', st_blocks[i]):
            mapping[c] = sec_name
    return mapping

def get_live_prices(all_codes):
    """Use EastMoney batch API (works from GitHub Actions US IPs)"""
    results = {}
    secids = []
    for c in all_codes:
        if c.startswith(('60','68')): secids.append(f'1.{c}')
        elif c.startswith(('00','30')): secids.append(f'0.{c}')
        else: secids.append(f'1.{c}')

    for i in range(0, len(secids), 100):
        batch = secids[i:i+100]
        url = f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={",".join(batch)}&ut=bd1d9ddb04089700cf9c27f6f7426281'
        text = fetch(url, encoding='utf-8')
        if not text: continue
        try:
            items = json.loads(text).get('data',{}).get('diff',[])
            for s in items:
                c = s.get('f12','')
                price = s.get('f2', 0)
                chg = s.get('f3', 0)
                sina_key = f'sh{c}' if c.startswith(('60','68')) else f'sz{c}'
                results[sina_key] = {'price': price, 'chg_pct': chg, 'name': s.get('f14','')}
        except: pass
        time.sleep(0.05)
    return results

def fetch_all_top_gainers():
    """Fallback: top 8 gainers from ALL A-shares. Returns list of 'code name'."""
    try:
        t = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f2,f3,f12,f14', encoding='utf-8')
        if t:
            return [s.get('f12','') + ' ' + s.get('f14','') for s in json.loads(t).get('data',{}).get('diff',[])]
    except:
        pass
    return []

def fetch_sector_stocks(our_names, heat_data):
    """For each sector, pull real-time top gainers from EastMoney board API.
    Filter: ≤3 科创/创业板 (300/301/688/689), rest 主板 (60x/00x/001-003).
    Sorted by gain% descending. Only includes stocks up >0% where possible.
    Returns dict: {sector_name: [{c, n, chg}, ...]}"""
    # Build reverse alias: our sector → list of EM board keywords to try
    our_to_kw = {}
    for kw, our in EM_ALIAS.items():
        if our and kw:
            our_to_kw.setdefault(our, []).append(kw)

    # Build board name → code from heat data (which already has board codes)
    name_to_bcode = {}
    for h in heat_data:
        bk = h.get('bk', '') or h.get('f12', '')
        if bk:
            name_to_bcode[h['n']] = bk

    # Also fetch full board list for broader matching
    all_boards = {}
    for mkt in ['m:90+t:3', 'm:90+t:2']:
        try:
            t = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs=' + mkt + '&fields=f2,f3,f12,f14', encoding='utf-8')
            if t:
                for h in json.loads(t).get('data', {}).get('diff', []):
                    n = h.get('f14', '')
                    if n and n not in all_boards:
                        all_boards[n] = h.get('f12', '')
        except:
            pass

    def find_bcode(sector_name):
        """Find best board code for a sector name."""
        # 1. Via alias keywords → heat data boards
        kws = our_to_kw.get(sector_name, [])
        for kw in kws:
            for bname, bc in name_to_bcode.items():
                if kw in bname or bname in kw:
                    return bc
        # 2. Via alias keywords → all boards
        for kw in kws:
            for bname, bc in all_boards.items():
                if kw in bname or bname in kw:
                    return bc
        # 3. Sector name substring in all boards
        for bname, bc in all_boards.items():
            if len(sector_name) >= 2 and sector_name[:2] in bname:
                return bc
        # 4. Sector name parts
        for part in sector_name.split('/'):
            for bname, bc in all_boards.items():
                if len(part) >= 2 and part[:2] in bname:
                    return bc
        return ''

    CODE_BOARD = {'60': 'sh', '68': 'sh', '00': 'sz', '30': 'sz', '00': 'sz', '00': 'sz'}

    result = {}
    for sec in our_names:
        bcode = find_bcode(sec)
        if not bcode:
            result[sec] = []
            continue

        # Fetch top 25 from this board, sorted by gain%
        stocks = []
        for retry in range(2):
            try:
                t = fetch(
                    'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=25&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:' + bcode +
                    '&fields=f2,f3,f12,f14', encoding='utf-8')
                if t:
                    for s in json.loads(t).get('data', {}).get('diff', []):
                        code = s.get('f12', '')
                        name = s.get('f14', '')
                        chg = s.get('f3', 0)
                        if code and name:
                            stocks.append({'c': code, 'n': name, 'chg': round(chg, 1)})
                    break
            except:
                pass
            time.sleep(0.3)

        # Sort by gain% descending
        stocks.sort(key=lambda x: x['chg'], reverse=True)

        # Filter: ≤3 科创/创业, rest 主板
        cyb_kcb = [s for s in stocks if s['c'].startswith(('300', '301', '688', '689'))]
        main_bd = [s for s in stocks if s['c'].startswith(('600', '601', '603', '605', '000', '001', '002', '003'))]

        filtered = cyb_kcb[:3] + main_bd
        # Re-sort by gain%
        filtered.sort(key=lambda x: x['chg'], reverse=True)

        # Only keep stocks with positive gain where possible, but at least 3
        up_stocks = [s for s in filtered if s['chg'] > 0]
        if len(up_stocks) >= 3:
            filtered = up_stocks
        # Cap at 8
        result[sec] = filtered[:8]

    return result


def get_fund_flow_em():
    """Returns fund flow: [{n, amt: '+87.9亿'}, ...]"""
    text = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f3,f12,f14,f62', encoding='utf-8')
    if not text: return []
    try:
        items = json.loads(text).get('data',{}).get('diff',[])
        return [{'n': i.get('f14',''), 'amt': f"{'+' if float(i.get('f62',0) or 0) > 0 else ''}{abs(float(i.get('f62',0) or 0)) / 100000000:.1f}亿"}
                for i in items]
    except: return []

# EastMoney sector → our EXACT sector name from D.groups (or '' = no match)
EM_ALIAS = {
    '航天航空':'商业航天','航天军工':'商业航天','通用航空':'低空经济eVTOL',
    '低空经济':'低空经济eVTOL','飞行汽车':'低空经济eVTOL',
    '机器人':'人形机器人','人形机器人':'人形机器人','具身智能':'人形机器人','汽车制造':'',
    '光通信':'CPO/硅光','光模块':'CPO/硅光','光纤光缆':'光纤光缆','光纤':'光纤光缆',
    '半导体':'AI芯片','芯片':'AI芯片','AI芯片':'AI芯片','GPU':'AI芯片','算力':'AI服务器/超节点',
    'PCB':'PCB/覆铜板','覆铜板':'PCB/覆铜板','印制电路板':'PCB/覆铜板',
    'MLCC':'MLCC电容','被动元件':'MLCC电容','电容':'MLCC电容','电子元件':'MLCC电容',
    '铜箔':'电子铜箔','超导':'超导/核聚变','核聚变':'超导/核聚变',
    '碳纤维':'碳纤维','固态电池':'固态电池','全固态电池':'固态电池',
    '存储芯片':'HBM/存储芯片','HBM':'HBM/存储芯片','NAND':'HBM/存储芯片','存储':'HBM/存储芯片',
    '液冷':'液冷散热','冷却':'液冷散热','散热':'液冷散热','液冷散热':'液冷散热',
    '钨':'钨稀土','稀土':'钨稀土','稀土永磁':'钨稀土','有色':'钨稀土','小金属':'钨稀土','稀缺资源':'钨稀土','钨稀土':'钨稀土',
    '玻璃基板':'玻璃基板TGV','TGV':'玻璃基板TGV','先进封装':'先进封装CoWoS','CoWoS':'先进封装CoWoS',
    '半导体硅片':'半导体硅片','硅片':'半导体硅片','光刻胶':'光刻胶','半导体设备':'半导体设备','刻蚀':'半导体设备',
    '服务器':'AI服务器/超节点','交换机':'交换机/网络','数据中心':'数据中心/AIDC','AIDC':'数据中心/AIDC',
    '电源':'电源/DrMOS','DrMOS':'电源/DrMOS','六氟化钨':'六氟化钨WF₆','WF6':'六氟化钨WF₆','电子特气':'六氟化钨WF₆',
    '培育钻石':'培育钻石/散热','金刚石':'培育钻石/散热','钻石':'培育钻石/散热',
    '6G':'6G/通信','通信':'6G/通信','卫星':'6G/通信','6G通信':'6G/通信',
    '连接器':'连接器/铜连接','铜连接':'连接器/铜连接',
    '电子树脂':'电子树脂/PPE','PPE':'电子树脂/PPE','树脂':'电子树脂/PPE',
    '空间计算':'空间计算/物理AI','物理AI':'空间计算/物理AI',
    '锂矿':'锂矿/盐湖提锂','盐湖提锂':'锂矿/盐湖提锂','碳酸锂':'锂矿/盐湖提锂',
    '锂电池':'锂电池/电解液','电解液':'锂电池/电解液','隔膜':'锂电池/电解液',
    '光伏':'光伏/太阳能','太阳能':'光伏/太阳能','逆变器':'光伏/太阳能',
    '风电':'风电','风能':'风电','海风':'风电',
    '储能':'储能','新能源车':'新能源汽车','汽车整车':'新能源汽车',
    '煤炭':'煤炭','煤化工':'煤炭',
    '黄金':'黄金/贵金属','贵金属':'黄金/贵金属',
    '铜':'铜铝有色','铝':'铜铝有色','有色金属':'铜铝有色',
    '化工':'化工','化学制品':'化工',
    '钢铁':'钢铁','普钢':'钢铁','特钢':'钢铁',
    '银行':'银行','券商':'券商','证券':'券商','保险':'保险',
    '房地产':'房地产开发','地产':'房地产开发',
    '白酒':'白酒','酿酒':'白酒',
    '食品':'食品饮料','乳业':'食品饮料','调味品':'食品饮料',
    '医药':'医药/CRO','生物医药':'医药/CRO','创新药':'医药/CRO','CXO':'医药/CRO',
    '医疗器械':'医疗器械','医疗设备':'医疗器械',
    '稀土永磁':'稀土永磁','永磁':'稀土永磁','钕铁硼':'稀土永磁',
    '钼':'钼/小金属','小金属':'钼/小金属','稀缺资源':'钼/小金属',
    '电子特气':'电子特气/工业气体','工业气体':'电子特气/工业气体','特种气体':'电子特气/工业气体',
    '半导体靶材':'半导体靶材','靶材':'半导体靶材','溅射':'半导体靶材',
    'AI智能体':'AI智能体/应用','AI应用':'AI智能体/应用','大模型':'AI智能体/应用','智能体':'AI智能体/应用','人工智能':'AI智能体/应用',
    '核电':'核电/核能','核能':'核电/核能','核电站':'核电/核能','SMR':'核电/核能',
    '量子计算':'量子计算/量子科技','量子科技':'量子计算/量子科技','量子':'量子计算/量子科技',
    '卫星互联网':'卫星互联网/北斗','北斗':'卫星互联网/北斗','低轨卫星':'卫星互联网/北斗','千帆':'卫星互联网/北斗',
    '电网设备':'电网设备/特高压','特高压':'电网设备/特高压','智能电网':'电网设备/特高压','配电网':'电网设备/特高压',
    '电力装备':'电网设备/特高压','输变电':'电网设备/特高压',
    '火电':'火电/电力运营','火力发电':'火电/电力运营','电力运营':'火电/电力运营','热电':'火电/电力运营',
    '算电':'算电协同','电力AI':'算电协同','AI电力':'算电协同',
    '算力租赁':'算力租赁/GPU云','GPU租赁':'算力租赁/GPU云','智算':'算力租赁/GPU云',
    'Token工厂':'Token工厂/模型推理','模型推理':'Token工厂/模型推理','推理云':'Token工厂/模型推理',
    # New sectors from AI sentinel
    'AI应用':'AI智能体/应用','人工智能':'AI智能体/应用','大模型':'AI智能体/应用','AI':'AI智能体/应用',
    '智能体':'AI智能体/应用','互联网':'AI智能体/应用',
    '鸿蒙':'空间计算/物理AI','华为概念':'空间计算/物理AI',
    '消费电子':'PCB/覆铜板','AI硬件':'PCB/覆铜板','AI眼镜':'PCB/覆铜板',
    '数字经济':'数据中心/AIDC','数据要素':'数据中心/AIDC',
    # Fallback: generic →  commercial aerospace (most active)
    '大会':'商业航天','峰会':'商业航天','论坛':'商业航天',
    '国企':'','化工':'','石油':'','煤炭':'','钢铁':'','金融':'','银行':'','保险':'','券商':'',
    '地产':'','消费':'','食品':'','饮料':'','酒':'','医药':'','医疗':'','新能源':'',
    '电力':'','光伏':'','风电':'','锂电':'','电池':'','草甘膦':'',
}

def compute_winners_losers(live, stock_sector, heat_em):
    """Group live prices by sector, produce top-5 stock detail per sector"""
    sec_changes = {}
    for key, v in live.items():
        code = key[2:]
        sec = stock_sector.get(code, '')
        if not sec: continue
        chg = v.get('chg_pct', 0)
        sec_changes.setdefault(sec, []).append({'c': code, 'n': v.get('name',''), 'chg': chg})

    sec_detail = {}
    for sec, stocks in sec_changes.items():
        ss = sorted(stocks, key=lambda x: x['chg'], reverse=True)
        sec_detail[sec] = ' / '.join([f"{s['c']} {s['n']} {s['chg']:+.1f}%" for s in ss[:5]])

    def match_our_sec(em_name):
        """Map EastMoney sector → our exact sec_detail key, or ''"""
        # 1. Exact alias match → check if target exists in sec_detail
        if em_name in EM_ALIAS:
            target = EM_ALIAS[em_name]
            if target and target in sec_detail: return target
            if not target: return ''  # explicitly ignored
        # 2. Partial alias match
        for kw, target in EM_ALIAS.items():
            if target and kw and (kw in em_name or em_name in kw):
                if target in sec_detail: return target
        # 3. If alias didn't help, try matching alias value via substring
        for kw, target in EM_ALIAS.items():
            if target and target in sec_detail and kw and kw in em_name:
                return target
        # 4. Direct fuzzy match against sec_detail keys
        for o in sec_detail:
            # Two-char overlap or cross-contained
            if (len(em_name)>=2 and len(o)>=2 and (em_name[:2] in o or o[:2] in em_name)) or em_name in o or o in em_name:
                return o
        # 5. Loose: single keyword overlap
        for kw in em_name:
            if len(kw) < 2: continue
            for o in sec_detail:
                if kw in o: return o
        return ''

    sorted_em = sorted(heat_em, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)
    winners, losers = [], []
    # Winners: prefer EM sectors that match our sectors (with stock detail)
    matched_em = []; unmatched_em = []
    for s in sorted_em[:30]:
        m = match_our_sec(s['n'])
        stks = sec_detail.get(m,'') if m else ''
        (matched_em if stks else unmatched_em).append({'s': s['n'], 'stks': stks or s['s']})
    for w in matched_em:
        if len(winners) >= 6: break
        winners.append(w)
    for w in unmatched_em:
        if len(winners) >= 6: break
        winners.append(w)
    # Losers from OUR sectors (average change), so they're always relevant
    our_losers = []
    for sec, detail in sec_detail.items():
        # Parse average change from detail string
        chgs = []
        for part in detail.split(' / '):
            m = re.search(r'([+-]?\d+\.?\d*)%', part)
            if m: chgs.append(float(m.group(1)))
        if chgs:
            avg = sum(chgs) / len(chgs)
            our_losers.append((avg, sec, detail))
    our_losers.sort(key=lambda x: x[0])  # worst first
    for avg, sec, detail in our_losers[:6]:
        losers.append({'s': sec, 'stks': detail})
    # Fill remaining with EM heat if needed
    for s in sorted_em[-10:][::-1]:
        if len(losers) >= 6: break
        stks = sec_detail.get(match_our_sec(s['n']),'') or ''
        if not stks: stks = s['s']
        losers.append({'s': s['n'], 'stks': stks})
    return winners, losers

def get_zt_ladder(cst):
    """Fetch consecutive limit-up pool from EastMoney. Returns {tiers, maxBoard, totalCount} or None"""
    # Try today first, then fall back to last trading day
    for attempt in range(3):
        try_date = cst - timedelta(days=attempt)
        if try_date.weekday() >= 5: continue  # skip weekends
        date_str = try_date.strftime('%Y%m%d')
        url = (f'http://push2ex.eastmoney.com/getTopicZTPool'
               f'?ut=7eea3edcaed734bea9cbfc24409ed989'
               f'&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date={date_str}')
        text = fetch(url, encoding='utf-8', extra_headers={'Referer': 'http://quote.eastmoney.com/'})
        if not text: continue
        try:
            # Handle JSONP wrapper: callback({...})
            if text.startswith('callback('):
                text = text[9:-1]
            elif text.startswith('jQuery'):
                text = text[text.index('(')+1:-1]
            data_obj = json.loads(text)
            items = data_obj.get('data', {}).get('pool', [])
        except Exception:
            continue
        if not items: continue

        tiers_dict = {}
        for item in items:
            lbc = item.get('lbc', 1) or 1
            stock = {
                'c': item.get('c', ''),
                'n': item.get('n', ''),
                'industry': item.get('hybk', ''),
                'p': (item.get('p', 0) or 0) / 1000 if item.get('p', 0) else 0,
                'zdf': item.get('zdp', 0)
            }
            tiers_dict.setdefault(lbc, []).append(stock)

        tiers = [{'boardCount': k, 'stocks': sorted(v, key=lambda s: (s.get('industry','') or 'zzz', s.get('n','')))} for k, v in sorted(tiers_dict.items(), reverse=True)]
        return {
            'updated': cst.strftime('%Y-%m-%d %H:%M'),
            'tiers': tiers,
            'maxBoard': max(tiers_dict.keys()) if tiers_dict else 0,
            'totalCount': len(items)
        }
    return None

def auto_sectors(heat, indices, preserved_sectors):
    """Auto-generate sector signals from EastMoney heat data when Claude data is stale.
    Returns list of {name, sig, msg} for our 35 sectors."""
    our_names = ['AI芯片','CPO/硅光','光模块','光纤光缆','连接器/铜连接',
        'PCB/覆铜板','MLCC电容','电子树脂/PPE','电子铜箔','HBM/存储芯片',
        'AI服务器/超节点','液冷散热','交换机/网络','电源/DrMOS','数据中心/AIDC',
        '半导体设备','光刻胶','先进封装CoWoS','半导体硅片',
        '六氟化钨WF₆','玻璃基板TGV','培育钻石/散热','超导/核聚变','碳纤维',
        '算电协同','电网设备/特高压','火电/电力运营','算力租赁/GPU云','Token工厂/模型推理',
        '稀土永磁','钼/小金属','电子特气/工业气体','半导体靶材',
        'AI智能体/应用','核电/核能','量子计算/量子科技','卫星互联网/北斗',
        '人形机器人','商业航天','6G/通信','固态电池','低空经济eVTOL','空间计算/物理AI','钨稀土',
        '锂矿/盐湖提锂','锂电池/电解液','光伏/太阳能','风电','储能','新能源汽车',
        '煤炭','黄金/贵金属','铜铝有色','化工','钢铁',
        '银行','券商','保险','房地产开发',
        '白酒','食品饮料','医药/CRO','医疗器械']

    # Sort EM sectors by performance
    sorted_heat = sorted(heat, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)

    # Build keyword → our_name mapping
    # Map EM sector names → our sector names

    results = []
    for our in our_names:
        # Find best matching EM heat entry
        matched = None
        for kw, target in EM_ALIAS.items():
            if target == our:
                for h in heat:
                    if kw in h['n'] or h['n'] in kw:
                        matched = h; break
            if matched: break
        if not matched:
            for h in heat:
                if our[:2] in h['n'] or h['n'][:2] in our:
                    matched = h; break

        if matched:
            pct = float(matched['s'].replace('%','').replace('+','').replace('-','-'))
            sig = 'major' if pct >= 3 else 'good' if pct >= 0 else 'neutral' if pct >= -1 else 'negative'
            msg = f"{matched['n']} {matched['s']} | 自动刷新"
        else:
            sig = 'neutral'
            pct = 0
            msg = '暂无行情数据'

        results.append({'name': our, 'sig': sig, 'msg': msg})
    return results

def auto_cycle(indices):
    """Auto-generate market cycle judgment from index data."""
    if not indices or len(indices) < 4:
        return {
            'phase': '数据不足', 'phaseIcon': '📊',
            'signals': ['等待行情数据更新'],
            'riskLevel': 'medium', 'riskLabel': '数据不足',
            'suggestion': '等待开盘后更新'
        }

    # Calculate average change of major indices (上证/深证/创业板/沪深300)
    major = [i for i in indices if i['n'] in ['上证指数','深证成指','创业板指','沪深300']]
    if not major: major = indices[:4]

    avg_chg = sum(float(i['chg'].replace('%','').replace('+','')) for i in major) / len(major)
    up_count = sum(1 for i in major if i['up'])

    if avg_chg > 1.5 and up_count >= 3:
        phase = '强势上攻'
        icon = '🔥'
        risk = 'medium'
        label = '中等风险'
        sug = '趋势良好，可积极布局主线赛道'
    elif avg_chg > 0.3 and up_count >= 2:
        phase = '震荡偏强'
        icon = '📈'
        risk = 'low'
        label = '较低风险'
        sug = '温和上涨，精选个股为主'
    elif avg_chg >= -0.3:
        phase = '窄幅震荡'
        icon = '⚖️'
        risk = 'medium'
        label = '中等风险'
        sug = '方向不明确，控制仓位等待信号'
    elif avg_chg >= -1.5:
        phase = '震荡回调'
        icon = '📉'
        risk = 'medium'
        label = '中等风险'
        sug = '高位止盈，关注防御板块'
    else:
        phase = '恐慌下跌'
        icon = '🔴'
        risk = 'high'
        label = '高风险'
        sug = '现金为王，等待企稳信号'

    signals = [
        f"指数均涨{avg_chg:+.1f}%，{up_count}/{len(major)}上涨",
        f"上证{indices[0].get('v','?')} {indices[0].get('chg','?')}",
        f"深证{indices[1].get('v','?')} {indices[1].get('chg','?')}" if len(indices) > 1 else '',
    ]

    return {
        'phase': phase, 'phaseIcon': icon,
        'signals': [s for s in signals if s],
        'riskLevel': risk, 'riskLabel': label,
        'suggestion': sug
    }

def main():
    now = datetime.now(timezone.utc)
    cst = now + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15

    codes = get_stock_codes()
    # Merge extra codes from dynamicSectors, layout, and ztLadder to ensure price coverage
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as _f:
            try:
                _old = json.load(_f)
                for ds in _old.get('dynamicSectors',[]):
                    for s in ds.get('st',[]): codes.append(s.get('c',''))
                for lev in _old.get('layout',[]):
                    for s in lev.get('stocks',[]):
                        c = (s or '').split()[0]
                        if c and len(c)==6: codes.append(c)
                if _old.get('recap',{}).get('ztLadder',{}).get('tiers'):
                    for t in _old['recap']['ztLadder']['tiers']:
                        for s in t.get('stocks',[]): codes.append(s.get('c',''))
            except: pass
    codes = sorted(set(c for c in codes if c and len(c)==6))
    stock_sector = get_sector_mapping()
    indices = get_indices()
    sectors = get_sector_heat()
    live = get_live_prices(codes)
    fund = get_fund_flow_em()
    zt_ladder = get_zt_ladder(cst)
    # Real ZT/DT count from clist API (all A-shares, not just 封板池)
    zt_count = len(zt_ladder.get('tiers',[]))  # fallback: tier count
    dt_count = 0
    try:
        t2 = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f12,f14', encoding='utf-8')
        if t2:
            items = json.loads(t2).get('data',{}).get('diff',[])
            zt_list = [i for i in items if i.get('f3',0) >= 9.9]
            dt_list = [i for i in items if i.get('f3',0) <= -9.9]
            zt_count = len(zt_list)
            dt_count = len(dt_list)
    except: pass

    # Compute winners/losers with real stock detail
    winners, losers = compute_winners_losers(live, stock_sector, sectors)

    next_update = '今日 17:00 收盘复盘' if is_trading else '下个交易日 9:15 开盘扫描'

    # Preserve manually-curated fields from existing data.json (12h freshness window)
    preserve = {}
    preserve_keys = ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout', 'bHistory', 'concepts', 'dynamicSectors']
    old_cycle = None
    old_briefing_date = ''
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                old = json.load(f)
                for k in preserve_keys:
                    if k in old and old[k]:
                        preserve[k] = old[k]
                old_recap = old.get('recap', {})
                if 'cycle' in old_recap and old_recap['cycle']:
                    old_cycle = old_recap['cycle']
                old_briefing = old.get('briefing', {})
                old_briefing_date = old_briefing.get('updated', '') if old_briefing else ''
            except: pass

    # Auto-fresh: if Claude data is >12h old, regenerate from market data
    cst_str = cst.strftime('%Y-%m-%d')
    sectors_fresh = preserve.get('sectors') and old_briefing_date.startswith(cst_str)
    if not sectors_fresh and sectors:
        auto_sec = auto_sectors(sectors, indices, preserve.get('sectors'))
        preserve['sectors'] = auto_sec

    # Auto-generate briefing if none or stale AND existing is auto-generated (<=3 items)
    briefing_fresh = preserve.get('briefing') and old_briefing_date.startswith(cst_str)
    existing_top3_len = len(preserve.get('top3', []))
    existing_picks_len = len(preserve.get('picks', []))
    # Never overwrite quality Claude-written data (10 items) with auto (3 items)
    is_auto_briefing = existing_top3_len <= 3 and existing_picks_len <= 5
    if not briefing_fresh and sectors and is_auto_briefing:
        ai = indices[:4] if indices else []
        idx_text = ' | '.join([f"{i['n']} {i['chg']}" for i in ai])
        ai_top3 = [{
            'r': 1, 't': f"📊 大盘实时: {idx_text}",
            'b': f"更新时间 {cst.strftime('%H:%M')}，数据每15分钟自动刷新。" + ('市场普涨' if sum(1 for i in ai if i.get('up')) >= 3 else '市场分化' if sum(1 for i in ai if i.get('up')) >= 2 else '市场调整'),
            's': []
        }]
        if sectors:
            top5 = sorted(sectors, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)[:5]
            ai_top3.append({
                'r': 2, 't': f"🔥 今日最热: {', '.join([h['n'] for h in top5])}",
                'b': f"领涨: {top5[0]['n']} {top5[0]['s']}，资金关注度高",
                's': [f"{h['n']} {h['s']}" for h in top5]
            })
        if zt_ladder and zt_ladder.get('tiers'):
            max_b = zt_ladder['tiers'][0]
            ai_top3.append({
                'r': 3, 't': f"🪜 连板: 最高{max_b['boardCount']}连板，共{zt_ladder['totalCount']}只涨停",
                'b': f"涨停{zt_ladder['totalCount']}只，最高{max_b['boardCount']}连板: {', '.join([s['n'] for s in max_b['stocks'][:5]])}",
                's': [f"{s['c']} {s['n']}" for s in max_b['stocks'][:6]]
            })
        preserve['briefing'] = {
            'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
            'top3': ai_top3,
            'picks': preserve.get('picks', [])
        }
        preserve['top3'] = ai_top3

    # Auto-generate cycle if no manual one
    cycle = old_cycle
    if not cycle and indices:
        cycle = auto_cycle(indices)
    if not cycle:
        cycle = {'phase': '等待数据', 'phaseIcon': '📊', 'signals': ['行情数据加载中'], 'riskLevel': 'medium', 'riskLabel': '等待', 'suggestion': '等待开盘'}

    # Events now handled by fetch_events.py (NBS macro calendar + AI sentinel + hand-curated)

    # Auto-repair layout stocks: fetch real market top stocks per sector
    existing_layout = preserve.get('layout', []) or []
    if existing_layout:
        if sectors:
            # Build EM sector name → board code mapping from heat data
            name_to_board = {}
            for h in sectors:
                name_to_board[h['n']] = h.get('bk', h.get('f12', ''))
            # Reverse alias: our sector name -> EM board name
            our_to_em = {}
            for kw, our in EM_ALIAS.items():
                if our and our not in our_to_em:
                    our_to_em[our] = kw  # use first match
            for lev in existing_layout:
                sec_name = lev.get('s', '')
                # 1. Direct match in heat names
                bcode = name_to_board.get(sec_name, '')
                # 2. Via alias table
                if not bcode:
                    em_hint = our_to_em.get(sec_name, '')
                    if em_hint:
                        for n, bc in name_to_board.items():
                            if em_hint in n or n in em_hint:
                                bcode = bc; break
                # 3. Fuzzy match heat names
                if not bcode:
                    for n, bc in name_to_board.items():
                        if sec_name[:2] in n or n[:2] in sec_name or sec_name in n or n in sec_name:
                            bcode = bc; break
                if not bcode:
                    if not lev.get('stocks') or len(lev.get('stocks',[])) < 3:
                        lev['stocks'] = fetch_all_top_gainers()
                    continue
                # Fetch top 8 stocks from this sector board (real market)
                bstocks = []
                for _ in range(2):
                    try:
                        t = fetch('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:' + bcode + '&fields=f2,f3,f12,f14', encoding='utf-8')
                        if t:
                            for s in json.loads(t).get('data',{}).get('diff',[]):
                                bstocks.append(s.get('f12','') + ' ' + s.get('f14',''))
                            break
                    except: pass
                if bstocks:
                    lev['stocks'] = bstocks[:8]
                if not lev.get('stocks') or len(lev.get('stocks',[])) < 3:
                    lev['stocks'] = fetch_all_top_gainers()
        else:
            # No heat data — use all-market fallback for every layout card
            fallback = fetch_all_top_gainers()
            if fallback:
                for lev in existing_layout:
                    if not lev.get('stocks') or len(lev.get('stocks',[])) < 3:
                        lev['stocks'] = fallback
    preserve['layout'] = existing_layout

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': next_update,
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices[:6] if indices else [],
            'heat': sectors[:25] if sectors else [],
            'flow': fund,
            'winners': winners,
            'losers': losers,
            'ztLadder': zt_ladder,
            'ztCount': zt_count,
            'dtCount': dt_count,
            'note': f"{cst.strftime('%m/%d %H:%M')} GitHub Actions云更新 | {len(codes)}只 | {len(sectors)}板块"
        },
        'livePrices': live,
        'runtime': {
            'cloud': True,
            'autoUpdate': True,
            'interval': '15min',
            'stockCount': len(codes),
            'liveCount': len(live),
            'updateCount': int(time.time() / 900),
            'trading': is_trading,
        }
    }
    # Build sector-level average change from live prices + stock_sector mapping
    sec_avg = {}
    for key, v in live.items():
        code = key[2:]
        sec = stock_sector.get(code, '')
        if not sec: continue
        chg = v.get('chg_pct', 0)
        sec_avg.setdefault(sec, []).append(chg)
    for sec, chgs in sec_avg.items():
        sec_avg[sec] = sum(chgs) / len(chgs) if chgs else 0

    # Generate dynamic tags for ALL 35 our sectors
    ai_msgs = {s.get('name',''): s.get('msg','')[:30] for s in preserve.get('sectors',[]) if s.get('name')}
    sector_tags = {}
    our_names = ['AI芯片','CPO/硅光','光模块','光纤光缆','连接器/铜连接',
        'PCB/覆铜板','MLCC电容','电子树脂/PPE','电子铜箔','HBM/存储芯片',
        'AI服务器/超节点','液冷散热','交换机/网络','电源/DrMOS','数据中心/AIDC',
        '半导体设备','光刻胶','先进封装CoWoS','半导体硅片',
        '六氟化钨WF₆','玻璃基板TGV','培育钻石/散热','超导/核聚变','碳纤维',
        '算电协同','电网设备/特高压','火电/电力运营','算力租赁/GPU云','Token工厂/模型推理',
        '稀土永磁','钼/小金属','电子特气/工业气体','半导体靶材',
        'AI智能体/应用','核电/核能','量子计算/量子科技','卫星互联网/北斗',
        '人形机器人','商业航天','6G/通信','固态电池','低空经济eVTOL','空间计算/物理AI','钨稀土',
        '锂矿/盐湖提锂','锂电池/电解液','光伏/太阳能','风电','储能','新能源汽车',
        '煤炭','黄金/贵金属','铜铝有色','化工','钢铁',
        '银行','券商','保险','房地产开发',
        '白酒','食品饮料','医药/CRO','医疗器械']
    for our in our_names:
        avg = sec_avg.get(our, 0)
        pct_s = '%.1f%%' % abs(avg)
        if avg >= 5: emoji = '🔥'; prefix = '板均涨' + pct_s
        elif avg >= 3: emoji = '🔥'; prefix = '板均涨' + pct_s
        elif avg >= 1: emoji = '🟢'; prefix = '偏强 +' + pct_s
        elif avg >= -1: emoji = '🟡'; prefix = '平盘'
        elif avg >= -3: emoji = '🔴'; prefix = '偏弱 -' + pct_s
        else: emoji = '🔴'; prefix = '回调 -' + pct_s
        ai_msg = ai_msgs.get(our, '')
        second = ai_msg[:22] if ai_msg and len(ai_msg) > 3 else our
        sector_tags[our] = emoji + ' ' + prefix + ' | ' + second
    # ── Live sector stocks: real-time top gainers per sector ──
    sector_stocks = fetch_sector_stocks(our_names, sectors)
    # Only overwrite if we actually got live data (prevents trading-hour-only blanks from wiping hardcoded)
    populated = sum(1 for v in sector_stocks.values() if v)
    if populated >= 10:  # At least 10 sectors must have data
        out['sectorStocks'] = sector_stocks
        stock_count = sum(1 for v in sector_stocks.values() for _ in v)
        print(f'  sectorStocks: {populated} sectors with live stocks, {stock_count} total')
    else:
        # Keep previous sectorStocks if they exist
        if preserve.get('sectorStocks') and sum(1 for v in preserve['sectorStocks'].values() if v) >= 10:
            out['sectorStocks'] = preserve['sectorStocks']
            print(f'  sectorStocks: kept existing ({sum(1 for v in preserve[\"sectorStocks\"].values() if v)} sectors)')
        else:
            print(f'  sectorStocks: skipped ({populated} sectors too few, likely non-trading)')

    # Merge preserved fields
    out.update(preserve)
    out['sectorTags'] = sector_tags  # always fresh, not from cache
    out['recap']['cycle'] = cycle

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Archive snapshot at market close (~15:00-15:30 CST)
    if is_trading and cst.hour == 15 and cst.minute < 45:
        archive_dir = os.path.join(DIR, 'archive')
        os.makedirs(archive_dir, exist_ok=True)
        date_key = cst.strftime('%Y-%m-%d')
        archive_path = os.path.join(archive_dir, f'{date_key}.json')
        shutil.copy2(DATA_PATH, archive_path)
        # Update index.json
        existing_archives = sorted(
            [os.path.basename(f).replace('.json','') for f in _glob.glob(os.path.join(archive_dir, '*.json'))
             if not os.path.basename(f) == 'index.json'],
            reverse=True
        )
        with open(os.path.join(archive_dir, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump(existing_archives, f, ensure_ascii=False)
        print(f"📦 Archived: {date_key} ({len(existing_archives)} snapshots)")

    print(f"OK {out['updated']} | {len(indices)} idx | {len(sectors)} sec | {len(live)} stks | flow={len(fund)} | zt={zt_ladder and zt_ladder.get('totalCount',0) or 0} | trading={is_trading}")

if __name__ == '__main__':
    main()
