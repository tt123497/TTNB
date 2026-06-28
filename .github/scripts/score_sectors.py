#!/usr/bin/env python3
"""
Auto sector signal scorer — replaces manual Claude judgment.
Runs every 5 min via market-update.yml (after fetch_data.py + fetch_news.py).

Scoring dimensions:
  1. Price momentum: EastMoney concept board avg gain% → mapped to our 63 sectors
  2. News heat: recent sector news count (from _newsSector feed)

Signal thresholds:
  major (🔥):  board avg ≥3%  OR  2+ news + price ≥2%
  good  (🟢):  board avg ≥1%  OR  has news + price ≥0%
  neutral (🟡): board avg ≥-1%
  negative (🔴): board avg < -1%
"""

import json, os, re, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

# ═══ EastMoney concept board → our EXACT 63 sector name ═══
EM_ALIAS = {
    '航天航空':'商业航天','航天军工':'商业航天','通用航空':'低空经济eVTOL',
    '低空经济':'低空经济eVTOL','飞行汽车':'低空经济eVTOL',
    '机器人概念':'人形机器人','人形机器人':'人形机器人','具身智能':'人形机器人',
    '光通信':'CPO/光模块','CPO概念':'CPO/光模块','光模块':'CPO/光模块',
    '光纤光缆':'光纤光缆','光纤概念':'光纤光缆',
    '半导体':'半导体设备','半导体概念':'半导体设备','芯片概念':'AI芯片',
    'AI芯片':'AI芯片','算力概念':'AI芯片',
    'PCB概念':'PCB/覆铜板','覆铜板':'PCB/覆铜板','印制电路板':'PCB/覆铜板',
    'MLCC概念':'MLCC电容','被动元件':'MLCC电容',
    '铜箔':'电子铜箔',
    '超导概念':'超导/核聚变','核聚变':'超导/核聚变',
    '碳纤维':'碳纤维',
    '固态电池':'固态电池',
    '存储芯片':'HBM/存储芯片','HBM':'HBM/存储芯片',
    '液冷概念':'液冷散热','液冷散热':'液冷散热',
    '钨概念':'钨稀土','稀土永磁':'稀土永磁','稀土概念':'稀土永磁',
    '小金属':'钼/小金属','稀缺资源':'钨稀土','有色金属':'铜铝有色',
    '玻璃基板':'玻璃基板TGV','TGV概念':'玻璃基板TGV',
    '先进封装':'先进封装CoWoS','Chiplet概念':'先进封装CoWoS',
    '半导体硅片':'半导体硅片','硅片':'半导体硅片',
    '光刻胶':'光刻胶',
    '半导体设备':'半导体设备','刻蚀概念':'半导体设备',
    '服务器概念':'AI服务器/超节点',
    '交换机概念':'交换机/网络',
    '数据中心':'数据中心/AIDC','AIDC':'数据中心/AIDC','东数西算':'数据中心/AIDC',
    '电源设备':'电源/DrMOS','DrMOS':'电源/DrMOS',
    '六氟化钨':'六氟化钨WF6','电子特气':'电子特气/工业气体','工业气体':'电子特气/工业气体',
    '培育钻石':'培育钻石/散热','金刚石概念':'培育钻石/散热',
    '6G概念':'6G/通信','5G概念':'6G/通信','通信设备':'6G/通信',
    '连接器概念':'连接器/铜连接','铜缆高速连接':'连接器/铜连接',
    '电子树脂':'电子树脂/PPE','PPE概念':'电子树脂/PPE',
    '空间计算':'空间计算/物理AI',
    '锂矿概念':'锂矿/盐湖提锂','盐湖提锂':'锂矿/盐湖提锂',
    '锂电池':'锂电池/电解液','电解液':'锂电池/电解液',
    '光伏设备':'光伏/太阳能','光伏概念':'光伏/太阳能',
    '风电设备':'风电','风能':'风电',
    '储能概念':'储能',
    '新能源车':'新能源汽车','汽车整车':'新能源汽车',
    '煤炭行业':'煤炭','煤化工':'煤炭',
    '黄金概念':'黄金/贵金属','贵金属':'黄金/贵金属',
    '铜缆高速连接':'铜铝有色','铝概念':'铜铝有色','铜概念':'铜铝有色',
    '化工原料':'化工','化学制品':'化工',
    '钢铁行业':'钢铁',
    '银行':'银行','券商概念':'券商','证券':'券商','保险':'保险',
    '房地产':'房地产开发','房地产开发概念':'房地产开发',
    '白酒':'白酒','酿酒行业':'白酒',
    '食品饮料':'食品饮料','乳业':'食品饮料','调味品概念':'食品饮料',
    '医药':'医药/CRO','CRO':'医药/CRO','创新药':'医药/CRO',
    '医疗器械概念':'医疗器械',
    '稀土永磁':'稀土永磁','永磁材料':'稀土永磁',
    '钼概念':'钼/小金属',
    '电子化学品':'电子特气/工业气体',
    '半导体靶材':'半导体靶材','靶材':'半导体靶材',
    'AI智能体':'AI应用/模型推理','人工智能':'AI应用/模型推理','大模型':'AI应用/模型推理',
    '核电':'核电/核能','核能核电':'核电/核能',
    '量子计算':'量子计算/量子科技','量子科技':'量子计算/量子科技',
    '卫星互联网':'卫星互联网/北斗','北斗导航':'卫星互联网/北斗',
    '特高压':'电网设备/特高压','智能电网':'电网设备/特高压',
    '电力行业':'火电/电力运营','火电':'火电/电力运营',
    'AI电力':'算电协同','算力电力':'算电协同',
    '算力租赁':'算力租赁/GPU云',
    'AI应用':'AI应用/模型推理',
    'AI眼镜':'AI眼镜/AR硬件','智能眼镜':'AI眼镜/AR硬件',
    '互联金融':'券商','参股期货':'券商',
    # Engineered/fallback
    '油价相关':'化工','石油行业':'化工',
    '中字头':'银行','破净股':'银行','高股息':'银行',
}


def fetch(url, retries=2):
    for i in range(retries):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urlopen(req, timeout=12) as r:
                return r.read().decode('utf-8', errors='replace')
        except:
            if i < retries - 1:
                time.sleep(2)
    return None


def get_board_prices():
    """Fetch all EastMoney concept boards with % change."""
    boards = {}
    for mkt in ['m:90+t:3', 'm:90+t:2']:
        text = fetch(
            f'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=300&po=1&np=1&fltt=2&invt=2'
            f'&fid=f3&fs={mkt}&fields=f2,f3,f12,f14'
        )
        if not text:
            continue
        try:
            for item in json.loads(text).get('data', {}).get('diff', []):
                name = item.get('f14', '')
                pct = item.get('f3', 0) or 0
                if name and name not in boards:
                    boards[name] = pct
        except:
            pass
        time.sleep(0.2)
    return boards


def map_board_to_sector(board_name):
    """Map EastMoney board name → our sector name using EM_ALIAS."""
    # Direct match
    if board_name in EM_ALIAS:
        return EM_ALIAS[board_name]
    # Substring match
    for em_name, our_name in EM_ALIAS.items():
        if our_name and (em_name in board_name or board_name in em_name):
            return our_name
    return None


def get_sector_definitions():
    """Return the canonical 63 sector names in display order."""
    return [
        # AI上游 · 核心器件
        'AI芯片','CPO/光模块','光纤光缆','连接器/铜连接',
        # AI上游 · 基础材料
        'PCB/覆铜板','MLCC电容','电子树脂/PPE','电子铜箔','HBM/存储芯片',
        # AI中游 · 基础设施
        'AI服务器/超节点','液冷散热','交换机/网络','电源/DrMOS','数据中心/AIDC',
        '算电协同','电网设备/特高压','算力租赁/GPU云','火电/电力运营',
        # 半导体全链
        '半导体设备','光刻胶','先进封装CoWoS','半导体硅片','半导体靶材',
        # 新兴材料
        '六氟化钨WF6','玻璃基板TGV','培育钻石/散热','超导/核聚变','稀土永磁','钼/小金属','碳纤维','电子特气/工业气体',
        # 前沿科技
        '人形机器人','商业航天','6G/通信','固态电池','低空经济eVTOL',
        '空间计算/物理AI','AI眼镜/AR硬件','AI应用/模型推理','核电/核能','量子计算/量子科技','卫星互联网/北斗',
        # 新能源
        '锂矿/盐湖提锂','锂电池/电解液','光伏/太阳能','风电','储能','新能源汽车',
        # 周期 · 资源
        '煤炭','黄金/贵金属','铜铝有色','化工','钢铁',
        # 金融 · 地产
        '银行','券商','保险','房地产开发',
        # 消费 · 医药
        '白酒','食品饮料','医药/CRO','医疗器械',
    ]


def count_sector_news(data):
    """Count recent sector news matching our keywords per sector."""
    news_items = data.get('_newsSector', [])
    if not news_items:
        return {}

    # Keyword → sector mapping
    kw_sector = {
        '六氟化钨': '六氟化钨WF6', 'WF6': '六氟化钨WF6', '钨矿': '钨稀土', '钨精矿': '钨稀土',
        '稀土': '稀土永磁', '永磁': '稀土永磁', '钕铁硼': '稀土永磁',
        '钼': '钼/小金属', '小金属': '钼/小金属',
        'AI芯片': 'AI芯片', 'GPU': 'AI芯片', '算力': '算力租赁/GPU云',
        'CPO': 'CPO/光模块', '硅光': 'CPO/光模块', '光模块': '光模块', '光芯片': '光模块',
        'PCB': 'PCB/覆铜板', '覆铜板': 'PCB/覆铜板',
        'MLCC': 'MLCC电容', '电容': 'MLCC电容', '被动元件': 'MLCC电容',
        '电子树脂': '电子树脂/PPE', 'PPE': '电子树脂/PPE',
        '铜箔': '电子铜箔', 'HVLP': '电子铜箔',
        '存储': 'HBM/存储芯片', 'HBM': 'HBM/存储芯片', '佰维': 'HBM/存储芯片', '江波龙': 'HBM/存储芯片',
        '长鑫': 'HBM/存储芯片', '长江存储': 'HBM/存储芯片',
        '液冷': '液冷散热', '散热': '液冷散热',
        '交换机': '交换机/网络',
        '服务器': 'AI服务器/超节点', '超节点': 'AI服务器/超节点',
        '数据中心': '数据中心/AIDC', 'AIDC': '数据中心/AIDC',
        '半导体': '半导体设备', '光刻胶': '光刻胶', '先进封装': '先进封装CoWoS', 'CoWoS': '先进封装CoWoS',
        '硅片': '半导体硅片', '靶材': '半导体靶材',
        '机器人': '人形机器人', 'Optimus': '人形机器人', '宇树': '人形机器人', '绿的谐波': '人形机器人',
        '拓普': '人形机器人', '三花': '人形机器人',
        'SpaceX': '商业航天', '商业航天': '商业航天', '千帆': '商业航天', '卫星': '商业航天', '星链': '商业航天',
        '固态电池': '固态电池',
        '低空经济': '低空经济eVTOL', 'eVTOL': '低空经济eVTOL', '飞行汽车': '低空经济eVTOL', '民航法': '低空经济eVTOL',
        '电网': '电网设备/特高压', '特高压': '电网设备/特高压',
        '火电': '火电/电力运营', '电力': '火电/电力运营',
        '风电': '风电', '光伏': '光伏/太阳能', '储能': '储能',
        '锂矿': '锂矿/盐湖提锂', '锂电池': '锂电池/电解液', '电解液': '锂电池/电解液',
        '新能源车': '新能源汽车',
        '煤炭': '煤炭', '黄金': '黄金/贵金属', '铜': '铜铝有色', '铝': '铜铝有色',
        '钢铁': '钢铁', '化工': '化工',
        '银行': '银行', '券商': '券商', '保险': '保险', '地产': '房地产开发', '房贷': '房地产开发',
        '白酒': '白酒', '茅台': '白酒', '五粮液': '白酒',
        '医药': '医药/CRO', 'CRO': '医药/CRO', '医疗器械': '医疗器械',
        '迈瑞': '医疗器械', '联影': '医疗器械',
        '核能': '核电/核能', '量子': '量子计算/量子科技',
        'AI眼镜': 'AI眼镜/AR硬件', '智能眼镜': 'AI眼镜/AR硬件',
        'AI智能体': 'AI应用/模型推理', '大模型': 'AI应用/模型推理', 'AI应用': 'AI应用/模型推理',
        '电弧炉': '钢铁', 'MDI': '化工', '电子特气': '电子特气/工业气体', '工业气体': '电子特气/工业气体',
        '碳纤维': '碳纤维', '超导': '超导/核聚变',
        '6G': '6G/通信',
    }

    counts = {}
    # Only count news from last 4 hours
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    for item in news_items[-200:]:  # last 200 items
        title = item.get('t', '')
        ts = item.get('ts', '')
        # Check recency
        if ts:
            try:
                t = datetime.fromisoformat(ts)
                if (cst - t).total_seconds() > 14400:  # 4 hours
                    continue
            except:
                pass

        matched = set()
        for kw, sec in kw_sector.items():
            if kw in title and sec not in matched:
                counts[sec] = counts.get(sec, 0) + 1
                matched.add(sec)

    return counts


def score_all():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)

    # Load data
    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                pass

    # 1. Fetch board prices
    boards = get_board_prices()

    # 2. Aggregate to our sectors
    sector_prices = {}  # {sector: [pct, pct, ...]}
    for bname, pct in boards.items():
        sec = map_board_to_sector(bname)
        if sec:
            sector_prices.setdefault(sec, []).append(pct)

    # 3. Count news per sector
    sector_news = count_sector_news(data)

    # 4. Score each sector
    all_sectors = get_sector_definitions()
    results = []

    for sec in all_sectors:
        prices = sector_prices.get(sec, [])
        news_count = sector_news.get(sec, 0)

        # Compute avg gain from matching boards
        if prices:
            avg_gain = round(sum(prices) / len(prices), 2)
            max_gain = round(max(prices), 2)
        else:
            avg_gain = 0
            max_gain = 0

        # Signal determination
        if prices:
            if avg_gain >= 3.0:
                sig = 'major'
            elif avg_gain >= 1.0:
                sig = 'good'
            elif avg_gain >= -1.0:
                sig = 'neutral'
            else:
                sig = 'negative'
        else:
            # No matching board found — fallback to news
            if news_count >= 2:
                sig = 'good'
            elif news_count >= 1:
                sig = 'neutral'
            else:
                sig = 'neutral'

        # Boost: news + positive price
        if news_count >= 2 and avg_gain >= 2.0 and sig == 'good':
            sig = 'major'

        # Generate message
        if sig == 'major':
            if news_count >= 2:
                msg = f"板块均涨{avg_gain:+.1f}%，{news_count}条最新消息，市场关注度极高。"
            else:
                msg = f"板块均涨{avg_gain:+.1f}%，资金大幅流入，走势强劲。"
        elif sig == 'good':
            if news_count >= 1:
                msg = f"板块均涨{avg_gain:+.1f}%，{news_count}条相关消息，表现稳健。"
            elif avg_gain > 0:
                msg = f"板块均涨{avg_gain:+.1f}%，温和上行。"
            else:
                msg = f"板块均涨{avg_gain:+.1f}%，基本面支撑，等待催化。"
        elif sig == 'negative':
            msg = f"板块均涨{avg_gain:+.1f}%，短期承压，关注后续修复。"
        else:
            if news_count >= 1:
                msg = f"板块均涨{avg_gain:+.1f}%，方向不明朗，{news_count}条消息待发酵。"
            else:
                msg = f"板块均涨{avg_gain:+.1f}%，横盘整理，等待催化。"

        results.append({
            "name": sec,
            "sig": sig,
            "msg": msg,
            "u": ""
        })

    # 5. Write dual-path
    data["sectors"] = results
    data["updated"] = cst.strftime('%Y-%m-%d %H:%M CST')

    if "briefing" not in data:
        data["briefing"] = {}
    data["briefing"]["sectors"] = results
    data["briefing"]["updated"] = data["updated"]

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    sigs = {}
    for r in results:
        sigs[r['sig']] = sigs.get(r['sig'], 0) + 1
    print(f"[score_sectors] {len(results)} sectors scored | boards: {len(boards)} | {sigs}")
    return results


if __name__ == '__main__':
    score_all()
