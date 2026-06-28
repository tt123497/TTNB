#!/usr/bin/env python3
"""Build layout data: future events with countdown, stock picks, lead time"""
import json, re
from datetime import date

d = json.load(open('data.json', 'r', encoding='utf-8'))
events = d.get('events', [])

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

sector_stocks = {}
id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)

for i in range(min(len(id_names), len(st_blocks))):
    _, sec_name = id_names[i]
    st_block = st_blocks[i]
    pick_stocks, regular_stocks = [], []
    all_stocks = re.findall(r'\{c:"(\d{6})",\s*n:"([^"]+)"(?:,\s*pick:1)?\}', st_block)
    for code, name in all_stocks:
        pos = st_block.find(code)
        (pick_stocks if 'pick:1' in st_block[max(0,pos-10):pos+30] else regular_stocks).append(f'{code} {name}')
    sector_stocks[sec_name] = pick_stocks + regular_stocks

sector_map = {
    'AI/鸿蒙': 'AI服务器/超节点', 'AI/大模型': 'AI芯片', 'AI应用': '交换机/网络',
    'AI/互联网': '交换机/网络', 'AI算力': 'AI服务器/超节点', '消费电子/AI硬件': '连接器/铜连接',
    '半导体全链': '半导体设备', '数字经济': '数据中心/AIDC', '存储/设备': 'HBM/存储芯片',
    '存储芯片': 'HBM/存储芯片', 'HBM/先进封装': '先进封装CoWoS', '低空经济': '低空经济eVTOL',
    '六氟化钨': '六氟化钨WF₆', '人形机器人': '人形机器人', '商业航天': '商业航天',
    '固态电池': '固态电池', 'MLCC': 'MLCC电容', '钨/稀土': '六氟化钨WF₆',
    '钨': '六氟化钨WF₆', '稀土': '六氟化钨WF₆',
}

def match_sector(event_sector, event_name):
    if event_sector in sector_map: return sector_map[event_sector]
    for alias, target in sector_map.items():
        if alias in event_sector or event_sector in alias: return target
    words = set(w for w in re.split(r'[/\s]+', event_sector) if w)
    for sec_name in sector_stocks:
        sec_words = set(w for w in re.split(r'[/\s]+', sec_name.replace('WF₆','WF6').replace('CoWoS','')) if w)
        if words & sec_words: return sec_name
    return None

today = date.today()
layout = []

for e in events:
    m = re.search(r'(\d+)月(\d+)日', e['d'])
    event_date = None
    if m: event_date = date(2026, int(m.group(1)), int(m.group(2)))
    else:
        m2 = re.search(r'(\d+)月([上中下])旬', e['d'])
        if m2: event_date = date(2026, int(m2.group(1)), {'上':5,'中':15,'下':25}[m2.group(2)])
    if not event_date or event_date < today: continue

    days_left = (event_date - today).days
    matched_sec = match_sector(e['s'], e['e'])

    if '全部赛道' in e['s']:
        stocks = sorted(set(s for sl in sector_stocks.values() for s in sl[:2]))[:12]
    elif matched_sec:
        stocks = sector_stocks.get(matched_sec, [])[:6]
    else:
        stocks = []

    big = e.get('big', 0)
    lead = max(7, min(21, days_left // 3)) if big else max(5, min(14, days_left // 4))

    layout.append({
        'd': e['d'], 'days': days_left, 'lead': lead,
        'e': e['e'], 'icon': e['icon'], 's': e['s'], 'big': big,
        'stocks': stocks, 'u': e.get('u', ''),
    })

layout.sort(key=lambda x: x['days'])
d['layout'] = layout
json.dump(d, open('data.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('Layout: %d events, %d empty' % (len(layout), sum(1 for e in layout if not e['stocks'])))
