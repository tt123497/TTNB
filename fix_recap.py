with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

start = html.find('// ════ MARKET RECAP ════')
end = html.find('// ════ BRIEFING ════')
old_block = html[start:end]

new_block = '''  // ════ MARKET RECAP ════
  let rc=`<div class="tab-panel" id="panel-recap">
    <div class="section"><div class="section-title" id="recapTitle">📈 大盘复盘 · ${D.updated}</div>
    <p style="font-size:.84rem;color:var(--sub);margin-bottom:12px">${D.recap.note}</p></div>

    <div class="section"><div class="section-title">📊 主要指数</div>
    <div class="recap-grid">${D.recap.index.map(i=>`<div class="recap-chip">
      <div class="rc-val" style="color:${i.up?'var(--green)':'var(--red)'}">${i.chg}</div>
      <div class="rc-label">${i.n}</div>
      <div class="rc-sub">${i.v}</div>
    </div>`).join('')}</div></div>

    <div class="section"><div class="section-title">💸 主力资金</div>
    <div class="recap-bar">${(()=>{let t=0;D.recap.flow.forEach(f=>{if(f.amt.startsWith('+'))t+=parseInt(f.amt.replace(/[+亿]/g,''));});return D.recap.flow.map(f=>{const v=f.amt.startsWith('+')?parseInt(f.amt.replace(/[+亿]/g,'')):0;const p=v/249*100;const colors=['var(--blue)','var(--purple)','var(--cyan)','var(--teal)','var(--amber)','var(--red)'];return '<div style="width:'+Math.max(p,3)+'%;background:'+colors[D.recap.flow.indexOf(f)%6]+'"></div>';}).join('');})()}</div>
    <div style="display:flex;flex-wrap:wrap;gap:10px;font-size:.84rem">${D.recap.flow.map((f,i)=>{const colors=['var(--blue)','var(--purple)','var(--cyan)','var(--teal)','var(--amber)','var(--red)'];return '<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:'+colors[i]+';margin-right:4px"></span>'+f.n+' '+f.amt+'</span>';}).join('')}</div></div>

    <div class="section"><div class="section-title">🔥 最热板块</div>
    <div class="heat-row">${D.recap.heat.map(h=>'<span class="heat-tag" style="background:'+(h.c=='var(--red)'?'rgba(239,68,68,.12)':'rgba(245,158,11,.12)')+';color:'+h.c+'">'+h.n+' '+h.s+'</span>').join('')}</div></div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="section" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px">
        <div class="section-title" style="color:var(--green);font-size:1rem">🟢 领涨方向</div>
        ${D.recap.winners.map(w=>'<div style="margin-bottom:12px"><div style="color:var(--green);font-weight:600;font-size:.88rem;margin-bottom:4px">✅ '+w.s+'</div><div style="font-size:.78rem;color:var(--sub);line-height:1.9">'+w.stks.split(' / ').map(st=>'<div style="font-family:SF Mono,Fira Code,monospace;font-size:.76rem;padding:2px 0">  '+st+'</div>').join('')+'</div></div>').join('')}
      </div>
      <div class="section" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px">
        <div class="section-title" style="color:var(--red);font-size:1rem">🔴 领跌方向</div>
        ${D.recap.losers.map(l=>'<div style="margin-bottom:12px"><div style="color:var(--red);font-weight:600;font-size:.88rem;margin-bottom:4px">❌ '+l.s+'</div><div style="font-size:.78rem;color:var(--sub);line-height:1.9">'+l.stks.split(' / ').map(st=>'<div style="font-family:SF Mono,Fira Code,monospace;font-size:.76rem;padding:2px 0">  '+st+'</div>').join('')+'</div></div>').join('')}
      </div>
    </div></div>`;

  // ════ BRIEFING ════
'''

html = html.replace(old_block, new_block)
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('OK:', len(html))
