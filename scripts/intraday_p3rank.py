#!/usr/bin/env python3
"""盘中轻扫(新P3口径) 190池: 冻结带×实时价, 按p3_target降序排列."""
import json, re, time, urllib.request
from pathlib import Path
from collections import Counter

ROOT = Path('/root/project/workspace/stock-selector-v2')
DAY = '2026-10-08'

snap = json.load(open(ROOT / f'data/r2/scans/current_scan_{DAY}.json'))
sh = json.load(open(ROOT / f'data/r2/shadow/shadow_{DAY}.json'))['rows']
sids = {r['stock'] for r in sh}

# ---- 新口径 p3_target (a3b3447) ----
def p3_target(tier, reg, support_state):
    if tier in ('EXIT', 'WATCH', 'NO_BUILD'):
        return 0.0
    base = {'CONFIRM_CANDIDATE': 0.5, 'RISK_HOLD': 0.25, 'BUILD': 0.2}.get(tier, 0.0)
    m = {'BULL': 1.0, 'BEAR': 0.5}.get(reg, 0.75)
    t = base * m
    if support_state == 'UNDERCUT_TEST':
        t *= 0.5
    return round(t, 4)

cards = [c for c in snap['cards'] if c['stock'] in sids]

# ---- 实时报价 ----
def market(code):
    return 'sh' if code.startswith(('6', '9')) else ('bj' if code[0] in '48' else 'sz')

import sys as _sys
_sys.path.insert(0, str(ROOT / 'src'))
from r2.tdx_quotes import (quotes as _tdx_quotes, index_pct as _tdx_index_pct,
                           split_quotes as _tdx_split, lookup as _tdx_lookup)

codes = [c['stock'] for c in cards]
q = _tdx_quotes(codes)          # 2026-10-21 起 TDX 通道，退役腾讯 qt.gtimg.cn
mkt_pct = _tdx_index_pct()      # 上证综指

# ---- 停牌/无数据口径（2026-10-22 R4/R5 对拍 C-1/C-2/C-3 定案）----
#   服务器不返回记录（missing）才是停牌/无行情信号；不能用 price<=0 判停牌——
#   盘前 09:10 全市场请求 5598 只、返回 5576 只且全部 price=0/vol=0/servertime=8:35。
#   有记录但 price<=0 = 盘前/竞价未撮合，单列 no_price，不混进 missing。
_ok, missing, no_price = _tdx_split(q, codes)

# ---- 逐股判定 ----
rows = []
reg = cards[0]['decision']['regime']
for c in cards:
    t = _tdx_lookup(_ok, c['stock'])
    if not t:
        continue
    cs = c['capital_support']
    de = c['decision']
    bl, bh = cs['cost_band_low'], cs['cost_band_high']
    trig = bl * 0.95
    px = t['price']
    frozen = cs['support_state']

    # 实时支撑状态
    if px >= bh: live = 'ABOVE'
    elif px >= bl: live = 'IN_BAND'
    else: live = 'UNDERCUT'

    # 四类警报 (intraday_scan 逻辑)
    alerts = []
    if px < trig: alerts.append('CROSS_TRIGGER')
    elif px / trig - 1 < 0.02: alerts.append('NEAR_TRIGGER')
    if frozen == 'ABOVE_SUPPORT' and px < bh: alerts.append('BAND_TEST')
    if frozen in ('UNDERCUT_TEST', 'IN_SUPPORT') and px > bh: alerts.append('BAND_BREAKOUT')
    if t['pct'] > mkt_pct + 1.0: alerts.append('RS_VS_INDEX')

    rows.append({
        'stock': c['stock'], 'name': t['name'], 'tier': de['decision_tier'],
        'hl': de.get('higher_low', False), 'frozen': frozen,
        'px': px, 'pct': t['pct'], 'bl': bl, 'bh': bh, 'trig': trig,
        'live': live, 'alerts': alerts,
        'p3': p3_target(de['decision_tier'], 'BEAR' if reg.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER', frozen),
        'exit_d': px / trig - 1,
    })

# ---- 按 p3_target 降序, 同级: 警报优先 > 距触发线近→远 ----
alert_rank = {'CROSS_TRIGGER': 0, 'NEAR_TRIGGER': 1, 'BAND_BREAKOUT': 2, 'RS_VS_INDEX': 3}
rows.sort(key=lambda r: (-r['p3'], min([alert_rank.get(a, 9) for a in r['alerts']], default=9), r['exit_d']))

# ---- 汇总 ----
print(f'快照基日: {DAY} | 池: {len(sids)} | 实时报价: {len(rows)} | 缺失: {len(missing)} | 无价: {len(no_price)}')
print(f'大盘(上证): {mkt_pct:+.2f}%')
print()
p3_dist = Counter(r['p3'] for r in rows)
print('P3档位分布:', dict(sorted(p3_dist.items(), reverse=True)))
print('实时状态:', dict(Counter(r["live"] for r in rows)))
al = [r for r in rows if r['alerts']]
print(f'警报票: {len(al)} (CROSS {sum(1 for r in al if "CROSS_TRIGGER" in r["alerts"])}, NEAR {sum(1 for r in al if "NEAR_TRIGGER" in r["alerts"])}, BREAKOUT {sum(1 for r in al if "BAND_BREAKOUT" in r["alerts"])}, RS {sum(1 for r in al if "RS_VS_INDEX" in r["alerts"])})')
print()

# ---- 警报明细 (全列) ----
print('========== 警报票明细 ==========')
for r in al:
    print(f"[{r['p3']:.4f}] {r['stock']} {r['name']} | {r['tier'][:7]} | {r['px']} ({r['pct']:+.2f}%) | 带[{r['bl']},{r['bh']}] | live={r['live']} | {','.join(r['alerts'])} | exit_d={r['exit_d']:+.1%}")

# 保存
out = ROOT / f'data/r2/daily_update/intraday_p3rank_{time.strftime("%H%M")}.json'
out.write_text(json.dumps({'base_day': DAY, 'mkt_pct': mkt_pct, 'n': len(rows), 'n_missing': len(missing),
                           'missing': missing, 'n_no_price': len(no_price), 'no_price': no_price,
                           'rows': rows}, ensure_ascii=False, indent=1))
print()
print('saved:', out)

# ---- md 输出 ----
tl = {'CONFIRM_CANDIDATE': 'CONFIRM', 'RISK_HOLD': 'RISK_HOLD'}
lines = [
    f"# 盘中轻扫 190池（新P3口径 {time.strftime('%H:%M')} 快照，基日 {DAY}）",
    "",
    f"- 大盘上证: **{mkt_pct:+.2f}%** | 实时报价 {len(rows)}/{len(codes)} | 缺失 {len(missing)} | 无价 {len(no_price)}",
    f"- P3档位: " + ' / '.join(f"{k}×{v}只" for k, v in sorted(p3_dist.items(), reverse=True)),
    f"- 实时状态: " + ' / '.join(f"{k}×{v}" for k, v in Counter(r['live'] for r in rows).items()),
    "",
    "| # | P3目标 | 代码 | 名称 | Tier | HL | 现价 | 涨跌% | 带下沿 | 带上沿 | 实时位 | 距触发线 | 警报 |",
    "|---|--------|------|------|------|----|------|-------|--------|--------|--------|----------|------|",
]
for i, r in enumerate(rows, 1):
    warn = ','.join(r['alerts']) if r['alerts'] else '—'
    lines.append(f"| {i} | {r['p3']:.4f} | {r['stock']} | {r['name']} | {tl.get(r['tier'], r['tier'])} | {'✓' if r['hl'] else '✗'} | "
                 f"{r['px']} | {r['pct']:+.2f}% | {r['bl']} | {r['bh']} | {r['live']} | {r['exit_d']*100:+.1f}% | {warn} |")
md = ROOT / f'data/r2/shadow/intraday_p3rank_{time.strftime("%H%M")}.md'
md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('md:', md)