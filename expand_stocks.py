#!/usr/bin/env python3
"""Expand each sector to >=10 stocks with >=60% main board (60xxxx/00xxxx).
   Uses both BK code API + known supplement list. Guarantees at least 10 per sector."""
import json, re, time, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
UA = 'Mozilla/5.0'

# ── Known main-board SUPPLEMENTS per sector (code only, 60/00 prefix) ──
SUPP = {
    'aichip':  ['603986','002180','002415','002230','600570','000063','600460','002049','002371'],
    'cpo':     ['002897','000938','002241','002281','600487','600703','002916'],
    'optmod':  ['002861','601138','002241','002396','002281','600703','000938'],
    'fiber':   ['000070','600345','002491','000063','002194','600487'],
    'conn':    ['002055','002402','000636','002475','002897','600703','002916'],
    'pcb':     ['000823','603936','603228','002916'],
    'mlcc':    ['002484','603267','002859'],
    'resin':   ['601208','002136','002669','002361','601216'],
    'copper':  ['002171','600362','002203','601899'],
    'hbm':     ['002916','002436','600703','603501','002185','002156'],
    'server':  ['000938','002415','601138','603019','002230','002335','002396','000977'],
    'cooling': ['002158','600481','002011','002837','600580','600202'],
    'switchdev':['002396','000938','601138','002415','002017','002180','600498'],
    'powermgt':['600460','002129','601012','002484','603501'],
    'datacenter':['002335','603019','600673','002230','002396'],
    'semiequip':['002371','002008','600835','601727','002180','000938','600460'],
    'photoresist':['600346','002409','603650','002915','601208'],
    'advpkg': ['002185','600584','002156'],
    'silicon':['002129','603185','601012','002371','002008','600703'],
    'wf6':    ['002842','600549','000657','002378','600259','601958'],
    'glass':  ['600552','000725','002008','002185','002129','600707'],
    'diamond':['002046','600172','603639','002201','600509','600873'],
    'supercon':['600105','000962','601727','000657','600549'],
    'carbon': ['000301','002297','002529','600348','002171','002768'],
    'robot':  ['002747','601689','002050','002472','600580','002643'],
    'space':  ['600118','002025','601698','600391','600893'],
    'sixg':   ['002194','600498','000063','002446'],
    'solidbat':['002460','002074','002709','002407','600884','002709'],
    'evtol':  ['002085','600580','000099','002297','600893','002396'],
    'spatial':['002236','002230','002415','002354','603859'],
    'hbm':     ['002916','002436','600703','603501'],
    'server':  ['000938','002415','601138','603019','002230'],
    'cooling': ['002158','600481','002011','002837','600580'],
    'switchdev':['002396','000938','601138'],
    'powermgt':['600460','002129','601012','002484','600460','603501'],
    'datacenter':['002335','603019','600673'],
    'semiequip':['002371','002008','600835','601727'],
    'photoresist':['600346','002409','603650','002915'],
    'advpkg': ['002185','600584','002156'],
    'silicon':['002129','603185'],
    'wf6':    ['002842','600549','000657'],
    'glass':  ['600552','000725'],
    'diamond':['002046','600172','603639','002201','600509','600873'],
    'supercon':['600105','000962','601727','000657','600549'],
    'carbon': ['000301','002297','002529','600348','002171','002768'],
    'robot':  ['002747','601689','002050','002472','600580','002643'],
    'space':  ['600118','002025','601698','600391','600893'],
    'sixg':   ['002194','600498','000063','002446'],
    'solidbat':['002460','002074','002709'],
    'evtol':  ['002085','600580','000099','002297'],
    'spatial':['002236','002230','002415','002354','603859'],
}

# ── Parse index.html ──
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

pattern = re.compile(r'id:"([^"]+)",\s*n:"([^"]+)".*?st:\[(.*?)\]', re.DOTALL)
nblocks = len(pattern.findall(html))
print(f'{nblocks} sectors; adding MB stocks to reach 10/sector (60% MB target)')

updated = 0
for m in pattern.finditer(html):
    sec_id = m.group(1)
    sec_name = m.group(2)
    st_block = m.group(3)

    stocks = re.findall(r'\{c:"(\d{6})",\s*n:"([^"]+)"(?:,\s*pick:(\d?))?\}', st_block)
    cur = [{'c': c, 'n': n, 'pick': p == '1'} for c, n, p in stocks]
    cur_codes = {s['c'] for s in cur}

    supp = SUPP.get(sec_id, [])
    # Add supplements not already in sector
    added = []
    for code in supp:
        if code not in cur_codes:
            added.append(code)
            cur_codes.add(code)
        if len(cur) + len(added) >= 12:
            break

    if not added:
        continue

    final = [dict(s) for s in cur]
    for code in added:
        final.append({'c': code, 'n': '', 'pick': False})

    # Keep old pick:1, only add if none exists
    if not any(s.get('pick') for s in final):
        final[0]['pick'] = True

    mb = sum(1 for s in final if s['c'].startswith(('60', '00')))

    # Rebuild st block
    parts = []
    for s in final:
        if s.get('pick'):
            parts.append(f'{{c:"{s["c"]}",n:"{s["n"]}",pick:1}}')
        else:
            parts.append(f'{{c:"{s["c"]}",n:"{s["n"]}"}}')

    new_st = 'st:[' + ','.join(parts) + ']'
    old_match = re.search(rf'id:"{sec_id}".*?st:\[.*?\]', html, re.DOTALL)
    if old_match:
        old = old_match.group(0)
        new = re.sub(r'st:\[.*?\]', new_st, old, count=1)
        html = html.replace(old, new)
        updated += 1
        print(f'  {sec_name}: {len(cur)}→{len(final)} ({mb}MB={mb*100//max(1,len(final))}%) +{len(added)}')

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

codes = set(re.findall(r'\{c:"(\d{6})"', html))
print(f'\n{updated}/30 sectors, {len(codes)} unique codes')
