#!/usr/bin/env python3
"""190影子池内 IN_SUPPORT + confidence==0.9 的票 → md（含名称，腾讯批量拉取）。"""
import json, re, time, urllib.request
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
day = '2026-10-08'
snap = json.load(open(ROOT / f'data/r2/scans/current_scan_{day}.json'))
shadow = json.load(open(ROOT / f'data/r2/shadow/shadow_{day}.json'))
smeta = {r['stock']: r for r in shadow['rows']}
sids = set(smeta)

sel = []
for c in snap['cards']:
    cs = c.get('capital_support') or {}
    if c['stock'] in sids and cs.get('support_state') == 'IN_SUPPORT' and c.get('confidence') == 0.9:
        sel.append(c)

# 排序：CONFIRM 在前 → HL ✓ 在前 → exit_distance 升序（距退出越远越安全）
tier_rank = {'CONFIRM_CANDIDATE': 0, 'RISK_HOLD': 1, 'BUILD': 2, 'WATCH': 3, 'EXIT': 4}
sel.sort(key=lambda c: (
    tier_rank.get(c['decision']['decision_tier'], 9),
    0 if c['decision'].get('higher_low') else 1,
    -(c.get('capital_support', {}).get('price', 0) / (c['capital_support']['cost_band_low'] * 0.95) - 1)
))

def market(code):
    return 'sh' if code.startswith(('6', '9')) else ('bj' if code[0] in '48' else 'sz')

names = {}
codes = [c['stock'] for c in sel]
for i in range(0, len(codes), 60):
    batch = codes[i:i+60]
    q = ','.join(f'{market(c)}{c}' for c in batch)
    url = f'https://qt.gtimg.cn/q={q}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=15).read().decode('gbk', errors='ignore')
    for m in re.finditer(r'v_(\w+)="([^"]*)"', data):
        f = m.group(2).split('~')
        if len(f) > 1:
            names[m.group(1)[2:]] = f[1]
    time.sleep(0.3)

lines = [
    f"# 190影子池内 IN_SUPPORT 置信0.9（{day}，共{len(sel)}只）",
    "",
    f"- 口径：shadow 池（CONFIRM 85 + RISK_HOLD 105）内，`support_state=IN_SUPPORT` 且 `confidence=0.9`",
    f"- 排序：Tier（CONFIRM→RISK_HOLD）→ HL ✓ → 距退出线距离（远→近）",
    "",
    "| # | 代码 | 名称 | Tier | HL | 收盘 | 带下沿 | 带上沿 | 距退出线 | P3仓位 |",
    "|---|------|------|------|----|------|--------|--------|----------|--------|",
]
tl = {'CONFIRM_CANDIDATE': 'CONFIRM', 'RISK_HOLD': 'RISK_HOLD'}
for i, c in enumerate(sel, 1):
    cs = c['capital_support']; de = c['decision']
    exit_d = c.get('close', cs.get('price', 0)) / (cs['cost_band_low'] * 0.95) - 1
    meta = smeta.get(c['stock'], {})
    lines.append(f"| {i} | {c['stock']} | {names.get(c['stock'], '—')} | {tl.get(de['decision_tier'], de['decision_tier'])} | {'✓' if de.get('higher_low') else '✗'} | {cs.get('price')} | {cs['cost_band_low']} | {cs['cost_band_high']} | {exit_d*100:.1f}% | {meta.get('p3_target', '—')} |")

out = ROOT / f'data/r2/shadow/shadow_{day}_insup_conf09.md'
out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'OK: {out} ({len(sel)} rows)')
print(f'names fetched: {len(names)}/{len(codes)}')
n_c = sum(1 for c in sel if c['decision']['decision_tier'] == 'CONFIRM_CANDIDATE')
n_r = len(sel) - n_c
print(f'CONFIRM: {n_c}, RISK_HOLD: {n_r}')
for c in sel[:8]:
    print(' ', c['stock'], names.get(c['stock']), tl.get(c['decision']['decision_tier']), 'HL' if c['decision'].get('higher_low') else 'noHL')