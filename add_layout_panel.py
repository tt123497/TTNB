#!/usr/bin/env python3
"""Add layout panel to index.html"""
import re

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add layout tab
html = html.replace(
    "const TABS=['overview','recap','briefing','chain','calendar','stocks'];",
    "const TABS=['overview','layout','recap','briefing','chain','calendar','stocks'];"
)
html = html.replace(
    "const TLABEL={overview:'📊 总览',recap:'📈 大盘复盘',briefing:'📰 简报',chain:'🗺️ 产业链',calendar:'📅 事件',stocks:'🎯 标的'};",
    "const TLABEL={overview:'📊 总览',layout:'📋 布局',recap:'📈 复盘',briefing:'📰 简报',chain:'🗺️ 产业链',calendar:'📅 事件',stocks:'🎯 标的'};"
)

# 2. Add D.layout merge in renderAll (after D.events merge)
html = html.replace(
    'if(data.events&&data.events.length) D.events=data.events;',
    'if(data.events&&data.events.length) D.events=data.events;\n    if(data.layout&&data.layout.length) D.layout=data.layout;'
)

# 3. Add CSS for layout cards
layout_css = '''
.layout-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;margin-bottom:10px;display:flex;gap:12px;align-items:flex-start}
.layout-card.urgent{border-left:3px solid var(--red);background:rgba(239,68,68,.04)}
.layout-card.hot{border-left:3px solid var(--amber)}
.layout-card.warm{border-left:3px solid var(--blue)}
.layout-card.normal{border-left:3px solid var(--border)}
.layout-card .lc-countdown{min-width:72px;text-align:center}
.layout-card .lc-countdown .lc-days{font-size:1.6rem;font-weight:800}
.layout-card .lc-countdown .lc-label{font-size:.68rem;color:var(--dim)}
.layout-card .lc-info{flex:1;min-width:0}
.layout-card .lc-title{font-size:.9rem;font-weight:600;margin-bottom:3px}
.layout-card .lc-sector{font-size:.72rem;color:var(--dim);margin-bottom:4px}
.layout-card .lc-lead{font-size:.7rem;color:var(--blue);margin-bottom:6px}
.layout-card .lc-stocks{display:flex;flex-wrap:wrap;gap:5px}
'''

html = html.replace('.evt-row.big{border-left:3px solid var(--red);background:rgba(239,68,68,.04)}',
                     '.evt-row.big{border-left:3px solid var(--red);background:rgba(239,68,68,.04)}' + layout_css)

# 4. Add layout panel HTML after overview panel (before recap)
# Find: </div></div>`; just before MARKET RECAP
layout_html = '''
  // ════ LAYOUT ════
  let lo=`<div class="tab-panel" id="panel-layout">
    <div class="section"><div class="section-title">📋 提前布局窗口</div>
    <p style="font-size:.84rem;color:var(--sub);margin-bottom:12px">按时间倒排。越近越红。标★为产业链重点标的。</p>
    <div class="layout-list">`;
  D.layout.forEach(function(ev){
    var cls=ev.days<=3?'urgent':ev.days<=7?'hot':ev.days<=14?'warm':'normal';
    var u=ev.u?' <a href="'+ev.u+'" target="_blank" rel="noopener" style="font-size:.64rem;color:var(--blue)">🔗</a>':'';
    lo+='<div class="layout-card '+cls+'"><div class="lc-countdown"><div class="lc-days" style="color:'+(ev.days<=3?'var(--red)':ev.days<=7?'var(--amber)':ev.days<=14?'var(--blue)':'var(--sub)')+'">'+(ev.days===0?'今天':ev.days+'天')+'</div><div class="lc-label">倒计时</div></div><div class="lc-info"><div class="lc-title">'+ev.icon+' '+ev.e+u+'</div><div class="lc-sector">🏷 '+ev.s+' | 📅 '+ev.d+'</div><div class="lc-lead">⏳ 建议提前'+(ev.lead||5)+'天布局 | 窗口期'+(ev.days-ev.lead>0?ev.days-ev.lead:0)+'天</div><div class="lc-stocks">'+(ev.stocks||[]).map(function(s){return '<span class="c-pill pick">'+s+'</span>';}).join('')+'</div></div></div>';
  });
  lo+=`</div></div></div>`;

  // ════ MARKET RECAP ════
'''

html = html.replace('  // ════ MARKET RECAP ════', layout_html + '\n  // ════ MARKET RECAP ════')

# 5. Update mainContent render line
html = html.replace(
    "document.getElementById('mainContent').innerHTML=ov+rc+br+ch+ca+st;",
    "document.getElementById('mainContent').innerHTML=ov+lo+rc+br+ch+ca+st;"
)

# 6. Add layout to loadLive refresh (after calendar refresh, before UpdateBar)
layout_loadlive = '''
        // Layout refresh
        var lop=document.getElementById('panel-layout');if(lop&&d.layout){
          var ll=lop.querySelector('.layout-list');
          if(ll&&d.layout.length){
            var loHtml='';
            d.layout.forEach(function(ev){
              var cls=ev.days<=3?'urgent':ev.days<=7?'hot':ev.days<=14?'warm':'normal';
              var u=ev.u?' <a href="'+ev.u+'" target="_blank" rel="noopener" style="font-size:.64rem;color:var(--blue)">🔗</a>':'';
              loHtml+='<div class="layout-card '+cls+'"><div class="lc-countdown"><div class="lc-days" style="color:'+(ev.days<=3?'var(--red)':ev.days<=7?'var(--amber)':ev.days<=14?'var(--blue)':'var(--sub)')+'">'+(ev.days===0?'today':'D-'+ev.days)+'</div><div class="lc-label">countdown</div></div><div class="lc-info"><div class="lc-title">'+ev.icon+' '+ev.e+u+'</div><div class="lc-sector">'+ev.s+' | '+ev.d+'</div><div class="lc-lead">advance '+(ev.lead||5)+'d | window '+(ev.days-ev.lead>0?ev.days-ev.lead:0)+'d</div><div class="lc-stocks">'+(ev.stocks||[]).map(function(s){return '<span class="c-pill pick">'+s+'</span>';}).join('')+'</div></div></div>';
            });
            ll.innerHTML=loHtml;
          }
        }

        // UpdateBar + LivePrices
'''

html = html.replace('\n        // UpdateBar + LivePrices', layout_loadlive + '\n        // UpdateBar + LivePrices')

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('Layout panel added to index.html')
print(f'New size: {len(html)} bytes')
