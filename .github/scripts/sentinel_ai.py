#!/usr/bin/env python3
"""Cloud Sentinel — AI 哨兵。每天4次用 DeepSeek API 生成高质量简报/赛道/标的。
质量校验：必须达到10条top3+10条picks才写入，不足则丢弃。"""
import json, os, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')
API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
API_URL = 'https://api.deepseek.com/v1/chat/completions'

OUR_SECTORS = '''AI芯片, CPO/硅光, 光模块, 光纤光缆, 连接器/铜连接,
  PCB/覆铜板, MLCC电容, 电子树脂/PPE, 电子铜箔, HBM/存储芯片,
  AI服务器/超节点, 液冷散热, 交换机/网络, 电源/DrMOS, 数据中心/AIDC,
  半导体设备, 光刻胶, 先进封装CoWoS, 半导体硅片,
  六氟化钨WF6, 玻璃基板TGV, 培育钻石/散热, 超导/核聚变, 碳纤维,
  人形机器人, 商业航天, 6G/通信, 固态电池, 低空经济eVTOL, 空间计算/物理AI, 钨稀土'''

def load_data():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def call_ai(prompt_text, max_tokens=4000):
    if not API_KEY:
        print('NO API KEY')
        return None
    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': '你是A股顶级市场分析师。请严格按JSON格式输出，不要加任何解释文字。所有赛道名必须使用系统指定的名称。'},
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

    if len(top3) < 3:
        print(f'REJECT: top3 count={len(top3)} < 3')
        return False
    if len(picks) < 3:
        print(f'REJECT: picks count={len(picks)} < 3')
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

    prompt = f"""当前时间：{cst.strftime('%Y年%m月%d日 %H:%M CST')}

请基于以下实时A股行情数据，给出深度市场分析并输出JSON。

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
    {{"name":"赛道名(必须从下方35赛道列表中选)","sig":"major/good/neutral/negative","msg":"信号描述+数据依据, 40字内","u":""}}
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

═══ 35赛道列表(必须从这里面选) ═══
{OUR_SECTORS}

═══ 要求 ═══
1. sectors输出12个赛道, sig按涨跌幅: >=3%为major, 0-3%为good, -1%~0为neutral, <-1%为negative
2. top3输出10条(!!!), 从市场最重要的维度切入(宏观/资金/板块/产业/风险), 每条b字段150-200字, 必须包含具体数据、信息来源、定价分析
3. picks输出10只精选标的, 每周角度推荐
4. 只用中文, 严格JSON, 不要markdown"""
    return prompt

def main():
    if not API_KEY:
        print('ERROR: DEEPSEEK_API_KEY not set in GitHub Secrets')
        return

    d = load_data()
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
