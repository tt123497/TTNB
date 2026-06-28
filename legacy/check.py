import json, re

html = open('index.html', 'r', encoding='utf-8').read()
d = json.load(open('data.json', 'r', encoding='utf-8'))
r = d['recap']
b = d['briefing']

issues = []

# 1. updateBar truth
if '电脑关机也能看' in html:
    issues.append('updateBar still says 电脑关机也能看')
if '每15分钟' in html:
    issues.append('updateBar still says 每15分钟')

# 2. Stock names
hc = len(set(re.findall(r'\{c:"(\d{6})"', html)))
empty = len(re.findall(r'n:""', html))
if empty:
    issues.append('%d stocks with empty name' % empty)

# 3. Data
if len(r['index']) < 6:
    issues.append('index: %d (need 6+)' % len(r['index']))
if len(r['heat']) < 10:
    issues.append('heat: %d (need 10+)' % len(r['heat']))
if len(r['flow']) < 3:
    issues.append('flow: %d (need 3+)' % len(r['flow']))

# 4. URLs
if not b.get('top3'):
    issues.append('briefing top3 empty')
else:
    for n in b['top3']:
        if not n.get('u'):
            issues.append('top3 #%d no URL' % n['r'])
if not b.get('picks'):
    issues.append('briefing picks empty')
else:
    for p in b['picks']:
        if not p.get('u'):
            issues.append('pick %s no URL' % p['c'])

if not d.get('sectors'):
    issues.append('sectors empty')
else:
    for s in d['sectors']:
        if not s.get('u'):
            issues.append('sector %s no URL' % s['name'])

if not d.get('events'):
    issues.append('events empty')

if not d.get('layout'):
    issues.append('layout empty')

# 5. JS features
if 'function renderAll()' not in html:
    issues.append('renderAll missing')
if 'D.livePrices=data.livePrices' not in html:
    issues.append('D.livePrices merge missing')
if 'window.searchStock=searchStock' not in html:
    issues.append('searchStock export missing')
if '现价' not in html:
    issues.append('现价 header missing')
if 'evt-row.past' not in html:
    issues.append('event archive CSS missing')
if '已过期' not in html:
    issues.append('已过期 section missing')
if 'panel-layout' not in html:
    issues.append('layout panel missing')
if 'panel-calendar' not in html:
    issues.append('calendar panel missing')
if 'panel-recap' not in html:
    issues.append('recap panel missing')
if 'split' not in html and 'stks' not in html:
    issues.append('winners/losers stock detail missing')
if 'c-msg' not in html:
    issues.append('sector msg link missing')
if 'chg_pct>=0?' in html and 'green' in html:
    pass
else:
    issues.append('red/green direction may be wrong')
if '6月9日' in html:
    issues.append('old hardcoded date still present')

print('codes=%d empty_names=%d' % (hc, empty))
print('idx=%d heat=%d flow=%d win=%d lose=%d' % (
    len(r['index']), len(r['heat']), len(r['flow']), len(r['winners']), len(r['losers'])))
print('sec=%d evt=%d lay=%d t3=%d pk=%d' % (
    len(d['sectors']), len(d['events']), len(d['layout']), len(b['top3']), len(b['picks'])))
print('livePrices=%d' % len(d['livePrices']))
print()
if issues:
    print('ISSUES (%d):' % len(issues))
    for i in issues:
        print('  - ' + i)
else:
    print('ALL CLEAN')
