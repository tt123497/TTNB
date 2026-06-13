#!/usr/bin/env python3
"""Fetch live market data (all EastMoney HTTP, no Sina dependency) + git push. Run every 5 min."""
import json, os, re, time, subprocess
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(DIR, 'data.json')
GIT = r'D:\Tools\Git\bin\git.exe'

def em_json(url, retries=2):
    for i in range(retries):
        try:
            r = urlopen(Request(url, headers={'User-Agent': UA, 'Accept': '*/*'}), timeout=12)
            return json.loads(r.read().decode('utf-8')).get('data') or {}
        except:
            if i == retries - 1: return {}
            time.sleep(2)

# ═══════════ Indices (EastMoney) ═══════════
INDEX_MAP = {'1.000001': '上证指数', '0.399001': '深证成指', '0.399006': '创业板指',
             '1.000688': '科创50', '1.000300': '沪深300', '1.000016': '上证50'}

def get_indices():
    items = em_json(f"http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={','.join(INDEX_MAP)}").get('diff', [])
    return [{'n': INDEX_MAP.get(i.get('f12',''), i.get('f14','')), 'v': f"{i.get('f2',0):.0f}",
             'chg': f"{i.get('f3',0):+.2f}%", 'up': i.get('f3',0)>=0} for i in items]

# ═══════════ Stock codes ═══════════
def get_stock_codes():
    codes = set()
    idx_path = os.path.join(DIR, 'index.html')
    if os.path.exists(idx_path):
        with open(idx_path, 'r', encoding='utf-8') as f:
            for m in re.finditer(r'\{c:"(\d{6})"', f.read()): codes.add(m.group(1))
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                for c in json.load(f).get('extraCodes', []): codes.add(str(c))
            except: pass
    return sorted(codes)

# ═══════════ Live prices (EastMoney batch) ═══════════
def get_live_prices(codes):
    results = {}
    secids = []
    for c in codes:
        if c[0] in '68': secids.append(f'1.{c}')
        elif c[0] in '89': secids.append(f'133.{c}')  # BSE stocks use 133. prefix in EastMoney
        else: secids.append(f'0.{c}')
    for i in range(0, len(secids), 100):
        batch = ','.join(secids[i:i+100])
        for s in em_json(f"http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids={batch}").get('diff', []):
            c = s.get('f12', '')
            key = f"sh{c}" if c[0] in '68' else f"sz{c}"
            results[key] = {'price': s.get('f2',0) or 0, 'chg_pct': s.get('f3',0) or 0, 'name': s.get('f14','') or ''}
        time.sleep(0.1)
    # Fill in any missing codes with zero (delisted BSE stocks etc.)
    for c in codes:
        for pfx in ['sh','sz']:
            if pfx + c in results:
                break
        else:
            results['sh' + c] = {'price': 0, 'chg_pct': 0, 'name': ''}
    return results

# ═══════════ Sector heat ═══════════
def get_sector_heat_em():
    return [{'n': i.get('f14',''), 's': f"{i.get('f3',0):+.1f}%",
             'c': 'var(--red)' if i.get('f3',0)>0 else 'var(--green)',
             'bk': i.get('f12','')}
            for i in em_json("http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f2,f3,f12,f14").get('diff',[])]

# ═══════════ Fund flow ═══════════
def get_fund_flow_em():
    """Returns fund flow: [{n, amt: '+87.9亿'}, ...]"""
    items = em_json("http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f3,f12,f14,f62").get('diff', [])
    return [{'n': i.get('f14', ''), 'amt': f"{'+' if float(i.get('f62', 0) or 0) > 0 else ''}{abs(float(i.get('f62', 0) or 0)) / 100000000:.1f}亿"}
            for i in items]

def get_zt_ladder():
    """Fetch consecutive limit-up pool from EastMoney"""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    for attempt in range(3):
        try_date = cst - timedelta(days=attempt)
        if try_date.weekday() >= 5: continue
        date_str = try_date.strftime('%Y%m%d')
        url = (f'http://push2ex.eastmoney.com/getTopicZTPool'
               f'?ut=7eea3edcaed734bea9cbfc24409ed989'
               f'&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date={date_str}')
        try:
            r = urlopen(Request(url, headers={'User-Agent': UA, 'Accept': '*/*', 'Referer': 'http://quote.eastmoney.com/'}), timeout=15)
            text = r.read().decode('utf-8')
            if text.startswith('callback('): text = text[9:-1]
            elif 'jQuery' in text[:20]: text = text[text.index('(')+1:-1]
            data = json.loads(text)
            items = data.get('data', {}).get('pool', [])
        except: continue
        if not items: continue
        tiers_dict = {}
        for item in items:
            lbc = item.get('lbc', 1) or 1
            stock = {'c': item.get('c',''), 'n': item.get('n',''), 'industry': item.get('hybk',''),
                     'p': (item.get('p',0) or 0) / 1000, 'zdf': item.get('zdp', 0)}
            tiers_dict.setdefault(lbc, []).append(stock)
        tiers = [{'boardCount': k, 'stocks': sorted(v, key=lambda s: (s.get('industry','') or 'zzz', s.get('n','')))} for k, v in sorted(tiers_dict.items(), reverse=True)]
        return {'updated': cst.strftime('%Y-%m-%d %H:%M'), 'tiers': tiers,
                'maxBoard': max(tiers_dict.keys()) if tiers_dict else 0, 'totalCount': len(items)}
    return None

# ═══════════ Sector mapping (from index.html D.groups) ═══════════
def get_sector_mapping():
    mapping = {}
    idx_path = os.path.join(DIR, 'index.html')
    if not os.path.exists(idx_path): return mapping
    with open(idx_path, 'r', encoding='utf-8') as f:
        html = f.read()
    id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
    st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)
    for i in range(min(len(id_names), len(st_blocks))):
        _, sec_name = id_names[i]
        for c in re.findall(r'\{c:"(\d{6})"', st_blocks[i]): mapping[c] = sec_name
    return mapping

# EastMoney sector → our EXACT sector name (or '' = no match)
EM_ALIAS = {
    '航天航空':'商业航天','航天军工':'商业航天','通用航空':'低空经济eVTOL',
    '低空经济':'低空经济eVTOL','飞行汽车':'低空经济eVTOL',
    '机器人':'人形机器人','人形机器人':'人形机器人','具身智能':'人形机器人',
    '光通信':'CPO/硅光','光模块':'CPO/硅光','光纤光缆':'光纤光缆','光纤':'光纤光缆',
    '半导体':'AI芯片','芯片':'AI芯片','AI芯片':'AI芯片','算力':'AI服务器/超节点',
    'PCB':'PCB/覆铜板','覆铜板':'PCB/覆铜板',
    'MLCC':'MLCC电容','被动元件':'MLCC电容','电容':'MLCC电容',
    '铜箔':'电子铜箔','超导':'超导/核聚变','核聚变':'超导/核聚变',
    '碳纤维':'碳纤维','固态电池':'固态电池',
    '存储芯片':'HBM/存储芯片','HBM':'HBM/存储芯片','存储':'HBM/存储芯片',
    '液冷':'液冷散热','散热':'液冷散热','液冷散热':'液冷散热',
    '钨':'钨稀土','稀土':'钨稀土','稀土永磁':'钨稀土','有色':'钨稀土','小金属':'钨稀土','稀缺资源':'钨稀土',
    '玻璃基板':'玻璃基板TGV','TGV':'玻璃基板TGV','先进封装':'先进封装CoWoS','CoWoS':'先进封装CoWoS',
    '半导体硅片':'半导体硅片','硅片':'半导体硅片','光刻胶':'光刻胶','半导体设备':'半导体设备',
    '服务器':'AI服务器/超节点','交换机':'交换机/网络','数据中心':'数据中心/AIDC',
    '电源':'电源/DrMOS','DrMOS':'电源/DrMOS','六氟化钨':'六氟化钨WF₆','电子特气':'六氟化钨WF₆',
    '培育钻石':'培育钻石/散热','金刚石':'培育钻石/散热',
    '6G':'6G/通信','通信':'6G/通信','卫星':'6G/通信',
    '连接器':'连接器/铜连接','铜连接':'连接器/铜连接',
    '电子树脂':'电子树脂/PPE','PPE':'电子树脂/PPE','树脂':'电子树脂/PPE',
    '空间计算':'空间计算/物理AI','物理AI':'空间计算/物理AI',
    '国企':'','化工':'','石油':'','煤炭':'','金融':'','银行':'','保险':'','券商':'',
    '消费':'','食品':'','酒':'','医药':'','医疗':'','新能源':'','电力':'','光伏':'',
}

# ═══════════ Winners/Losers with stock codes ═══════════
def compute_winners_losers(live, stock_sector, heat_em):
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

    def match_our(em_name):
        if em_name in EM_ALIAS:
            t = EM_ALIAS[em_name]
            if not t: return ''
            if t in sec_detail: return t
        for kw, t in EM_ALIAS.items():
            if t and t in sec_detail and kw and (kw in em_name or em_name in kw):
                return t
        for o in sec_detail:
            if (len(em_name)>=2 and len(o)>=2 and (em_name[:2] in o or o[:2] in em_name)) or em_name in o or o in em_name:
                return o
        return ''

    sorted_em = sorted(heat_em, key=lambda x: float(x['s'].replace('%','').replace('+','').replace('-','-')), reverse=True)
    winners, losers = [], []
    matched_em = []; unmatched_em = []
    for s in sorted_em[:30]:
        m = match_our(s['n'])
        stks = sec_detail.get(m,'') if m else ''
        (matched_em if stks else unmatched_em).append({'s': s['n'], 'stks': stks or s['s']})
    for w in matched_em:
        if len(winners) >= 6: break
        winners.append(w)
    for w in unmatched_em:
        if len(winners) >= 6: break
        winners.append(w)
    # Losers from OUR sectors (by average change), so always relevant
    our_losers = []
    import re
    for sec, detail in sec_detail.items():
        chgs = []
        for part in detail.split(' / '):
            m = re.search(r'([+-]?\d+\.?\d*)%', part)
            if m: chgs.append(float(m.group(1)))
        if chgs: our_losers.append((sum(chgs)/len(chgs), sec, detail))
    our_losers.sort(key=lambda x: x[0])
    for avg, sec, detail in our_losers[:6]:
        losers.append({'s': sec, 'stks': detail})
    for s in sorted_em[-10:][::-1]:
        if len(losers) >= 6: break
        m = match_our(s['n'])
        losers.append({'s': s['n'], 'stks': sec_detail.get(m,'') if m else s['s']})
    return winners, losers

# ═══════════════ MAIN ═══════════════
def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    is_trading = cst.weekday() < 5 and 9 <= cst.hour < 15
    tick = time.time()

    codes = get_stock_codes()
    # Merge extra codes from dynamicSectors, layout, and ztLadder for price coverage
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
    indices = get_indices()
    live = get_live_prices(codes)
    heat = get_sector_heat_em()
    fund = get_fund_flow_em()
    stock_sector = get_sector_mapping()
    winners, losers = compute_winners_losers(live, stock_sector, heat)
    zt_ladder = get_zt_ladder()
    dt_count = 0
    try:
        cst2 = datetime.now(timezone.utc) + timedelta(hours=8)
        for attempt in range(3):
            td = cst2 - timedelta(days=attempt)
            if td.weekday() >= 5: continue
            url2 = f'http://push2ex.eastmoney.com/getTopicDTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date={td.strftime("%Y%m%d")}'
            try:
                r2 = urlopen(Request(url2, headers={'User-Agent': UA, 'Accept': '*/*', 'Referer': 'http://quote.eastmoney.com/'}), timeout=10)
                txt2 = r2.read().decode('utf-8')
                if txt2.startswith('callback('): txt2 = txt2[9:-1]
                dt_count = len(json.loads(txt2).get('data',{}).get('pool',[]))
            except: pass
            break
    except: pass

    existing = {}
    old_cycle = None
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try: existing = json.load(f)
            except: pass
        old_cycle = existing.get('recap', {}).get('cycle')

    out = {
        'updated': cst.strftime('%Y-%m-%d %H:%M CST'),
        'nextSentinel': existing.get('nextSentinel', '今日 09:15 早盘哨兵'),
        'updateCount': int(time.time() / 900),
        'recap': {
            'index': indices,
            'heat': heat[:25],
            'flow': fund,
            'winners': winners,
            'losers': losers,
            'ztLadder': zt_ladder,
            'dtCount': dt_count,
            'note': f"{cst.strftime('%m/%d %H:%M')} 东财全源 | {len(live)}只 | {len(heat)}板块"
        },
        'livePrices': live,
        'runtime': {
            'cloud': False, 'autoUpdate': True, 'interval': '5min',
            'stockCount': len(codes), 'liveCount': len(live),
            'updateCount': int(time.time() / 900), 'trading': is_trading
        }
    }
    if old_cycle:
        out['recap']['cycle'] = old_cycle
    else:
        # Auto-generate cycle from index
        avg_chg = sum(float(i['chg'].replace('%','').replace('+','')) for i in indices[:4]) / max(len(indices[:4]), 1)
        up_n = sum(1 for i in indices[:4] if i['up'])
        phase = '强势上攻' if avg_chg > 1.5 and up_n >= 3 else '震荡偏强' if avg_chg > 0.3 else '窄幅震荡' if avg_chg >= -0.3 else '震荡回调' if avg_chg >= -1.5 else '恐慌下跌'
        icon = '🔥' if avg_chg > 1.5 else '📈' if avg_chg > 0.3 else '⚖️' if avg_chg >= -0.3 else '📉' if avg_chg >= -1.5 else '🔴'
        risk = 'medium' if avg_chg > 1.5 else 'low' if avg_chg > 0.3 else 'medium' if avg_chg >= -0.3 else 'medium' if avg_chg >= -1.5 else 'high'
        lab = '中等风险' if risk == 'medium' else '较低风险' if risk == 'low' else '高风险'
        sug = '可积极布局' if avg_chg > 0.3 else '精选个股为主' if avg_chg >= -0.3 else '控制仓位等待信号' if avg_chg >= -1.5 else '现金为王等待企稳'
        out['recap']['cycle'] = {'phase': phase, 'phaseIcon': icon, 'signals': [f'指数均涨{avg_chg:+.1f}%'], 'riskLevel': risk, 'riskLabel': lab, 'suggestion': sug}
    for k in ['sectors', 'top3', 'picks', 'briefing', 'events', 'layout', 'extraCodes', 'bHistory', 'concepts', 'dynamicSectors']:
        if k in existing and existing[k]: out[k] = existing[k]

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    ms = int((time.time() - tick) * 1000)
    print(f"{out['updated']} idx:{len(indices)} heat:{len(heat)} live:{len(live)} flow:{len(fund)} {ms}ms")

    # Git push
    subprocess.run([GIT, 'remote', 'set-url', 'origin', 'git@github.com:tt123497/market-sentinel.git'],
                   cwd=DIR, capture_output=True, timeout=10)
    subprocess.run([GIT, 'add', 'data.json'], cwd=DIR, capture_output=True, timeout=10)
    r = subprocess.run([GIT, 'diff', '--staged', '--quiet'], cwd=DIR, timeout=10)
    if r.returncode != 0:
        subprocess.run([GIT, 'commit', '-m', f"📊 {cst.strftime('%H:%M')} 东财全源更新"],
                       cwd=DIR, capture_output=True, timeout=10)
        subprocess.run([GIT, 'push', 'origin', 'main'], cwd=DIR,
                       env={**os.environ, 'GIT_SSH_COMMAND': 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10'},
                       capture_output=True, timeout=30)
        print('Pushed.')

if __name__ == '__main__':
    main()
