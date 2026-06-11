#!/usr/bin/env python3
"""Fill ALL empty stock names in index.html"""
import json, re

d = json.load(open('data.json', 'r', encoding='utf-8'))
name_map = {}
for k, v in d['livePrices'].items():
    if v.get('name'):
        name_map[k[2:]] = v['name']

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Collect existing names
fill = re.findall(r'\{c:"(\d{6})",n:"([^"]+)"', html)
for c, n in fill:
    if n and c not in name_map:
        name_map[c] = n

fixed = 0
while True:
    m = re.search(r'\{c:"(\d{6})",n:""\}', html)
    if not m:
        break
    code = m.group(1)
    name = name_map.get(code, 'unknown')
    repl = '{c:"%s",n:"%s"}' % (code, name)
    html = html[:m.start()] + repl + html[m.end():]
    fixed += 1

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

empty = len(re.findall(r'n:""', html))
print('Fixed: %d, still empty: %d' % (fixed, empty))
