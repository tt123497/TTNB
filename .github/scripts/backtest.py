#!/usr/bin/env python3
"""
Briefing backtest system — tracks AI sentinel pick performance.

Runs once daily (15:30 CST market close).
1. Records today's briefing picks with closing prices
2. Checks previous session's picks — calculates 1d/3d/5d returns
3. Stores history: _backtest in data.json, max 90 days
"""
import json, os
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(DIR, 'data.json')

def fetch_prices(codes, fallback=None, fallback_tencent=None):
    """Batch fetch current prices for a list of stock codes.
    Priority: livePrices from data.json > tencentVal > EastMoney API
    """
    if not codes:
        return {}

    result = {}

    # Tier 1: Use livePrices from data.json (last real prices captured during trading)
    if fallback:
        for c in codes:
            for prefix in ['sh', 'sz']:
                key = f"{prefix}{c}"
                if key in fallback:
                    lp = fallback[key]
                    price = lp.get('price', 0) if isinstance(lp, dict) else 0
                    if price and price > 0:
                        result[c] = {
                            'price': price,
                            'chg': lp.get('chg_pct', 0) if isinstance(lp, dict) else 0,
                            'name': lp.get('name', '') if isinstance(lp, dict) else ''
                        }
                    break
            if c in result:
                continue

    # Tier 1.5: Use tencentVal from data.json (PE/PB/price snapshot)
    if fallback_tencent:
        for c in codes:
            if c in result:
                continue
            if c in fallback_tencent:
                tv = fallback_tencent[c]
                price = tv.get('p', 0) if isinstance(tv, dict) else 0
                if price and price > 0:
                    result[c] = {
                        'price': price,
                        'chg': tv.get('chg', 0) if isinstance(tv, dict) else 0,
                        'name': tv.get('n', '') if isinstance(tv, dict) else ''
                    }

    # Tier 2: EastMoney API (only for codes we haven't found yet)
    remaining = [c for c in codes if c not in result]
    if remaining:
        secids = []
        for c in remaining:
            pf = '1.' if c.startswith(('60', '68')) else '0.'
            secids.append(pf + c)
        url = 'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f12,f14&secids=' + ','.join(secids) + '&ut=bd1d9ddb04089700cf9c27f6f7426281'
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urlopen(req, timeout=12) as r:
                api_data = json.loads(r.read().decode('utf-8', errors='replace'))
            for s in api_data.get('data', {}).get('diff', []):
                code = s.get('f12', '')
                price = s.get('f2', 0)
                # Only accept non-zero prices (skip post-market zeros)
                if price and price > 0:
                    result[code] = {'price': price, 'chg': s.get('f3', 0), 'name': s.get('f14', '')}
        except:
            pass

    return result

def main():
    cst = datetime.now(timezone.utc) + timedelta(hours=8)
    today_str = cst.strftime('%Y-%m-%d')

    data = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                pass

    live_prices = data.get('livePrices', {})
    tencent_val = data.get('tencentVal', {})

    bhistory = data.get('_backtest', {'records': [], 'stats': {}})
    records = bhistory.get('records', [])

    # ── Step 1: Check yesterday's picks (settle returns) ──
    unsettled = []
    for rec in records:
        if 'result' in rec:
            continue  # already settled
        # This is today's entry, not from yesterday — skip
        if rec.get('date') == today_str:
            unsettled.append(rec)
            continue
        unsettled.append(rec)

    if unsettled:
        # Fetch current prices for all unsettled picks
        all_codes = []
        for rec in unsettled:
            for p in rec.get('picks', []):
                all_codes.append(p['c'])
        prices = fetch_prices(all_codes, fallback=live_prices, fallback_tencent=tencent_val)

        for rec in unsettled:
            rec_prices = {p['c']: p for p in rec.get('picks', [])}
            winners, losers, neutral = 0, 0, 0
            settled_picks = []
            for p in rec.get('picks', []):
                code = p['c']
                entry_price = p.get('entry_price', 0)
                now = prices.get(code, {})
                now_price = now.get('price', 0)
                pct_chg = 0
                if entry_price and now_price:
                    pct_chg = round((now_price - entry_price) / entry_price * 100, 2)
                p['pct_1d'] = pct_chg
                p['result'] = 'up' if pct_chg > 0 else ('down' if pct_chg < 0 else 'flat')
                if pct_chg > 1:
                    winners += 1
                elif pct_chg < -1:
                    losers += 1
                else:
                    neutral += 1
                settled_picks.append(p)
            rec['picks'] = settled_picks
            rec['result'] = {
                'winners': winners,
                'losers': losers,
                'neutral': neutral,
                'total': len(settled_picks),
                'hit_rate': round(winners / max(len(settled_picks), 1) * 100, 0),
                'settled_date': today_str
            }

    # ── Step 2: Record today's picks ──
    briefing = data.get('briefing', {})
    picks = briefing.get('picks', []) or data.get('picks', [])
    if picks and not any(r.get('date') == today_str for r in records):
        # Fetch closing prices
        codes = [p['c'] for p in picks if p.get('c')]
        prices = fetch_prices(codes, fallback=live_prices, fallback_tencent=tencent_val)

        today_picks = []
        for p in picks:
            code = p.get('c', '')
            price_data = prices.get(code, {})
            today_picks.append({
                'c': code,
                'n': price_data.get('name', p.get('n', '')),
                'why': p.get('why', ''),
                'sec': p.get('sec', ''),
                'entry_price': price_data.get('price', 0),
                'entry_chg': price_data.get('chg', 0)
            })

        records.append({
            'date': today_str,
            'day_of_week': cst.weekday(),
            'picks': today_picks,
            'top3_summary': [(n.get('t', '') or '')[:40] for n in (briefing.get('top3', []) or [])[:3]]
        })
        print(f'Recorded {len(today_picks)} picks for {today_str}')

    # Cap at 90 days
    if len(records) > 90:
        records = records[-90:]

    # ── Step 3: Calculate aggregate stats ──
    settled = [r for r in records if 'result' in r]
    if settled:
        total_picks = sum(r['result']['total'] for r in settled)
        total_wins = sum(r['result']['winners'] for r in settled)
        avg_hit = round(total_wins / max(total_picks, 1) * 100, 1)

        # 3-day rolling hit rate
        recent = settled[-5:] if len(settled) >= 5 else settled
        recent_picks = sum(r['result']['total'] for r in recent)
        recent_wins = sum(r['result']['winners'] for r in recent)
        recent_hit = round(recent_wins / max(recent_picks, 1) * 100, 1)

        bhistory['stats'] = {
            'total_days': len(settled),
            'total_picks': total_picks,
            'total_wins': total_wins,
            'overall_hit_rate': avg_hit,
            'recent_5d_hit_rate': recent_hit,
            'last_updated': today_str
        }

    bhistory['records'] = records
    data['_backtest'] = bhistory

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    stats = bhistory.get('stats', {})
    print(f'Backtest: {len(settled)} days settled, {stats.get("overall_hit_rate","?")}% hit rate')
    if records and records[-1].get('date') == today_str:
        print(f'  Today: {len(records[-1]["picks"])} picks recorded')


if __name__ == '__main__':
    main()
