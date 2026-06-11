#!/usr/bin/env python3
"""Build layout data: future events with countdown, stock picks, lead time"""
import json, re
from datetime import date

d = json.load(open('data.json', 'r', encoding='utf-8'))
events = d['events']

# Parse sector-stock mapping from index.html
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

sector_stocks = {}
id_names = re.findall(r'id:"([^"]+)",\s*n:"([^"]+)"', html)
st_blocks = re.findall(r'st:\[(.*?)\]', html, re.DOTALL)

for i in range(min(len(id_names), len(st_blocks))):
    _, sec_name = id_names[i]
    st_block = st_blocks[i]
    stocks = re.findall(r'\{c:"(\d{6})",\s*n:"([^"]+)"(?:,\s*pick:1)?\}', st_block)
    # Separate pick=1 and regular stocks
    pick_stocks = []
    regular_stocks = []
    for code, name in stocks:
        pos = st_block.find(code)
        snippet = st_block[max(0,pos-20):pos+40]
        if 'pick:1' in snippet:
            pick_stocks.append(f'{code} {name}')
        else:
            regular_stocks.append(f'{code} {name}')
    sector_stocks[sec_name] = pick_stocks + regular_stocks  # picks first

# Fuzzy match event sector -> D.groups sector
def match_sector(event_sector):
    for sec_name in sector_stocks:
        # Direct match
        if event_sector in sec_name or sec_name in event_sector:
            return sec_name
        # Keyword overlap
        words = set(event_sector.replace('/', ' ').split())
        sec_words = set(sec_name.replace('/', ' ').replace('WF₆', 'WF6').split())
        if words & sec_words:
            return sec_name
    return None

today = date.today()
layout = []

for e in events:
    m = re.search(r'(\d+)月(\d+)日', e['d'])
    event_date = None
    if m:
        event_date = date(2026, int(m.group(1)), int(m.group(2)))
    else:
        m2 = re.search(r'(\d+)月([上中下])旬', e['d'])
        if m2:
            day = {'上': 5, '中': 15, '下': 25}[m2.group(2)]
            event_date = date(2026, int(m2.group(1)), day)

    if not event_date or event_date < today:
        continue

    days_left = (event_date - today).days
    matched_sec = match_sector(e['s'])
    stocks = sector_stocks.get(matched_sec, [])[:6] if matched_sec else []

    big = e.get('big', 0)
    if big:
        lead = max(7, min(21, days_left // 3))
    elif days_left <= 7:
        lead = max(3, days_left - 1)
    else:
        lead = max(5, min(14, days_left // 4))

    layout.append({
        'd': e['d'],
        'days': days_left,
        'lead': lead,
        'e': e['e'],
        'icon': e['icon'],
        's': e['s'],
        'big': big,
        'stocks': stocks,
        'u': e.get('u', ''),
    })

layout.sort(key=lambda x: x['days'])

d['layout'] = layout
json.dump(d, open('data.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

print(f'Layout: {len(layout)} future events with stock picks')
for ev in layout[:10]:
    u = '⚡' if ev['days'] <= 3 else '🔥' if ev['days'] <= 7 else '🟡' if ev['days'] <= 14 else '🟢'
    print(f'  {u} D-{ev["days"]} | {ev["d"]} | {ev["e"][:35]} | stocks={len(ev["stocks"])}')
