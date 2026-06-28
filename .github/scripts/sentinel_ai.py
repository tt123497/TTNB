#!/usr/bin/env python3
"""Cloud Sentinel — AI 哨兵。每小时用 DeepSeek API 扫描市场变化，
更新简报/赛道信号/精选标的/新事件。
校验：≥5条top3+≥5条picks才写入，不足则保留上一版。"""
import json, os, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')
API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
API_URL = 'https://api.deepseek.com/v1/chat/completions'

OUR_SECTORS = '''锂矿/盐湖提锂, 锂电池/电解液, 光伏/太阳能, 风电, 储能, 新能源汽车,
  PCB/覆铜板, MLCC电容, 电子树脂/PPE, 电子铜箔, HBM/存储芯片,
  AI服务器/超节点, 液冷散热, 交换机/网络, 电源/DrMOS, 数据中心/AIDC,
  半导体设备, 光刻胶, 先进封装CoWoS, 半导体硅片,
  六氟化钨WF6, 玻璃基板TGV, 培育钻石/散热, 超导/核聚变, 碳纤维,
  算电协同, 电网设备/特高压, 火电/电力运营, 算力租赁/GPU云,
  稀土永磁, 钼/小金属, 电子特气/工业气体, 半导体靶材, AI眼镜/AR硬件, AI应用/模型推理, 核电/核能, 量子计算/量子科技, 卫星互联网/北斗,
  人形机器人, 商业航天, 6G/通信, 固态电池, 低空经济eVTOL, 空间计算/物理AI, 钨稀土,
  煤炭, 黄金/贵金属, 铜铝有色, 化工, 钢铁,
  银行, 券商, 保险, 房地产开发,
  白酒, 食品饮料, 医药/CRO, 医疗器械'''

def load_data():
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"ERROR: corrupted data.json: {e}")
        return None

def save_data(d):
    tmp_path = DATA_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_PATH)

def call_ai(prompt_text, max_tokens=4000):
    if not API_KEY:
        print('NO API KEY')
        return None
    payload = {
        'model': 'deepseek-v4-pro',
        'messages': [
            {'role': 'system', 'content': '你是A股实时市场分析师。每小时扫描一次数据变化，重点捕捉最近一小时的异动。严格按JSON格式输出，赛道名只用系统指定名称。'},
            {'role': 'user', 'content': prompt_text}
        ],
        'temperature': 0.3,
        'max_tokens': max_tokens,
        'response_format': {'type': 'json_object'}
    }
    req = Request(API_URL, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'})
    try:
        r = urlopen(req, timeout=60)
        resp = json.loads(r.read().decode('utf-8'))
        content = resp['choices'][0]['message']['content']
        return json.loads(content)
    except Exception as e:
        print(f'AI error: {e}')
        return None

def validate_output(result):
    """Return True if AI output meets quality standards"""
    b = result.get('briefing', {})
    top3 = b.get('top3', [])
    picks = b.get('picks', [])
    sectors = result.get('sectors', [])

    if len(top3) < 5:
        print(f'REJECT: top3 count={len(top3)} < 5')
        return False
    if len(picks) < 5:
        print(f'REJECT: picks count={len(picks)} < 5')
        return False
    if len(sectors) < 3:
        print(f'REJECT: sectors count={len(sectors)} < 3')
        return False

    # Check each top3 has required fields
    for i, n in enumerate(top3):
        if not n.get('t') or not n.get('b'):
            print(f'REJECT: top3[{i}] missing title/body')
            return False
        if not n.get('s') or not isinstance(n['s'], list):
            n['s'] = []

    for i, p in enumerate(picks):
        if not p.get('c') or not p.get('n') or not p.get('why'):
            print(f'REJECT: picks[{i}] missing code/name/why')
            return False

    # Check events
    new_events = result.get('newEvents', [])
    if new_events:
        for i, ev in enumerate(new_events):
            if not ev.get('d') or not ev.get('e'):
                print('REJECT: newEvents[%d] missing date/title' % i)
                # don't reject entire output, just drop bad events
                new_events[i] = None
        result['newEvents'] = [ev for ev in new_events if ev is not None]

    return True

def build_prompt(d):
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    r = d.get('recap', {})
    indices = r.get('index', [])
    heat = r.get('heat', [])
    flow = r.get('flow', [])
    zt = r.get('ztLadder', {})
    winners = r.get('winners', [])
    losers = r.get('losers', [])

    idx_str = ' | '.join([f"{i['n']}:{i['v']} {i['chg']}" for i in indices[:6]])
    heat_str = '\n'.join([f"  {h['n']} {h['s']}" for h in heat[:25]])
    flow_str = '\n'.join([f"  {f['n']} {f['amt']}" for f in flow[:10]])
    zt_str = f"总数{zt.get('totalCount',0)}只, 最高{zt.get('maxBoard',0)}连板"
    winners_str = '\n'.join([f"  {w['s']}: {w.get('stks','')[:100]}" for w in winners[:6]])
    losers_str = '\n'.join([f"  {l['s']}: {l.get('stks','')[:100]}" for l in losers[:6]])

    # ── ⭐ NEW: 北向资金 ──
    nb = d.get('northbound', {})
    nb_str = ''
    if nb.get('points', 0) > 0:
        nb_str = f"北向资金: 沪股通{nb.get('hgt_yi',0)}亿 深股通{nb.get('sgt_yi',0)}亿 合计净{nb.get('net_yi',0)}亿 | 状态:{nb.get('status','?')}"
    else:
        nb_str = f"北向资金: 暂无实时数据 ({nb.get('status','?')})"

    # ── ⭐ NEW: 同花顺热点归因 Top10 ──
    hot = d.get('_hotReasons', {})
    hot_str = ''
    if hot.get('total', 0) > 0:
        hot_tags = ', '.join([f"{t['tag']}({t['count']})" for t in hot.get('topReasons', [])[:10]])
        hot_str = f"热点题材频率: {hot_tags}"
        hot_top5 = hot.get('stocks', [])[:5]
        if hot_top5:
            hot_str += '\n热点Top5: ' + ' | '.join([f"{s['c']} {s['n']} {s['reason']} +{s['chg']}%" for s in hot_top5])
    else:
        hot_str = f"热点归因: {hot.get('status','暂无')}"

    # ── ⭐ NEW: 龙虎榜摘要 ──
    lhbf = d.get('lhbFull', {})
    lhb_str = ''
    if lhbf.get('total', 0) > 0:
        top_lhb = lhbf.get('stocks', [])[:8]
        lhb_str = f"龙虎榜{lhbf['total']}条, 净买Top8:\n"
        lhb_str += '\n'.join([f"  {s['c']} {s['n']} 净买{s['net']}万 {s.get('reason','')[:20]} 涨跌{s.get('chg',0)}%" for s in top_lhb])
    else:
        lhb_str = '龙虎榜: 今日无数据'

    # ── ⭐ NEW: 解禁预警 ──
    lockup = d.get('lockupAlerts', {})
    lockup_str = ''
    if lockup.get('alerts'):
        top_lockup = lockup['alerts'][:5]
        lockup_str = f"未来90天解禁: {len(lockup['alerts'])}批, 重点关注:\n"
        lockup_str += '\n'.join([f"  {a['d']} {a['c']} {a['n']} {a['type']} {a['shares']}万股({a['ratio']}%)" for a in top_lockup])
    else:
        lockup_str = '解禁预警: 未来90天无重大解禁'

    # Read recent real news for the AI to reference (three channels)
    ns = d.get('_newsSector', [])[:15]
    nm = d.get('_newsMarket', [])[:10]
    gn = d.get('globalNews', {}).get('headlines', [])[:10]
    if ns or nm or gn:
        news_text = '══ 赛道新闻 ══\n'
        news_text += '\n'.join([f"  [{n.get('time','?')}] {n.get('t','')}  {n.get('u','')}" for n in ns])
        news_text += '\n══ 市场宏观 ══\n'
        news_text += '\n'.join([f"  [{n.get('time','?')}] {n.get('t','')}  {n.get('u','')}" for n in nm])
        if gn:
            news_text += '\n══ 东财7x24快讯 ══\n'
            news_text += '\n'.join([f"  [{n.get('ts','?')}] {n.get('t','')}" for n in gn])
    else:
        news_text = '暂无实时新闻'

    prompt = f"""当前时间：{cst.strftime('%Y年%m月%d日 %H:%M CST')}（每小时扫描）

═══ 最近真实新闻 ═══
{news_text}

═══ 实时行情数据 ═══

═══ 指数 ═══
{idx_str}

═══ 基金流向(TOP10) ═══
{flow_str}

═══ 领涨方向(TOP6, 含个股) ═══
{winners_str}

═══ 领跌方向(TOP6, 含个股) ═══
{losers_str}

═══ 涨停概况 ═══
{zt_str}

═══ 25大热力板块 ═══
{heat_str}

═══ ⭐ 北向资金(新增) ═══
{nb_str}

═══ ⭐ 同花顺热点归因(新增) ═══
{hot_str}

═══ ⭐ 龙虎榜Top8(新增) ═══
{lhb_str}

═══ ⭐ 解禁预警(新增) ═══
{lockup_str}

═══ 你的任务 ═══

必须输出如下JSON结构：

{{
  "cycle": {{
    "phase": "大盘阶段描述(8字内)",
    "phaseIcon": "一个emoji匹配phase",
    "signals": ["5条关键信号, 每条30字内, 要数据支撑"],
    "riskLevel": "low/medium/high",
    "riskLabel": "较低风险/中等风险/高风险",
    "suggestion": "操作建议(30字内)"
  }},
  "sectors": [
    {{"name":"赛道名(必须从下方62赛道列表中选)","sig":"major/good/neutral/negative","msg":"信号描述+数据依据, 40字内","u":""}}
  ],
  "briefing": {{
    "top3": [
      {{"r":1,"t":"标题(含emoji前缀, 25字内)","b":"正文(150-200字, 数据+分析+来源+定价状态)","s":["代码 名称 代码 名称"],"u":"新闻链接可为空"}}
    ],
    "picks": [
      {{"r":1,"c":"6位代码","n":"名称","why":"推荐理由(25字内)","sec":"所属赛道"}}
    ]
  }}
}}

═══ 63赛道列表(必须从这里面选) ═══
{OUR_SECTORS}

═══ 要求 ═══
1. sectors输出20个赛道, sig按涨跌幅: >=3%为major, 0-3%为good, -1%~0为neutral, <-1%为negative
2. top3输出10条(!!!), 从市场最重要的维度切入(宏观/资金/板块/产业/风险), 每条b字段150-200字, 必须包含具体数据、信息来源、定价分析
3. picks输出10只精选标的, 每周角度推荐
4. newEvents: 列出未来30天内所有A股重要事件(不限赛道,财报/会议/政策/数据发布/产业催化/宏观数据), 每条必须含: d(月+日), icon(emoji), e(标题), s(赛道名或行业名), big(1=硬催化如停产/涨价/法规/财报,0=普通会议), desc(20字内说明), u(!!!必须填真实新闻链接URL,不能为空,从最近新闻中引用或填真实URL)
5. 每个top3的u字段必须从最近真实新闻中引用URL，不能编造。如果没有匹配新闻，填https://data.eastmoney.com/
6. 只用中文, 严格JSON, 不要markdown"""
    return prompt

def main():
    if not API_KEY:
        print('ERROR: DEEPSEEK_API_KEY not set in GitHub Secrets')
        return

    d = load_data()
    if d is None:
        print("ERROR: cannot load data.json, giving up")
        return
    cst = datetime.now(timezone.utc) + timedelta(hours=8)

    prompt = build_prompt(d)
    print(f'Sending AI prompt ({len(prompt)} chars)...')
    result = call_ai(prompt, max_tokens=8000)
    if not result:
        return

    if not validate_output(result):
        print('AI output rejected — keeping existing data')
        return

    # Merge
    if 'cycle' in result:
        d['recap']['cycle'] = result['cycle']
        print(f"OK  Cycle: {result['cycle'].get('phase','?')}")

    if 'sectors' in result:
        d['sectors'] = result['sectors']
        print(f"OK  Sectors: {len(result['sectors'])}")

    if 'newEvents' in result and result['newEvents']:
        existing_events = d.get('events', [])
        new_events = result['newEvents']
        # De-duplicate by date+title
        seen = set()
        for ev in existing_events:
            seen.add((ev.get('d',''), ev.get('e','')))
        added = 0
        for ev in new_events:
            key = (ev.get('d',''), ev.get('e',''))
            if key not in seen and len(ev.get('d','')) >= 4:
                seen.add(key)
                existing_events.append(ev)
                added += 1
        # Cap at 60 events total
        if len(existing_events) > 60:
            existing_events = existing_events[-60:]
        d['events'] = existing_events
        print("Events: +%d new" % added)

    if 'briefing' in result:
        b = result['briefing']
        # Archive old
        old_bf = d.get('briefing', {})
        if old_bf.get('top3'):
            bHistory = d.get('bHistory', [])
            last_date = bHistory[0].get('updated','') if bHistory else ''
            if old_bf.get('updated','') != last_date:
                bHistory.insert(0, old_bf)
                d['bHistory'] = bHistory[:30]

        b['updated'] = cst.strftime('%Y-%m-%d %H:%M CST')
        d['briefing'] = b
        d['top3'] = b['top3']
        d['picks'] = b['picks']
        print(f"OK  Briefing: {len(b['top3'])} top3, {len(b['picks'])} picks")

    d['updated'] = cst.strftime('%Y-%m-%d %H:%M CST')
    save_data(d)
    print('Sentinel scan complete')

if __name__ == '__main__':
    main()
