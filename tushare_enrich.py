#!/usr/bin/env python3
"""
tushare_enrich.py — Tushare 数据增强模块
注入到 run_update.py 管线中，替换最不稳定的东财调用 + 新增资金面维度。

使用方式:
    from tushare_enrich import get_pro, enrich_data
    pro = get_pro()
    enriched = enrich_data(pro, codes, cst)

依赖: pip install tushare (月卡, gyzcloud.top 代理)
Token: 环境变量 TUSHARE_TOKEN 或 GitHub Secrets
"""

import os, json, re
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════════
# 0. 配置
# ═══════════════════════════════════════════════════════════════

TOKEN = os.environ.get('TUSHARE_TOKEN', '')  # 必须从GitHub Secrets注入，不再硬编码
API_URL = 'https://ts.gyzcloud.top/api'

_pro = None

def get_pro():
    """返回已配置的 tushare pro_api（单例）"""
    global _pro
    if _pro is not None:
        return _pro
    try:
        import tushare as ts
        ts.set_token(TOKEN)
        _pro = ts.pro_api()
        _pro._DataApi__http_url = API_URL
        return _pro
    except ImportError:
        print("  [tushare] 未安装 tushare, 跳过增强")
        return None
    except Exception as e:
        print(f"  [tushare] 连接失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 1. UTF-8 清洗工具 — 消灭 data.json 损坏的根源
# ═══════════════════════════════════════════════════════════════

_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')

def sanitize_str(s):
    """移除字符串中的孤立代理对（lone surrogates），防止 JSON 非法"""
    if isinstance(s, str):
        # 1. 先尝试 encode+replace 修复
        try:
            s = s.encode('utf-8', errors='replace').decode('utf-8')
        except Exception:
            pass
        # 2. 移除残留的代理对
        s = _SURROGATE_RE.sub('?', s)
    return s

def sanitize_obj(obj):
    """递归清洗 dict/list 中的所有字符串"""
    if isinstance(obj, str):
        return sanitize_str(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    return obj

def safe_json_dump(obj, fp):
    """安全的 json.dump — 确保只会写出合法 UTF-8"""
    cleaned = sanitize_obj(obj)
    json.dump(cleaned, fp, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# 2. 核心数据接口（tushare 替代东财）
# ═══════════════════════════════════════════════════════════════

def fetch_indices_tushare(pro, cst):
    """
    Tushare 指数行情 → 与现有 {'n','v','chg','up'} 格式兼容。
    如果 tushare 不可用或非交易日，返回 [] 让调用方降级。
    """
    if pro is None:
        return []

    idx_map = [
        ('000001.SH', '上证指数'), ('399001.SZ', '深证成指'), ('399006.SZ', '创业板指'),
        ('000688.SH', '科创50'),   ('000300.SH', '沪深300'), ('000016.SH', '上证50')
    ]

    for attempt in range(4):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            # 逐只拉取（比逗号分隔更可靠）
            results = []
            for code, name in idx_map:
                df = pro.index_daily(ts_code=code, start_date=date_str, end_date=date_str)
                if df is None or df.empty:
                    continue
                row = df.iloc[0]
                chg = round(float(row.get('pct_chg', 0) or 0), 2)
                close = float(row.get('close', 0) or 0)
                results.append({
                    'n': name,
                    'v': f'{close:.0f}',
                    'chg': f'{chg:+.2f}%',
                    'up': chg >= 0
                })
            if len(results) >= 3:
                return results
        except Exception:
            continue
    return []


def fetch_zt_dt_tushare(pro, cst):
    """
    Tushare 涨跌停列表 → {zt_count, dt_count, zt_list, dt_list}
    比东财 clist 更准，有 limit_type 字段区分涨停/跌停/炸板
    """
    if pro is None:
        return None

    for attempt in range(3):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            # 涨停
            zt = pro.limit_list_d(trade_date=date_str, limit_type='U')
            # 跌停
            dt = pro.limit_list_d(trade_date=date_str, limit_type='D')

            zt_count = len(zt) if zt is not None else 0
            dt_count = len(dt) if dt is not None else 0

            zt_list = []
            if zt is not None and not zt.empty:
                for _, r in zt.iterrows():
                    zt_list.append({
                        'c': str(r.get('ts_code', '')).split('.')[0],
                        'n': str(r.get('name', '')),
                        'pct': round(float(r.get('pct_chg', 0) or 0), 2),
                        'industry': str(r.get('industry', '') or ''),
                    })

            dt_list = []
            if dt is not None and not dt.empty:
                for _, r in dt.iterrows():
                    dt_list.append({
                        'c': str(r.get('ts_code', '')).split('.')[0],
                        'n': str(r.get('name', '')),
                        'pct': round(float(r.get('pct_chg', 0) or 0), 2),
                    })

            return {
                'zt_count': zt_count,
                'dt_count': dt_count,
                'zt_list': zt_list,
                'dt_list': dt_list,
                'date': date_str,
            }
        except Exception:
            continue
    return None


def fetch_zt_ladder_tushare(pro, cst):
    """
    Tushare 连板梯队 → 与现有 ztLadder 格式兼容
    返回: {tiers: [{boardCount, stocks: [{c,n,industry,p,zdf}]}], maxBoard, totalCount}
    """
    if pro is None:
        return None

    for attempt in range(3):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            df = pro.limit_step(trade_date=date_str)
            if df is None or df.empty:
                continue

            tiers_dict = {}
            for _, row in df.iterrows():
                nums = int(row.get('nums', 1) or 1)
                code = str(row.get('ts_code', '')).split('.')[0]
                name = str(row.get('name', ''))

                # 拉该票的详细数据
                stock = {
                    'c': code,
                    'n': name,
                    'industry': '',
                    'p': 0,
                    'zdf': 0,
                }
                tiers_dict.setdefault(nums, []).append(stock)

            if not tiers_dict:
                continue

            tiers = [
                {
                    'boardCount': k,
                    'stocks': sorted(v, key=lambda s: s['n'])
                }
                for k, v in sorted(tiers_dict.items(), reverse=True)
            ]
            total = sum(len(v) for v in tiers_dict.values())

            return {
                'updated': cst.strftime('%Y-%m-%d %H:%M'),
                'tiers': tiers,
                'maxBoard': max(tiers_dict.keys()),
                'totalCount': total,
            }
        except Exception:
            continue
    return None


def fetch_northbound_tushare(pro, cst):
    """
    Tushare 北向资金 → 与现有 northbound 字段兼容
    返回: {date, hgt_yi, sgt_yi, net_yi, points, status}
    """
    if pro is None:
        return None

    for attempt in range(5):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            df = pro.moneyflow_hsgt(trade_date=date_str)
            if df is None or df.empty:
                continue

            row = df.iloc[0]
            hgt = round(float(row.get('hgt', 0) or 0) / 10000, 2)  # 万元→亿元
            sgt = round(float(row.get('sgt', 0) or 0) / 10000, 2)
            north = round(float(row.get('north_money', 0) or 0) / 10000, 2)

            return {
                'date': date_str,
                'hgt_yi': hgt,
                'sgt_yi': sgt,
                'net_yi': north,
                'points': 1,
                'status': '收盘',
            }
        except Exception:
            continue
    return None


def fetch_lhb_tushare(pro, cst):
    """
    Tushare 龙虎榜 → 与现有 lhb 格式兼容
    返回: {date, total, topBuy: [{c,n,net,chg,reason}], topSell: [...]}
    """
    if pro is None:
        return None

    for attempt in range(4):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            df = pro.top_list(trade_date=date_str)
            if df is None or df.empty:
                continue

            buy_list, sell_list = [], []
            for _, row in df.iterrows():
                code = str(row.get('ts_code', '')).split('.')[0]
                name = str(row.get('name', ''))
                net_val = float(row.get('net_buy_amount', 0) or 0) / 10000  # 元→万
                chg_val = round(float(row.get('pct_change', 0) or 0), 1)
                reason = str(row.get('reason', '') or '')[:30]

                entry = {
                    'c': code, 'n': name,
                    'net': round(net_val, 2),
                    'chg': chg_val,
                    'reason': reason,
                }
                if net_val > 0:
                    buy_list.append(entry)
                else:
                    sell_list.append(entry)

            buy_list.sort(key=lambda x: -x['net'])
            sell_list.sort(key=lambda x: x['net'])

            return {
                'date': td.strftime('%m/%d'),
                'total': len(df),
                'topBuy': buy_list[:15],
                'topSell': sell_list[:15],
            }
        except Exception:
            continue
    return None


def fetch_margin_tushare(pro, codes, cst):
    """
    Tushare 融资融券 → 替代东财逐票爬虫
    批量拉当日全市场融资融券明细，只保留我们关注的标的。
    返回: {stocks: [{c,n,d,rzye_wan,change_5d,rzmre_wan}], status}
    """
    if pro is None or not codes:
        return None

    for attempt in range(4):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            df = pro.margin_detail(trade_date=date_str)
            if df is None or df.empty:
                continue

            # 只保留我们关注的标的
            code_set = set(codes)
            summary = []
            for _, row in df.iterrows():
                code = str(row.get('ts_code', '')).split('.')[0]
                if code not in code_set:
                    continue
                rzye = float(row.get('rzye', 0) or 0) / 10000  # 融资余额(万)
                rzmre = float(row.get('rzmre', 0) or 0) / 10000  # 融资买入额(万)
                rqye = float(row.get('rqye', 0) or 0) / 10000  # 融券余额(万)

                summary.append({
                    'c': code,
                    'n': str(row.get('name', '')) if 'name' in df.columns else code,
                    'd': date_str,
                    'rzye_wan': round(rzye, 0),
                    'change_5d': 0,  # 单日拉取，无法计算5日变化
                    'rzmre_wan': round(rzmre, 0),
                    'rqye_wan': round(rqye, 0),
                })

            summary.sort(key=lambda x: -x['rzmre_wan'])
            return {
                'stocks': summary[:40],
                'status': 'ok' if summary else '无匹配标的',
                'updated': date_str,
            }
        except Exception:
            continue
    return None


def fetch_daily_basic_tushare(pro, codes, cst):
    """
    Tushare 估值指标 → 批量拉 PE/PB/换手率/量比
    一次调用拉全市场，替代东财逐票爬。
    返回: {code: {pe, pb, turnover, vol_ratio, total_mv}}
    """
    if pro is None or not codes:
        return {}

    for attempt in range(3):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            df = pro.daily_basic(trade_date=date_str)
            if df is None or df.empty:
                continue

            code_set = set(codes)
            result = {}
            for _, row in df.iterrows():
                code = str(row.get('ts_code', '')).split('.')[0]
                if code not in code_set:
                    continue
                result[code] = {
                    'pe': round(float(row.get('pe', 0) or 0), 2),
                    'pb': round(float(row.get('pb', 0) or 0), 2),
                    'turnover': round(float(row.get('turnover_rate', 0) or 0), 2),
                    'vol_ratio': round(float(row.get('volume_ratio', 0) or 0), 2),
                    'total_mv': round(float(row.get('total_mv', 0) or 0) / 10000, 0),  # 元→万
                }
            return result
        except Exception:
            continue
    return {}


def fetch_moneyflow_tushare(pro, codes, cst):
    """
    Tushare 个股资金流 → 主力净流入
    批量拉全市场资金流，提取我们关注的标的。
    返回: {code: {main_net_wan, buy_sm_wan, sell_sm_wan}}
    """
    if pro is None or not codes:
        return {}

    for attempt in range(3):
        td = cst - timedelta(days=attempt)
        if td.weekday() >= 5:
            continue
        date_str = td.strftime('%Y%m%d')
        try:
            # 需要逐票拉 — 合并成批量（用循环）
            result = {}
            code_set = set(codes[:60])  # 只拉前60只（关键标的）
            for code in code_set:
                ts_code = f"{code}.{'SH' if code.startswith(('60','68')) else 'SZ'}"
                try:
                    df = pro.moneyflow(ts_code=ts_code, start_date=date_str, end_date=date_str)
                    if df is not None and not df.empty:
                        row = df.iloc[0]
                        buy_sm = float(row.get('buy_sm_amount', 0) or 0) / 10000
                        sell_sm = float(row.get('sell_sm_amount', 0) or 0) / 10000
                        buy_lg = float(row.get('buy_lg_amount', 0) or 0) / 10000
                        sell_lg = float(row.get('sell_lg_amount', 0) or 0) / 10000
                        result[code] = {
                            'main_net': round(buy_sm + buy_lg - sell_sm - sell_lg, 1),
                            'buy_sm_wan': round(buy_sm, 1),
                            'sell_sm_wan': round(sell_sm, 1),
                        }
                except Exception:
                    pass
            return result
        except Exception:
            continue
    return {}


def fetch_share_float_tushare(pro, cst):
    """
    Tushare 限售解禁 → 未来30天解禁预警
    返回: {alerts: [{c,n,d,ratio,shares}], forwardDays: 30}
    """
    if pro is None:
        return None

    try:
        start = cst.strftime('%Y%m%d')
        end = (cst + timedelta(days=30)).strftime('%Y%m%d')
        df = pro.share_float(start_date=start, end_date=end)
        if df is None or df.empty:
            return None

        alerts = []
        for _, row in df.iterrows():
            code = str(row.get('ts_code', '')).split('.')[0]
            ratio = float(row.get('float_ratio', 0) or 0)
            if ratio < 0.5:  # 只关注 >0.5%的解禁
                continue
            alerts.append({
                'c': code,
                'n': str(row.get('name', '')) if 'name' in df.columns else code,
                'd': str(row.get('ann_date', ''))[:10],
                'ratio': round(ratio, 2),
                'shares': round(float(row.get('float_share', 0) or 0) / 10000, 0),
            })
        alerts.sort(key=lambda x: (x['d'], -x['ratio']))
        return {
            'scanned': len(df),
            'alerts': alerts[:30],
            'forwardDays': 30,
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# 3. 统一增强入口
# ═══════════════════════════════════════════════════════════════

def enrich_data(codes, cst=None, force=False):
    """
    主入口 — 用 tushare 增强所有数据维度。
    返回 dict，可直接 merge 到 data.json。

    调用方式（在 run_update.py 中）:
        from tushare_enrich import enrich_data
        tushare_data = enrich_data(codes, cst)
        out.update(tushare_data)
    """
    if cst is None:
        cst = datetime.now(timezone.utc) + timedelta(hours=8)

    pro = get_pro()
    if pro is None and not force:
        print("  [tushare] 不可用，跳过增强（东财降级链正常运作）")
        return {}

    enriched = {}
    api_calls = 0

    # 1. 指数行情（替代东财 push2 + 新浪）
    t0 = datetime.now()
    idx = fetch_indices_tushare(pro, cst)
    api_calls += 1
    if idx:
        enriched['_tushare_indices'] = idx
        print(f"  [tushare] 指数: {len(idx)}个 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 2. 涨跌停（替代东财 clist 全市场扫描）
    t0 = datetime.now()
    zt_dt = fetch_zt_dt_tushare(pro, cst)
    api_calls += 1
    if zt_dt:
        enriched['_tushare_zt_dt'] = zt_dt
        print(f"  [tushare] 涨跌停: {zt_dt['zt_count']}涨停/{zt_dt['dt_count']}跌停 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 3. 连板梯队（替代东财 getTopicZTPool JSONP）
    t0 = datetime.now()
    zt_ladder = fetch_zt_ladder_tushare(pro, cst)
    api_calls += 1
    if zt_ladder:
        enriched['_tushare_zt_ladder'] = zt_ladder
        print(f"  [tushare] 连板: 最高{zt_ladder['maxBoard']}板/{zt_ladder['totalCount']}只 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 4. 北向资金（替代同花顺 hsgtApi）
    t0 = datetime.now()
    nb = fetch_northbound_tushare(pro, cst)
    api_calls += 1
    if nb:
        enriched['northbound'] = nb
        print(f"  [tushare] 北向: 净{nb['net_yi']}亿 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 5. 龙虎榜（替代东财 getStockLHBList JSONP）
    t0 = datetime.now()
    lhb = fetch_lhb_tushare(pro, cst)
    api_calls += 1
    if lhb:
        enriched['lhb'] = lhb
        enriched['lhbFull'] = {
            'date': lhb['date'],
            'total': lhb['total'],
            'stocks': lhb['topBuy'] + lhb['topSell'],
            'status': 'ok',
        }
        print(f"  [tushare] 龙虎榜: {lhb['total']}只 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 6. 融资融券（替代东财逐票爬 RPTA_WEB_RZRQ_GGMX）
    if codes:
        t0 = datetime.now()
        margin = fetch_margin_tushare(pro, codes, cst)
        api_calls += 1
        if margin and margin['stocks']:
            enriched['marginSummary'] = margin
            print(f"  [tushare] 融资融券: {len(margin['stocks'])}只 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 7. 估值指标（批量替代东财逐票爬）
    if codes:
        t0 = datetime.now()
        vals = fetch_daily_basic_tushare(pro, codes, cst)
        api_calls += 1
        if vals:
            enriched['tencentVal'] = {c: {
                'n': '', 'p': 0,
                'pe': v['pe'], 'pb': v['pb'],
                'mcap': v['total_mv'], 'chg': 0,
                'to': v['turnover']
            } for c, v in vals.items()}
            enriched['_tushare_vals'] = vals
            print(f"  [tushare] 估值: {len(vals)}只 PE/PB ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 8. 限售解禁
    t0 = datetime.now()
    lockup = fetch_share_float_tushare(pro, cst)
    api_calls += 1
    if lockup and lockup['alerts']:
        enriched['lockupAlerts'] = lockup
        print(f"  [tushare] 解禁预警: {len(lockup['alerts'])}批 ({(datetime.now()-t0).total_seconds():.1f}s)")

    # 9. 资金流（仅关键标的，控制API调用量）
    if codes and api_calls < 120:  # 为资金流预留调用额度
        t0 = datetime.now()
        mf = fetch_moneyflow_tushare(pro, codes[:30], cst)
        api_calls += len(codes[:30])
        if mf:
            enriched['_tushare_moneyflow'] = mf
            print(f"  [tushare] 资金流: {len(mf)}只 ({(datetime.now()-t0).total_seconds():.1f}s)")

    enriched['_tushare_api_calls'] = api_calls
    enriched['_tushare_updated'] = cst.strftime('%Y-%m-%d %H:%M CST')
    print(f"  [tushare] 总计 {api_calls} 次API调用，剩余 {150 - api_calls} 次/分钟")
    return enriched


# ═══════════════════════════════════════════════════════════════
# 4. 后处理器 — 把 tushare 数据合并到 data.json 输出
# ═══════════════════════════════════════════════════════════════

def apply_enrichment(out, tushare_data):
    """
    将 tushare 增强数据应用到 data.json 输出 dict。
    只在东财降级链返回空/不完整时覆盖，不覆盖已有高质量数据。

    out: 要写入 data.json 的完整 dict
    tushare_data: enrich_data() 的返回值
    """
    if not tushare_data:
        return out

    # ── 指数: 只在东财+新浪都失败时用 tushare ──
    if tushare_data.get('_tushare_indices'):
        existing_idx = out.get('recap', {}).get('index', [])
        if not existing_idx or len(existing_idx) < 3:
            out.setdefault('recap', {})['index'] = tushare_data['_tushare_indices']

    # ── 涨跌停: 只在东财扫描失败时用 ──
    recap = out.setdefault('recap', {})
    if tushare_data.get('_tushare_zt_dt'):
        zt_dt = tushare_data['_tushare_zt_dt']
        if recap.get('ztCount', 0) == 0:
            recap['ztCount'] = zt_dt['zt_count']
        if recap.get('dtCount', 0) == 0:
            recap['dtCount'] = zt_dt['dt_count']
        # 将个股列表注入 livePrices 扩展
        if zt_dt.get('zt_list'):
            out.setdefault('_tushare_zt_list', zt_dt['zt_list'])[:] = zt_dt['zt_list']

    # ── 连板: 东财失败时用 tushare ──
    if tushare_data.get('_tushare_zt_ladder'):
        if not recap.get('ztLadder') or not recap['ztLadder'].get('tiers'):
            recap['ztLadder'] = tushare_data['_tushare_zt_ladder']

    # ── 北向: 直接覆盖（tushare 比同花顺 hsgtApi 更准）──
    if tushare_data.get('northbound'):
        out['northbound'] = tushare_data['northbound']

    # ── 龙虎榜: 东财失败时用 ──
    if tushare_data.get('lhb'):
        existing_lhb = recap.get('lhb', {})
        if not existing_lhb or existing_lhb.get('total', 0) == 0:
            recap['lhb'] = tushare_data['lhb']
        if tushare_data.get('lhbFull'):
            if not out.get('lhbFull') or out['lhbFull'].get('total', 0) == 0:
                out['lhbFull'] = tushare_data['lhbFull']

    # ── 融资融券: 只在东财逐票爬失败时用 ──
    if tushare_data.get('marginSummary'):
        existing_margin = out.get('marginSummary', {})
        if not existing_margin.get('stocks') or len(existing_margin.get('stocks', [])) < 5:
            out['marginSummary'] = tushare_data['marginSummary']

    # ── 估值: 只在腾讯接口失败时用 ──
    if tushare_data.get('tencentVal'):
        existing_tv = out.get('tencentVal', {})
        if not existing_tv or len(existing_tv) < 5:
            out['tencentVal'] = tushare_data['tencentVal']

    # ── 解禁: 只在东财逐票爬失败时用 ──
    if tushare_data.get('lockupAlerts'):
        existing_lockup = out.get('lockupAlerts', {})
        if not existing_lockup.get('alerts') or len(existing_lockup.get('alerts', [])) < 3:
            out['lockupAlerts'] = tushare_data['lockupAlerts']

    # ── 资金流: 新增字段，不覆盖 ──
    if tushare_data.get('_tushare_moneyflow'):
        out['_tushare_moneyflow'] = tushare_data['_tushare_moneyflow']

    # 元数据
    out['_tushare_meta'] = {
        'api_calls': tushare_data.get('_tushare_api_calls', 0),
        'updated': tushare_data.get('_tushare_updated', ''),
    }

    return out


# ═══════════════════════════════════════════════════════════════
# 5. 独立运行（调试用）
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"=== Tushare Enrich Test @ {cst.strftime('%Y-%m-%d %H:%M')} ===")

    # 测试数据
    test_codes = ['600519', '000858', '300750', '601318', '000333',
                  '002415', '688981', '300274', '600036', '601012']

    data = enrich_data(test_codes, cst)
    print(f"\n=== 结果 ===")
    for k, v in sorted(data.items()):
        if isinstance(v, dict):
            print(f"  {k}: dict ({len(v)} keys)")
        elif isinstance(v, list):
            print(f"  {k}: list ({len(v)} items)")
        else:
            print(f"  {k}: {v}")

    # 测试 safe_json_dump
    test_obj = {
        'name': '测试𐀀数据',
        'items': [{'t': '正常'}, {'t': '异常\udca5文本'}],
    }
    import io
    buf = io.StringIO()
    safe_json_dump(test_obj, buf)
    cleaned = buf.getvalue()
    print(f"\n=== UTF-8 清洗测试 ===")
    print(f"  清洗后: {cleaned[:100]}...")
    try:
        json.loads(cleaned)
        print("  JSON 解析: ✅ 合法")
    except json.JSONDecodeError as e:
        print(f"  JSON 解析: ❌ {e}")

    print("\nDone.")
