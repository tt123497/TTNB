#!/usr/bin/env python3
"""Cloud Sentinel — AI 哨兵：用 DeepSeek API 扫描市场数据，生成简报/赛道信号/精选标的。
替代本地 Claude Cron。API Key 存在 GitHub Secrets (DEEPSEEK_API_KEY)。"""
import json, os, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')
API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
API_URL = 'https://api.deepseek.com/v1/chat/completions'

def load_data():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def call_ai(prompt_text, max_tokens=2000):
    """Call DeepSeek V4-Pro with structured output request"""
    if not API_KEY:
        print('NO API KEY — skipping AI scan')
        return None

    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': '你是A股市场分析师。请严格按JSON格式输出，不要加任何解释文字。'},
            {'role': 'user', 'content': prompt_text}
        ],
        'temperature': 0.3,
        'max_tokens': max_tokens,
        'response_format': {'type': 'json_object'}
    }
    data = json.dumps(payload).encode('utf-8')
    req = Request(API_URL, data=data, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}'
    })
    try:
        r = urlopen(req, timeout=30)
        resp = json.loads(r.read().decode('utf-8'))
        content = resp['choices'][0]['message']['content']
        return json.loads(content)
    except Exception as e:
        print(f'AI call failed: {e}')
        return None

def build_prompt(d):
    """Build analysis prompt from current market data"""
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    now_str = cst.strftime('%Y年%m月%d日 %H:%M')

    r = d.get('recap', {})
    indices = r.get('index', [])
    heat = r.get('heat', [])
    flow = r.get('flow', [])
    zt = r.get('ztLadder', {})
    winners = r.get('winners', [])
    losers = r.get('losers', [])

    idx_str = ' | '.join([f"{i['n']}:{i['v']} {i['chg']}" for i in indices[:4]])
    heat_str = ' | '.join([f"{h['n']} {h['s']}" for h in heat[:8]])
    flow_str = ' | '.join([f"{f['n']} {f['amt']}" for f in flow[:5]])
    zt_str = f"涨停{zt.get('totalCount',0)}只,最高{zt.get('maxBoard',0)}连板"

    prompt = f"""当前时间：{now_str}
请基于以下实时A股行情数据，进行市场分析并输出JSON。

【指数】{idx_str}
【热力板块TOP8】{heat_str}
【主力资金TOP5】{flow_str}
【涨停概况】{zt_str}

请输出以下JSON结构：
{{
  "cycle": {{
    "phase": "大盘阶段（如：主升浪中段/高位分化/震荡筑底）",
    "phaseIcon": "一个emoji对应phase",
    "signals": ["3-5条关键信号，每条不超过25字"],
    "riskLevel": "low/medium/high",
    "riskLabel": "较低风险/中等风险/高风险",
    "suggestion": "一句话操作建议"
  }},
  "sectors": [
    {{"name":"赛道名(35赛道之一)","sig":"major/good/neutral/negative","msg":"信号描述+数据依据,不超过40字"}}
    (输出12个主要赛道)
  ],
  "briefing": {{
    "top3": [
      {{"r":1,"t":"标题(含emoji)","b":"正文分析(100-150字)","s":["代码 名称"]}}
      (输出3条今日最重要的消息)
    ],
    "picks": [
      {{"r":1,"c":"代码","n":"名称","why":"推荐理由(20字内)","sec":"所属赛道"}}
      (推荐5只精选标的)
    ]
  }}
}}

要求：①top3标题加对应emoji ②b字段简洁有数据支撑 ③sectors覆盖六氟化钨、商业航天、CPO、MLCC、PCB、低空、机器人等重点赛道 ④只用中文 ⑤严格JSON格式"""
    return prompt

def main():
    if not API_KEY:
        print('WARNING: DEEPSEEK_API_KEY not set. Add it to GitHub Secrets.')
        return

    d = load_data()
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today = cst.strftime('%Y-%m-%d')

    prompt = build_prompt(d)
    result = call_ai(prompt, max_tokens=2500)
    if not result:
        return

    # Merge AI output into data.json
    if 'cycle' in result:
        d['recap']['cycle'] = result['cycle']
        print(f"Cycle: {result['cycle'].get('phase','?')}")

    if 'sectors' in result and result['sectors']:
        d['sectors'] = result['sectors']
        print(f"Sectors: {len(result['sectors'])} signals")

    if 'briefing' in result:
        b = result['briefing']
        if b.get('top3'):
            # Archive old briefing
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
            print(f"Briefing: {len(b['top3'])} top3, {len(b.get('picks',[]))} picks")

        if b.get('picks'):
            d['picks'] = b['picks']

    d['updated'] = cst.strftime('%Y-%m-%d %H:%M CST')
    d['nextSentinel'] = '今日 17:00 收盘雷达' if cst.hour < 15 else '明日 9:00 早盘哨兵'

    save_data(d)
    print(f'Sentinel scan complete: {cst.strftime("%H:%M")}')

if __name__ == '__main__':
    main()
