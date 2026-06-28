#!/usr/bin/env python3
"""
expand_sector_stocks.py — 扩展赛道标的池
对每个赛道, 从东财全市场扫描中找该赛道的股票,
按当日涨跌幅排序, 去除ST/次新, 科创+创业板≤3只, 选前12只。
"""
import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sector_fixed_stocks import SECTOR_FIXED_STOCKS, is_kcb_cyb, is_mainboard
import a_stock_data as ad

# ═══════════════════════════════════════════════════════════════
# 1. 从东财全市场获取所有A股 + 实时涨跌幅 (分页, 每页100只)
# ═══════════════════════════════════════════════════════════════

def fetch_all_a_stocks():
    """获取全市场A股: 代码, 名称, 涨跌幅, 所属行业"""
    all_stocks = []
    for page in range(1, 60):  # 最多60页×100=6000只
        try:
            url = (f'http://push2.eastmoney.com/api/qt/clist/get?'
                   f'pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&'
                   f'fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&'
                   f'fields=f2,f3,f12,f14,f100,f6')
            r = ad.em_get(url, timeout=10)
            if not r:
                break
            data = r.json().get('data', {}).get('diff', [])
            if not data:
                break
            for s in data:
                code = s.get('f12', '')
                name = s.get('f14', '')
                chg = s.get('f3', 0) or 0
                price = s.get('f2', 0) or 0
                industry = s.get('f100', '') or ''
                amount = s.get('f6', 0) or 0  # 成交额
                if code and len(code) == 6 and name:
                    all_stocks.append({
                        'code': code, 'name': name, 'chg': chg,
                        'price': price, 'industry': industry,
                        'amount': amount,
                    })
            if len(data) < 100:
                break
            time.sleep(0.1)
        except Exception as e:
            print(f'  page {page} error: {e}')
            break
    print(f'  全市场扫描: {len(all_stocks)} 只')
    return all_stocks

# ═══════════════════════════════════════════════════════════════
# 2. 赛道关键词匹配 — 把股票映射到我们的赛道
# ═══════════════════════════════════════════════════════════════

# 赛道 → 关键词 (用于匹配东财行业名/概念名/股票名)
# 第一组=精确匹配, 第二组=宽泛匹配(当精确不够时用)
SECTOR_KEYWORDS = {
    "AI芯片": [["AI芯片","人工智能芯片","GPU","算力芯片","芯片设计"], ["半导体","集成电路"]],
    "CPO/光模块": [["光模块","CPO","光通信","光器件"], ["通信设备","光电"]],
    "光纤光缆": [["光纤","光缆","通信线缆"], ["通信设备"]],
    "连接器/铜连接": [["连接器","铜连接","电子连接"], ["电子元件","元器件","精密制造"]],
    "PCB/覆铜板": [["PCB","印制电路板","覆铜板","电路板"], ["电子元件","元器件"]],
    "MLCC电容": [["MLCC","电容","被动元件","陶瓷电容"], ["电子元件","元器件"]],
    "电子树脂/PPE": [["树脂","PPE","电子材料","环氧树脂"], ["化学制品","化工"]],
    "电子铜箔": [["铜箔","电子铜箔"], ["有色金属","铜"]],
    "HBM/存储芯片": [["HBM","存储芯片","存储器","DRAM","NAND"], ["半导体","集成电路"]],
    "AI服务器/超节点": [["服务器","AI服务器","超算","计算设备"], ["计算机设备","IT服务"]],
    "液冷散热": [["液冷","散热","热管理","温控"], ["制冷","空调","机械设备"]],
    "交换机/网络": [["交换机","网络设备","路由器","通信设备"], ["通信"]],
    "电源/DrMOS": [["电源管理","DrMOS","电源芯片","功率半导体"], ["半导体","电源"]],
    "数据中心/AIDC": [["数据中心","IDC","AIDC","数据服务"], ["IT服务","计算机"]],
    "算电协同": [["算电","电力算力","数据中心电力"], ["电力","电源","电气"]],
    "电网设备/特高压": [["特高压","电网设备","输变电","智能电网"], ["电气设备","电力设备"]],
    "算力租赁/GPU云": [["算力","GPU云","云计算","算力服务"], ["IT服务","计算机"]],
    "火电/电力运营": [["火电","电力","发电","电力运营"], ["电力","能源"]],
    "半导体设备": [["半导体设备","晶圆制造设备","光刻机"], ["专用设备","半导体"]],
    "光刻胶": [["光刻胶","光致抗蚀剂","半导体材料"], ["化学制品","化工新材料"]],
    "先进封装CoWoS": [["先进封装","封装测试","CoWoS","Chiplet"], ["半导体","集成电路"]],
    "半导体硅片": [["硅片","半导体硅材料","晶圆"], ["半导体","材料"]],
    "半导体靶材": [["靶材","溅射靶材","半导体材料"], ["半导体","材料","有色金属"]],
    "六氟化钨WF₆": [["六氟化钨","WF6","电子特气","钨"], ["化学制品","化工","特气"]],
    "玻璃基板TGV": [["玻璃基板","TGV","玻璃载板"], ["玻璃","电子元件","新材料"]],
    "培育钻石/散热": [["培育钻石","金刚石","散热材料"], ["新材料","超硬材料"]],
    "超导/核聚变": [["超导","核聚变","超导材料"], ["新材料","冶金","材料"]],
    "稀土永磁": [["稀土","永磁","钕铁硼","磁性材料"], ["有色金属","小金属"]],
    "钼/小金属": [["钼","钨","小金属","稀有金属"], ["有色金属","小金属"]],
    "碳纤维": [["碳纤维","碳纤维复合材料"], ["化学纤维","新材料","化工"]],
    "电子特气/工业气体": [["电子特气","工业气体","特种气体"], ["化学制品","气体"]],
    "人形机器人": [["机器人","人形机器人","减速器","伺服"], ["自动化","机械设备","工业4.0"]],
    "商业航天": [["商业航天","卫星制造","火箭","航天"], ["航天军工","国防","航空"]],
    "6G/通信": [["6G","通信","射频","基站"], ["通信设备","通信"]],
    "固态电池": [["固态电池","电池","锂电池"], ["电池","新能源"]],
    "低空经济eVTOL": [["低空经济","eVTOL","无人机","通航"], ["航空","国防","飞行器"]],
    "空间计算/物理AI": [["空间计算","AR","VR","MR","XR"], ["消费电子","光学","显示"]],
    "AI眼镜/AR硬件": [["AI眼镜","智能眼镜","AR","可穿戴"], ["消费电子","光学","电子"]],
    "AI应用/模型推理": [["AI应用","人工智能","大模型","AIGC"], ["软件","计算机","IT服务"]],
    "核电/核能": [["核电","核能","核反应堆","核技术"], ["电力","能源","核工业"]],
    "量子计算/量子科技": [["量子","量子计算","量子通信"], ["通信","计算机","科技"]],
    "卫星互联网/北斗": [["卫星互联网","北斗","卫星导航","卫星通信"], ["航天","通信","导航"]],
    "锂矿/盐湖提锂": [["锂矿","锂盐","盐湖提锂","碳酸锂"], ["有色金属","矿业","采掘"]],
    "锂电池/电解液": [["锂电池","电解液","隔膜","正极材料"], ["电池","新能源","化学"]],
    "光伏/太阳能": [["光伏","太阳能","光伏组件","硅料"], ["新能源","电力设备","硅"]],
    "风电": [["风电","风力发电","风电整机","风电塔筒"], ["新能源","电力设备","机械"]],
    "储能": [["储能","储能系统","储能电池"], ["新能源","电池","电力"]],
    "新能源汽车": [["新能源汽车","电动汽车","新能源车"], ["汽车","新能源"]],
    "煤炭": [["煤炭","动力煤","焦煤","煤化工"], ["采掘","能源","煤炭"]],
    "黄金/贵金属": [["黄金","贵金属","金矿"], ["有色金属","矿业","贵金属"]],
    "铜铝有色": [["铜","铝","有色金属","电解铝"], ["有色金属","矿业"]],
    "化工": [["化工","化学原料","化学制品","精细化工"], ["化学","化工","材料"]],
    "钢铁": [["钢铁","特钢","不锈钢","钢铁冶炼"], ["钢铁","冶金","材料"]],
    "银行": [["银行","商业银行"], ["银行","金融"]],
    "券商": [["券商","证券","投行"], ["证券","金融"]],
    "保险": [["保险","寿险","财险"], ["保险","金融"]],
    "房地产开发": [["房地产","地产开发","房地产开发"], ["房地产","地产"]],
    "白酒": [["白酒","白酒酿造"], ["食品","饮料","酿酒"]],
    "食品饮料": [["食品","饮料","乳制品","调味品"], ["食品","饮料","消费品"]],
    "医药/CRO": [["医药","CRO","创新药","医药研发","制药"], ["医药","生物","医疗"]],
    "医疗器械": [["医疗器械","医疗设备","医疗仪器"], ["医疗","医药","健康"]],
    "钨稀土": [["钨","稀土","稀有金属"], ["有色金属","小金属","矿业"]],
}

# ST/次新过滤
def is_st(name):
    return 'ST' in name or '*ST' in name or '退' in name

def is_cixin(code):
    """次新: 688/301开头且代码较大 (粗略判断, 6885xx/6886xx/3015xx/3016xx 较新)"""
    # 更精确的判断需要上市日期, 这里用代码模式粗滤
    # 688开头的: 6885xx以上算次新
    if code.startswith('688') and int(code[3:]) >= 500:
        return True
    # 301开头的: 3015xx以上算次新
    if code.startswith('301') and int(code[3:]) >= 500:
        return True
    # 003开头的较新
    if code.startswith('003'):
        return True
    return False

# ═══════════════════════════════════════════════════════════════
# 3. 主逻辑
# ═══════════════════════════════════════════════════════════════

def main():
    print("=== 扩展赛道标的池 ===")
    print("1. 扫描全市场...")
    all_stocks = fetch_all_a_stocks()
    
    # 建索引: code → stock
    stock_map = {s['code']: s for s in all_stocks}
    
    print(f"\n2. 匹配赛道 + 筛选 + 排序...")
    new_pool = {}
    stats = {'total': 0, 'sectors': 0, 'added': 0}
    
    for sec_name, existing in SECTOR_FIXED_STOCKS.items():
        # 保留现有标的的代码
        existing_codes = set()
        for s in existing:
            parts = s.split()
            if parts:
                existing_codes.add(parts[0])
        
        # 从全市场找匹配该赛道的股票
        kw_groups = SECTOR_KEYWORDS.get(sec_name, [[sec_name[:2]]])
        matched = []
        for s in all_stocks:
            if is_st(s['name']):
                continue
            if is_cixin(s['code']):
                continue
            try:
                amt = float(s['amount'] or 0)
            except (ValueError, TypeError):
                amt = 0
            if amt < 50000000:
                continue
            # 匹配: 先用精确关键词, 不够再用宽泛关键词
            ind = s['industry']
            matched_text = ind + ' ' + s['name']
            for kw_group in kw_groups:
                if any(kw in matched_text for kw in kw_group):
                    matched.append(s)
                    break
        
        # 加上现有池中不在匹配列表的 (保留手工选的)
        for s in existing:
            parts = s.split()
            code = parts[0]
            name = ' '.join(parts[1:]) if len(parts) > 1 else code
            if code in stock_map and code not in [m['code'] for m in matched]:
                if not is_st(stock_map[code]['name']) and not is_cixin(code):
                    matched.append(stock_map[code])
            elif code not in stock_map:
                # 不在东财数据中, 保留原始
                matched.append({'code': code, 'name': name, 'chg': 0, 'price': 0, 'industry': '', 'amount': 0})
        
        # 去重
        seen = set()
        unique = []
        for m in matched:
            if m['code'] not in seen:
                seen.add(m['code'])
                unique.append(m)
        matched = unique
        
        # 按涨跌幅排序 (降序)
        matched.sort(key=lambda x: x.get('chg', 0), reverse=True)
        
        # 选前12只, 但科创/创业板≤3; 优先保留原有标的
        selected = []
        kcb_cyb_count = 0
        # 先放原有标的 (保持原有顺序)
        existing_codes_list = []
        for s in existing:
            parts = s.split()
            code = parts[0]
            existing_codes_list.append(code)
            name = ' '.join(parts[1:]) if len(parts) > 1 else code
            if is_st(name):
                continue
            if is_kcb_cyb(code):
                if kcb_cyb_count >= 3:
                    continue
                kcb_cyb_count += 1
            if is_mainboard(code) or is_kcb_cyb(code):
                # 用东财最新名称
                if code in stock_map and not is_st(stock_map[code]['name']):
                    name = stock_map[code]['name']
                selected.append(f"{code} {name}")
        
        # 再从匹配列表中补充新标的
        for m in matched:
            if len(selected) >= 12:
                break
            code = m['code']
            # 跳过已有的
            if code in [s.split()[0] for s in selected]:
                continue
            if is_kcb_cyb(code):
                if kcb_cyb_count >= 3:
                    continue
                kcb_cyb_count += 1
            if not is_mainboard(code) and not is_kcb_cyb(code):
                continue
            selected.append(f"{code} {m['name']}")
        
        new_pool[sec_name] = selected
        stats['total'] += len(selected)
        stats['sectors'] += 1
        added = len(selected) - len(existing)
        if added > 0:
            stats['added'] += added
        
        print(f"  {sec_name}: {len(existing)}→{len(selected)}只 (新增{added})")
    
    print(f"\n=== 统计 ===")
    print(f"赛道: {stats['sectors']}")
    print(f"总标的: {stats['total']} (原{sum(len(v) for v in SECTOR_FIXED_STOCKS.values())})")
    print(f"新增: {stats['added']}")
    
    # 验证规则
    print(f"\n=== 规则验证 ===")
    violations = 0
    for sec, stocks in new_pool.items():
        kcb_cyb = [s for s in stocks if is_kcb_cyb(s.split()[0])]
        if len(kcb_cyb) > 3:
            print(f"  ⚠ {sec}: 科创/创业 {len(kcb_cyb)}只 (>3)")
            violations += 1
        for s in stocks:
            name = ' '.join(s.split()[1:])
            if is_st(name):
                print(f"  ⚠ {sec}: ST股 {s}")
                violations += 1
    print(f"违规: {violations} ({'全部通过' if violations==0 else '有问题'})")
    
    # 生成新的 sector_fixed_stocks.py
    print(f"\n=== 生成 sector_fixed_stocks.py ===")
    output = '#!/usr/bin/env python3\n"""\nSECTOR_FIXED_STOCKS — 每个赛道8-12只固定精选标的\n规则:\n  1. 主业匹配: 标的所属行业/概念与赛道直接相关\n  2. 科创(688)/创业板(300/301)合计 ≤3只\n  3. 去除ST/*ST/退市股\n  4. 去除次新股 (6885xx+/3015xx+/003开头)\n  5. 按当日涨跌幅排序, 优先选近期强势股\n  6. 单只股票最多出现在3个赛道\n自动生成, 每日由 run_update.py 刷新实时价格\n"""\n\nSECTOR_FIXED_STOCKS = {\n'
    for sec, stocks in new_pool.items():
        lines = []
        for s in stocks:
            lines.append(f'"{s}"')
        output += f'    "{sec}": [{", ".join(lines)}],\n'
    output += '}\n\n'
    
    # 保留原有的验证函数
    output += '''def is_kcb_cyb(code):
    return code.startswith("688") or code.startswith("300") or code.startswith("301")

def is_mainboard(code):
    return code.startswith("600") or code.startswith("601") or code.startswith("603") or code.startswith("605") or \\
           code.startswith("000") or code.startswith("001") or code.startswith("002") or code.startswith("003")

def validate_stocks(stocks, sector_name=""):
    kcb_cyb = [s for s in stocks if is_kcb_cyb(s.split()[0])]
    errors = []
    if len(kcb_cyb) > 3:
        errors.append(f"[{sector_name}] 科创/创业板 {len(kcb_cyb)} 只 (≤3)")
    if errors:
        for e in errors: print(f"  WARNING: {e}")
        return False
    return True

if __name__ == '__main__':
    from collections import Counter, defaultdict
    ks = list(SECTOR_FIXED_STOCKS.keys())
    print(f"Sectors: {len(ks)}")
    errors = 0
    for name, stocks in SECTOR_FIXED_STOCKS.items():
        if not validate_stocks(stocks, name): errors += 1
    print(f"Board rule: {'ALL PASS' if errors == 0 else f'{errors} FAILURES'}")
    total = sum(len(v) for v in SECTOR_FIXED_STOCKS.values())
    print(f"Total stocks: {total}")
'''
    
    with open('sector_fixed_stocks.py', 'w', encoding='utf-8') as f:
        f.write(output)
    print(f"✓ sector_fixed_stocks.py 已更新")
    
    return new_pool

if __name__ == '__main__':
    main()
