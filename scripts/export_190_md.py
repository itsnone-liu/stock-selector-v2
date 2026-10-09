#!/usr/bin/env python3
"""导出一日 shadow 池（CONFIRM+RISK_HOLD）为 md，按置信度降序。"""
import json, sys
from pathlib import Path
from datetime import date

ROOT = Path('/root/project/workspace/stock-selector-v2')
day = sys.argv[1] if len(sys.argv) > 1 else '2026-10-08'

shadow = json.load(open(ROOT / f'data/r2/shadow/shadow_{day}.json'))
snap = json.load(open(ROOT / f'data/r2/scans/current_scan_{day}.json'))

want = {'CONFIRM_CANDIDATE', 'RISK_HOLD'}
conf = {c['stock']: c.get('confidence') for c in snap['cards'] if c.get('decision', {}).get('decision_tier') in want}

rows = []
for r in shadow['rows']:
    if r['tier'] in want:
        rows.append({**r, 'confidence': conf.get(r['stock'])})

rows.sort(key=lambda r: (-(r['confidence'] or 0), -r['p3_target'], r['stock']))

tier_label = {'CONFIRM_CANDIDATE': 'CONFIRM', 'RISK_HOLD': 'RISK_HOLD'}
lines = []
lines.append(f"# R2 影子池 {day}（CONFIRM + RISK_HOLD，按置信度降序）")
lines.append("")
lines.append(f"- 池规模：**{len(rows)}** 只（CONFIRM {shadow['confirm']} + RISK_HOLD {shadow['risk_hold']}）")
lines.append(f"- 五日 regime：`{shadow['regime_5d']}`（{shadow['regime_grp']}）｜封存哈希：`{shadow['sealed_sha256'][:16]}…`")
lines.append(f"- 生成：{date.today()} ｜ 排序依据：置信度（confidence）降序，同级按 P3 目标仓位降序")
lines.append("")
lines.append("| # | 代码 | 名称 | Tier | 置信度 | 收盘 | 带下沿 | 带上沿 | HL | 支撑状态 | P3仓位 | 距退出 |")
lines.append("|---|------|------|------|--------|------|--------|--------|----|----------|--------|--------|")
for i, r in enumerate(rows, 1):
    conf_s = f"{r['confidence']:.3f}" if r['confidence'] is not None else "—"
    hl = '✓' if r['higher_low'] else '✗'
    exit_d = f"{r['exit_distance']*100:.1f}%" if r['exit_distance'] is not None else "—"
    lines.append(f"| {i} | {r['stock']} | {r['name'] or '—'} | {tier_label[r['tier']]} | {conf_s} | {r['px_close']} | {r['band_low']} | {r['band_high']} | {hl} | {r['support_state']} | {r['p3_target']} | {exit_d} |")

out = ROOT / f'data/r2/shadow/shadow_{day}_top190.md'
out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'OK: {out} ({len(rows)} rows)')
print('首3条:')
for r in rows[:3]:
    print(' ', r['stock'], r['tier'], r['confidence'], r['p3_target'])