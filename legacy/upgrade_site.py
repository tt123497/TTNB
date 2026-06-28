path = r'D:\projects\market-dashboard\index.html'
with open(path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('setInterval(loadLive,300000)', 'setInterval(loadLive,30000)')
html = html.replace('<title>📡 股市哨兵 · AI全链+市场监控</title>', '<title>📡 LIVE · 股市哨兵</title>')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('OK')
