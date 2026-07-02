#!/usr/bin/env python3
"""
signal_monitor.py — 全市场异动信号监控

扫描所有新闻，用规则引擎过滤噪音，关联到板块和标的。
输出分级信号，喂给 sector_factors.py 更新因子状态。

信号级别: high(重大) / medium(中等) / low(一般)
信号类型: price_change / announcement / policy / block_trade / institutional / breakout / etc.
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
TODAY = CST.strftime('%Y-%m-%d')

# ═══════════════════════════════════════════════════
# 规则引擎：关键词过滤
# ═══════════════════════════════════════════════════

# 必须命中至少一个产业关键词
HIT_KEYWORDS = {
    'price_up': ['涨价', '提价', '上调', '价格上涨', '价格调整', 'ASP提升', '创历史新高'],
    'price_down': ['降价', '下调', '价格下跌', '暴跌', '价格战'],
    'capacity': ['投产', '量产', '扩产', '达产', '满产', '停产', '减产', '复产', '检修', '产能'],
    'earnings': ['业绩预告', '业绩快报', '超预期', '扭亏', '预增', '预减', '预亏', '大幅增长', '大幅下降'],
    'supply_chain': ['断供', '替代', '国产化', '突破', '验证', '导入', '认证', '合格供应商'],
    'policy': ['补贴', '免税', '审批', '纳入', '规划', '专项', '政策', '条例', '征求意见'],
    'capital': ['定增', '回购', '增持', '减持', '解禁', '收购', '并购', '重组', '入股'],
    'order': ['中标', '签订', '合同', '订单', '框架协议', '战略合作'],
    'tech': ['突破', '首发', '首发', '验证通过', '量产', '试产', '流片', 'tape-out'],
}

# 噪音关键词 - 直接丢弃
NOISE_KEYWORDS = [
    '演唱会', '世界杯', '欧洲杯', '奥运', '亚运', '决赛', '半决赛', '裁判', '球员', '教练',
    '明星', '演员', '歌手', '网红', '电视剧', '综艺', '选秀',
    '高考', '中考', '录取', '开学',
    '地震', '海啸', '洪水', '泥石流', '台风', '救灾', '遇难',
]

# 重大信号关键词 - 直接升级为high
HIGH_PRIORITY = [
    '停产', '断供', '制裁', '实体清单', '出口管制', '永久停产',
    '量产', '投产', '达产', ' breakthrough', '突破',
    '涨价', '集体涨价', '大幅涨价',
    '业绩超预期', '大幅增长', '扭亏',
    '政策', '条例', '规划', '专项',
    '增持', '回购', '举牌',
]

# ═══════════════════════════════════════════════════
# 板块关联匹配
# ═══════════════════════════════════════════════════

SECTOR_KEYWORDS = {
    'AI芯片': ['AI芯片', '寒武纪', '海光', '景嘉微', 'GPU', '算力芯片'],
    'CPO/光模块': ['CPO', '光模块', '硅光', '中际旭创', '新易盛', '光迅科技', '800G', '1.6T'],
    'PCB/覆铜板': ['PCB', '覆铜板', '印制电路', '沪电股份', '深南电路', '生益科技'],
    '半导体设备': ['半导体设备', '北方华创', '中微公司', '拓荆科技', '盛美上海'],
    '半导体硅片': ['硅片', '沪硅产业', 'TCL中环', '西安奕材'],
    '半导体靶材': ['靶材', '江丰电子', '阿石创', '有研新材'],
    '光刻胶': ['光刻胶', '彤程新材', '上海新阳', '南大光电'],
    'HBM/存储芯片': ['HBM', '存储芯片', 'NAND', 'DRAM', '兆易创新', '江波龙'],
    '先进封装CoWoS': ['先进封装', 'CoWoS', 'Chiplet', '长电科技', '通富微电'],
    '电子特气/工业气体': ['电子特气', '工业气体', '中船特气', '华特气体', '雅克科技', '六氟化钨'],
    '电子树脂/PPE': ['电子树脂', 'PPE', '圣泉集团', '东材科技'],
    '电子铜箔': ['铜箔', '嘉元科技', '诺德股份'],
    'MLCC电容': ['MLCC', '被动元件', '电容', '风华高科', '三环集团'],
    '液冷散热': ['液冷', '散热', '英维克', '曙光数创'],
    '交换机/网络': ['交换机', '锐捷网络', '星网锐捷', '中兴通讯'],
    '电源/DrMOS': ['DrMOS', '电源管理', '杰华特', '晶丰明源'],
    '数据中心/AIDC': ['数据中心', 'AIDC', 'IDC', '光环新网'],
    '钨稀土/小金属': ['钨', '稀土', '钼', '洛阳钼业', '金钼股份', '厦门钨业', '翔鹭钨业'],
    '黄金/贵金属': ['黄金', '金价', '紫金矿业', '山东黄金', '赤峰黄金'],
    '铜铝有色': ['铜', '铝', '有色', '紫金矿业', '中国铝业', '洛阳钼业'],
    '人形机器人': ['人形机器人', '机器人', 'Optimus', '绿的谐波', '拓普集团', '汇川技术'],
    '消费电子/AI硬件': ['苹果', 'iPhone', '立讯精密', '歌尔股份', '蓝思科技', 'AI手机', 'AI眼镜', 'AR'],
    'AI应用/模型推理': ['AI应用', '大模型', 'DeepSeek', '科大讯飞', 'GPT', 'Agent'],
    '创新药/CXO': ['创新药', 'CXO', '药明康德', '恒瑞医药', '百济神州', 'ADC', 'License'],
    '医药/CRO': ['CRO', '药明康德', '康龙化成', '泰格医药'],
    '商业航天': ['商业航天', 'SpaceX', '千帆星座', '航天动力', '上海沪工'],
    '低空经济eVTOL': ['低空经济', 'eVTOL', '万丰奥威', '中信海直'],
    '稳定币/RWA/跨境支付': ['稳定币', 'RWA', '数字货币', '数字人民币', '区块链', '跨境支付', 'CIPS', '楚天龙', '四方精创'],
    '模拟芯片/功率半导体': ['模拟芯片', '功率半导体', 'IGBT', 'SiC', 'GaN', '圣邦股份', '思瑞浦', '士兰微', '斯达半导'],
    '猪肉/养殖': ['猪肉', '生猪', '猪价', '牧原股份', '温氏股份', '能繁母猪', '养殖'],
    '光伏/太阳能': ['光伏', '太阳能', '隆基绿能', '通威股份', '晶澳科技', 'HJT', 'TOPCon'],
    '锂电池/电解液': ['锂电池', '电解液', '宁德时代', '亿纬锂能', '天赐材料'],
    '固态电池': ['固态电池', '硫化物', '氧化物'],
    '新能源汽车': ['新能源车', '比亚迪', '赛力斯', '宁德时代', '渗透率'],
    '风电': ['风电', '金风科技', '明阳智能', '海上风电'],
    '储能': ['储能', '阳光电源', '宁德时代', '虚拟电厂'],
    '保险': ['保险', '中国人寿', '中国平安', '新华保险'],
    '券商': ['券商', '证券', '东方财富', '中信证券', '牛市'],
    '银行': ['银行', '降息', 'LPR', '招商银行', '工商银行'],
    '房地产': ['房地产', '地产', '万科', '保利', '限购'],
    '白酒': ['白酒', '茅台', '五粮液', '泸州老窖', '批价'],
    '煤炭': ['煤炭', '动力煤', '焦煤', '中国神华'],
    '钢铁': ['钢铁', '宝钢', '限产', '铁矿石'],
    '6G/通信': ['6G', '通信', '烽火通信', '中兴通讯'],
    '卫星互联网/北斗': ['卫星互联网', '北斗', '低轨卫星', '中国卫星'],
    '核电/核能': ['核电', '核能', '中国核电', '中国广核', 'SMR', '小型堆'],
    '量子计算/量子科技': ['量子', '国盾量子', '量子计算'],
}

# ═══════════════════════════════════════════════════
# 信号生成引擎
# ═══════════════════════════════════════════════════

def is_noise(title):
    """检查是否是噪音"""
    for kw in NOISE_KEYWORDS:
        if kw in title:
            return True
    return False

def match_hit_keywords(title):
    """匹配产业关键词，返回信号类型"""
    signals = []
    for sig_type, keywords in HIT_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                signals.append({'type': sig_type, 'keyword': kw})
                break
    return signals

def match_sectors(title):
    """匹配板块，返回关联的赛道列表"""
    matched = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                matched.append(sector)
                break
    return matched

def determine_level(title, hit_signals):
    """确定信号级别"""
    for hp in HIGH_PRIORITY:
        if hp in title:
            return 'high'
    if len(hit_signals) >= 2:
        return 'medium'
    if hit_signals:
        return 'low'
    return 'low'

def generate_signal(news_item):
    """从新闻生成结构化信号"""
    title = news_item.get('t', '')
    if not title or is_noise(title):
        return None

    hits = match_hit_keywords(title)
    if not hits:
        return None  # 没命中产业关键词，丢弃

    sectors = match_sectors(title)
    if not sectors:
        return None  # 无法关联到板块，丢弃

    level = determine_level(title, hits)

    # 信号类型描述
    type_map = {
        'price_up': '产品涨价',
        'price_down': '产品降价',
        'capacity': '产能变化',
        'earnings': '业绩公告',
        'supply_chain': '供应链',
        'policy': '政策',
        'capital': '资本运作',
        'order': '订单中标',
        'tech': '技术突破',
    }

    signal = {
        'level': level,
        'type': hits[0]['type'],
        'type_label': type_map.get(hits[0]['type'], hits[0]['type']),
        'time': news_item.get('time', ''),
        'title': title[:120],
        'sectors': sectors,
        'keyword': hits[0]['keyword'],
        'url': news_item.get('u', ''),
        'src': news_item.get('src', ''),
    }
    return signal

def collect_news(d, project_dir='.'):
    """收集所有新闻源（data.json + news.json）"""
    news = []
    # data.json
    for n in d.get('_newsSector', []):
        news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('time', ''), 'src': n.get('src', '')})
    for n in d.get('_newsMarket', []):
        news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('time', ''), 'src': n.get('src', '')})
    gn = d.get('globalNews', {})
    for n in gn.get('headlines', []):
        news.append({'t': n.get('t', ''), 'u': n.get('u', ''), 'time': n.get('ts', ''), 'src': 'global'})
    # news.json (独立新闻文件，可能data.json的快讯已被覆盖)
    news_json_path = os.path.join(project_dir, 'news.json')
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

def main():
    print(f"=== Signal Monitor {CST.strftime('%Y-%m-%d %H:%M CST')} ===")

    if not os.path.exists(DATA_PATH):
        print("  ERROR: data.json not found")
        return

    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        d = json.load(f)

    project_dir = os.path.dirname(DATA_PATH)
    news = collect_news(d, project_dir)
    print(f"  News collected: {len(news)}")

    # 生成信号
    signals = []
    seen_titles = set()
    for item in news:
        sig = generate_signal(item)
        if sig and sig['title'] not in seen_titles:
            signals.append(sig)
            seen_titles.add(sig['title'])

    # 按级别排序
    level_order = {'high': 0, 'medium': 1, 'low': 2}
    signals.sort(key=lambda x: (level_order.get(x['level'], 3), x.get('time', '')), reverse=True)

    # 保留历史信号（7天）
    old_signals = d.get('_signalHistory', [])
    cutoff = CST - timedelta(days=7)
    history = []
    for s in old_signals:
        try:
            s_time = datetime.strptime(s.get('time', '')[:10], '%Y-%m-%d')
            if s_time >= cutoff:
                history.append(s)
        except:
            pass

    # 合并新信号到历史（去重）
    history_titles = {s.get('title', '') for s in history}
    for s in signals:
        if s['title'] not in history_titles:
            s['detected'] = CST.strftime('%Y-%m-%d %H:%M')
            history.append(s)
            history_titles.add(s['title'])

    # 限制历史最多200条
    history = history[-200:]

    # 统计
    high_count = sum(1 for s in signals if s['level'] == 'high')
    med_count = sum(1 for s in signals if s['level'] == 'medium')
    low_count = sum(1 for s in signals if s['level'] == 'low')

    d['_marketSignals'] = signals  # 本次扫描的信号
    d['_signalHistory'] = history   # 7天历史

    # 保存
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)

    print(f"  Signals generated: {len(signals)} (high={high_count} medium={med_count} low={low_count})")
    print(f"  History retained: {len(history)}")
    print(f"  Done → {DATA_PATH}")

if __name__ == '__main__':
    main()
