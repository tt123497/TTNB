#!/usr/bin/env python3
"""
sector_factors.py — 赛道催化剂追踪引擎

每个赛道跟踪3-5个关键因子，因子状态变化 = 预判信号。
因子和板块的对应关系基于产业链逻辑（确定性），不靠AI判断。

输出: data.json['sectorFactors'] = {
  "AI芯片": {
    "factors": [
      {"name":"国产替代进度","status":"加速","value":"寒武纪Q2扭亏","changed":"2026-07-02","impact":"bullish"},
      {"name":"美国出口管制","status":"收紧","value":"新一轮限制","changed":"2026-06-28","impact":"bearish"},
      ...
    ],
    "score": +2,  # 正向因子数-负向因子数
    "updated": "2026-07-02 23:00 CST"
  }
}
"""
import json, os, re
from datetime import datetime, timezone, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
# 从.github/scripts/往上两级到项目根目录
PROJECT_DIR = os.path.dirname(os.path.dirname(DIR)) if '.github' in DIR else DIR
# 也检查上级目录
if not os.path.exists(os.path.join(PROJECT_DIR, 'data.json')):
    for candidate in [PROJECT_DIR, os.path.dirname(DIR), DIR, 'D:/projects/market-dashboard']:
        if os.path.exists(os.path.join(candidate, 'data.json')):
            PROJECT_DIR = candidate
            break
DATA_PATH = os.path.join(PROJECT_DIR, 'data.json')

CST = datetime.now(timezone.utc) + timedelta(hours=8)

# ═══════════════════════════════════════════════════
# 赛道因子定义 — 每个赛道3-5个关键因子
# 因子状态: bullish(正向) / bearish(负向) / neutral(中性) / watch(观察中)
# ═══════════════════════════════════════════════════

SECTOR_FACTORS = {
    "AI芯片": [
        {"name": "国产替代进度", "keywords": ["国产替代", "国产化率", "自主可控", "寒武纪", "海光", "景嘉微"], "default": "bullish"},
        {"name": "美国出口管制", "keywords": ["出口管制", "实体清单", "禁运", "制裁", "限制"], "default": "bearish"},
        {"name": "AI算力需求", "keywords": ["算力", "数据中心", "大模型", "训练", "推理", "GPU"], "default": "bullish"},
        {"name": "芯片涨价", "keywords": ["涨价", "提价", "价格上调", "ASP提升"], "default": "neutral"},
    ],
    "CPO/光模块": [
        {"name": "英伟达需求", "keywords": ["英伟达", "黄仁勋", "GPU", "数据中心", "800G", "1.6T"], "default": "bullish"},
        {"name": "产能扩张", "keywords": ["扩产", "产能", "量产", "交付", "订单"], "default": "bullish"},
        {"name": "技术迭代", "keywords": ["CPO", "硅光", "共封装", "薄膜铌酸锂", "LPO"], "default": "bullish"},
        {"name": "海外竞争", "keywords": ["博通", "Intel", "Marvell", "竞争", "份额"], "default": "neutral"},
    ],
    "PCB/覆铜板": [
        {"name": "AI服务器需求", "keywords": ["AI服务器", "算力", "数据中心", "HDI", "高多层"], "default": "bullish"},
        {"name": "上游涨价", "keywords": ["铜箔", "树脂", "玻纤", "涨价", "覆铜板"], "default": "bullish"},
        {"name": "产能利用率", "keywords": ["产能", "稼动率", "订单", "满产"], "default": "bullish"},
    ],
    "半导体设备": [
        {"name": "国产替代", "keywords": ["国产替代", "国产化", "北方华创", "中微", "拓荆"], "default": "bullish"},
        {"name": "晶圆厂资本开支", "keywords": ["资本开支", "设备采购", "招标", "中芯", "华虹", "长鑫"], "default": "bullish"},
        {"name": "美国制裁", "keywords": ["制裁", "出口管制", "实体清单", "禁运"], "default": "bearish"},
    ],
    "存储芯片/HBM": [
        {"name": "产品价格", "keywords": ["涨价", "提价", "NAND", "DRAM", "合约价"], "default": "bullish"},
        {"name": "AI需求拉动", "keywords": ["HBM", "AI", "算力", "数据中心", "GPU"], "default": "bullish"},
        {"name": "库存周期", "keywords": ["库存", "去库存", "补库存", "周期"], "default": "neutral"},
    ],
    "稳定币/RWA/跨境支付": [
        {"name": "政策进度", "keywords": ["稳定币条例", "监管", "牌照", "合规", "数字货币"], "default": "bullish"},
        {"name": "RWA落地", "keywords": ["RWA", "通证化", "代币化", "贝莱德", "BUIDL"], "default": "bullish"},
        {"name": "数字人民币", "keywords": ["数字人民币", "DCEP", "试点", "CIPS", "跨境"], "default": "bullish"},
    ],
    "模拟芯片/功率半导体": [
        {"name": "涨价周期", "keywords": ["涨价", "提价", "价格调整", "ASP"], "default": "bullish"},
        {"name": "国产替代", "keywords": ["国产替代", "国产化", "圣邦", "思瑞浦", "士兰微"], "default": "bullish"},
        {"name": "下游需求", "keywords": ["汽车", "工业", "光伏", "消费电子", "需求"], "default": "neutral"},
    ],
    "猪肉/养殖": [
        {"name": "猪价", "keywords": ["猪价", "生猪价格", "猪肉价格"], "default": "bullish"},
        {"name": "能繁母猪存栏", "keywords": ["能繁母猪", "存栏", "去化", "产能"], "default": "bullish"},
        {"name": "饲料成本", "keywords": ["玉米", "豆粕", "饲料", "成本"], "default": "neutral"},
    ],
    "钨稀土/小金属": [
        {"name": "产品价格", "keywords": ["六氟化钨", "钨", "稀土", "涨价", "价格"], "default": "bullish"},
        {"name": "供给端变化", "keywords": ["停产", "减产", "出口管制", "战略矿产"], "default": "bullish"},
        {"name": "政策催化", "keywords": ["矿产法", "战略矿产", "收储", "配额"], "default": "bullish"},
    ],
    "黄金/贵金属": [
        {"name": "金价走势", "keywords": ["金价", "黄金", "避险", "实际利率"], "default": "bullish"},
        {"name": "地缘风险", "keywords": ["地缘", "冲突", "战争", "避险"], "default": "bullish"},
        {"name": "美联储政策", "keywords": ["美联储", "降息", "加息", "FOMC", "利率"], "default": "neutral"},
    ],
    "人形机器人": [
        {"name": "量产进度", "keywords": ["量产", "投产", "特斯拉", "Optimus", " Figure"], "default": "bullish"},
        {"name": "技术突破", "keywords": ["突破", "灵巧手", "减速器", "伺服", "运控"], "default": "bullish"},
        {"name": "政策支持", "keywords": ["政策", "专项", "补贴", "标准"], "default": "neutral"},
    ],
    "消费电子/AI硬件": [
        {"name": "苹果AI催化", "keywords": ["苹果", "AI手机", "换机", "iPhone", "Vision Pro"], "default": "bullish"},
        {"name": "AI眼镜进展", "keywords": ["AI眼镜", "AR", "MicroLED", "光波导", "雷鸟"], "default": "bullish"},
        {"name": "出货量", "keywords": ["出货", "销量", "订单", "产能"], "default": "neutral"},
    ],
    "创新药/CXO": [
        {"name": "管线进展", "keywords": ["临床", "获批", "上市", "NDA", "BLA", "适应症"], "default": "bullish"},
        {"name": "海外授权", "keywords": ["授权", "License", "出海", "海外", "ADC"], "default": "bullish"},
        {"name": "集采影响", "keywords": ["集采", "采购", "降价", "医保"], "default": "bearish"},
    ],
    "商业航天": [
        {"name": "发射进度", "keywords": ["发射", "千帆", "星链", "星座", "组网"], "default": "bullish"},
        {"name": "可回收技术", "keywords": ["回收", "复用", "朱雀", "火箭"], "default": "bullish"},
        {"name": "政策支持", "keywords": ["政策", "专项", "规划", "航天"], "default": "neutral"},
    ],
    "低空经济eVTOL": [
        {"name": "适航认证", "keywords": ["适航", "认证", "取证", "型号"], "default": "bullish"},
        {"name": "订单进展", "keywords": ["订单", "意向", "采购", "合同"], "default": "bullish"},
        {"name": "空域开放", "keywords": ["空域", "航线", "低空", "管理"], "default": "neutral"},
    ],
}

# ═══════════════════════════════════════════════════
# 信号匹配引擎
# ═══════════════════════════════════════════════════

def load_data():
    if not os.path.exists(DATA_PATH):
        return {}
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_data(d):
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)

def get_all_news(d):
    """收集所有新闻源（data.json + news.json）"""
    news = []
    for n in d.get('_newsSector', []):
        news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('time', ''), 'src': n.get('src', '')})
    for n in d.get('_newsMarket', []):
        news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('time', ''), 'src': n.get('src', '')})
    gn = d.get('globalNews', {})
    for n in gn.get('headlines', []):
        news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('ts', ''), 'src': 'global'})
    for n in d.get('_signalHistory', []):
        news.append({'t': n.get('title', ''), 'u': n.get('url', ''), 'time': n.get('time', ''), 'src': n.get('src', '')})
    # news.json
    news_json_path = os.path.join(os.path.dirname(DATA_PATH), 'news.json')
    if os.path.exists(news_json_path):
        try:
            with open(news_json_path, 'r', encoding='utf-8') as f:
                nj = json.load(f)
            for n in nj.get('_newsSector', []):
                news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('time', ''), 'src': n.get('src', 'news_json')})
            for n in nj.get('_newsMarket', []):
                news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('time', ''), 'src': n.get('src', 'news_json')})
            gnj = nj.get('globalNews', {})
            for n in gnj.get('headlines', []):
                news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('ts', ''), 'src': 'news_json_global'})
        except:
            pass
    return news

def match_sector(title, sector_name, factors):
    """检查标题是否匹配某赛道的因子关键词"""
    matched_factors = []
    for f in factors:
        for kw in f['keywords']:
            if kw in title:
                matched_factors.append({
                    'factor': f['name'],
                    'keyword': kw,
                    'impact': f['default'],
                    'title': title
                })
                break
    return matched_factors

def analyze_sector_factors(d):
    """
    分析所有赛道的因子状态
    返回: {sector_name: {factors: [...], score: int, updated: str}}
    """
    news = get_all_news(d)
    print(f"  News to scan: {len(news)}")

    # 获取赛道列表
    sector_names = set()
    st = d.get('sectorTags', {})
    sector_names.update(st.keys())
    sfs = d.get('sectorFixedStocks', {})
    sector_names.update(sfs.keys())

    result = {}
    total_signals = 0

    for sector_name, factor_defs in SECTOR_FACTORS.items():
        if sector_name not in sector_names:
            # 尝试模糊匹配
            matched = [s for s in sector_names if sector_name.split('/')[0] in s or s.split('/')[0] in sector_name]
            if not matched:
                continue
            sector_name = matched[0]

        # 扫描新闻匹配因子
        factor_updates = []
        for news_item in news:
            title = news_item['t']
            if not title:
                continue
            matches = match_sector(title, sector_name, factor_defs)
            for m in matches:
                factor_updates.append({
                    'name': m['factor'],
                    'status': 'active' if m['impact'] in ('bullish',) else 'warning' if m['impact'] == 'bearish' else 'neutral',
                    'value': title[:80],
                    'impact': m['impact'],
                    'keyword': m['keyword'],
                    'changed': news_item.get('time', CST.strftime('%Y-%m-%d')),
                    'url': news_item.get('u', '')
                })
                total_signals += 1

        # 去重：同一因子只保留最新一条
        seen = {}
        for u in factor_updates:
            key = u['name']
            if key not in seen or u['changed'] > seen[key]['changed']:
                seen[key] = u

        # 合并：未匹配到新闻的因子用默认状态
        factors = []
        score = 0
        for fdef in factor_defs:
            fname = fdef['name']
            if fname in seen:
                fu = seen[fname]
                factors.append(fu)
                if fu['impact'] == 'bullish':
                    score += 1
                elif fu['impact'] == 'bearish':
                    score -= 1
            else:
                factors.append({
                    'name': fname,
                    'status': 'stable' if fdef['default'] == 'bullish' else 'watch',
                    'value': '',
                    'impact': fdef['default'],
                    'changed': '',
                    'url': ''
                })
                if fdef['default'] == 'bullish':
                    score += 1
                elif fdef['default'] == 'bearish':
                    score -= 1

        result[sector_name] = {
            'factors': factors,
            'score': score,
            'updated': CST.strftime('%Y-%m-%d %H:%M CST'),
            'signal_count': len(seen)
        }

    print(f"  Sectors analyzed: {len(result)}")
    print(f"  Total factor signals: {total_signals}")
    return result

def main():
    print(f"=== Sector Factors Update {CST.strftime('%Y-%m-%d %H:%M CST')} ===")
    d = load_data()
    if not d:
        print("  ERROR: data.json not found or empty")
        return

    sector_factors = analyze_sector_factors(d)

    # 保存到data.json
    d['sectorFactors'] = sector_factors

    # 生成因子变化预警（score变化或新信号）
    old_factors = d.get('_sectorFactorsOld', {})
    alerts = []
    for sector, info in sector_factors.items():
        old_info = old_factors.get(sector, {})
        old_score = old_info.get('score', 0)
        new_score = info['score']
        if new_score != old_score and old_score != 0:
            direction = '↑' if new_score > old_score else '↓'
            alerts.append({
                'sector': sector,
                'old_score': old_score,
                'new_score': new_score,
                'direction': direction,
                'time': CST.strftime('%Y-%m-%d %H:%M'),
                'msg': f"{sector} 因子评分{direction} {abs(new_score-old_score)} (新信号)"
            })
        # 检查新因子信号
        old_signal_count = old_info.get('signal_count', 0)
        if info['signal_count'] > old_signal_count:
            for f in info['factors']:
                if f.get('changed') == CST.strftime('%Y-%m-%d'):
                    alerts.append({
                        'sector': sector,
                        'factor': f['name'],
                        'impact': f['impact'],
                        'value': f['value'],
                        'time': CST.strftime('%Y-%m-%d %H:%M'),
                        'msg': f"{sector}·{f['name']} 更新: {f['value'][:50]}"
                    })

    d['_sectorFactorAlerts'] = alerts
    d['_sectorFactorsOld'] = sector_factors  # 保存为下次的old

    save_data(d)
    print(f"  Alerts: {len(alerts)}")
    print(f"  Done → {DATA_PATH}")

if __name__ == '__main__':
    main()
