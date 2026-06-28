"""Upgrade website: briefing from data.json, 30s price refresh"""
import re

path = r'D:\projects\market-dashboard\index.html'
with open(path, 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Change refresh from 5min to 30s
html = html.replace('setInterval(loadLive,300000)', 'setInterval(loadLive,30000)')

# 2. Add briefing loader to loadLive function
old_loadlive = 'function loadLive(){'
new_loadlive = '''function loadLive(){
      // Briefing from cloud
      var bp=document.getElementById('panel-briefing');if(bp){
        fetch('./data.json?t='+Date.now()).then(function(r){return r.json()}).then(function(d){
          if(d.briefing){
            var b=d.briefing;
            var topNewsDiv=bp.querySelector('.section:first-child');
            if(topNewsDiv&&b.top3){
              var newsHtml='<div class="section-title">📰 云端实时简报</div>';
              b.top3.forEach(function(n){
                newsHtml+='<div class="news-card"><div class="n-head"><div class="n-rank r'+n.r+'">'+n.r+'</div><div class="n-title">'+n.t+'</div></div><div class="n-body">'+n.b+'</div><div class="n-pills">'+(n.s||[]).map(function(x){return '<span class="c-pill pick">'+x+'</span>';}).join('')+'</div></div>';
              });
              topNewsDiv.innerHTML=newsHtml;
            }
            var picksDiv=bp.querySelector('.section:last-child');
            if(picksDiv&&b.picks){
              var picksHtml='<div class="section-title">🎯 云端精选标的</div><div class="pick-row">';
              b.picks.forEach(function(p){
                picksHtml+='<div class="pick-item"><div class="pi-rank">#'+p.r+'</div><div class="pi-info"><div><span class="pi-name">'+p.n+'</span><span class="pi-code">'+p.c+'</span></div><div class="pi-reason">'+p.why+'</div></div><div class="pi-sector">'+p.sec+'</div></div>';
              });
              picksHtml+='</div>';
              picksDiv.innerHTML=picksHtml;
            }
          }
        }).catch(function(){});
      }'''

html = html.replace(old_loadlive, new_loadlive)

# 3. Update title
html = html.replace('<title>📡 股市哨兵 · AI全链+市场监控</title>', '<title>📡 LIVE · 股市哨兵</title>')

# 4. Remove the "REALTIME" label and put cloud status
html = html.replace("document.getElementById('updateBar').innerHTML='REALTIME <b>'+d.updated+'</b> | '+lc+' stocks tracking | auto-refresh 5min';",
                    "document.getElementById('updateBar').innerHTML='☁️ 云端实时 · <b>'+d.updated+'</b> | '+lc+'只标的 | 每15分钟自动刷新 | 电脑关机也能看';")

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)

print('Briefing + live engine upgraded')
