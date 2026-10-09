#!/usr/bin/env python3
"""88 只实时仍站带内 → md。基于 live_check 结果，实时口径。"""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path('/root/project/workspace/stock-selector-v2')
check = json.load(open(ROOT / 'data/r2/shadow/insup09_live_check_1156.json'))
rows = [r for r in check['rows'] if r['ss'] == 'IN_SUPPORT(live)']
# 排序：Tier(CONFIRM→RISK_HOLD) → HL ✓ → 距触发线(远→近)
tier_rank = {'CONFIRM_CANDIDATE': 0, 'RISK_HOLD': 1}
rows.sort(key=lambda r: (tier_rank.get(r['tier'], 9), 0 if r['hl'] else 1, -r['exit_d']))
tl = {'CONFIRM_CANDIDATE': 'CONFIRM', 'RISK_HOLD': 'RISK_HOLD'}

lines = [
    f"# 实时仍站带内 88 只（104只中昨收IN_SUPPORT+0.9口径）",
    "",
    f"- 快照时间：11:56 腾讯实时行情，共 102 只体检 → **带内 88** / 站上带 11 / 破带 3",
    f"- 口径：昨收 IN_SUPPORT + 置信 0.9（190 影子池内），实时价仍 ≥ 带下沿",
    f"- 排序：Tier（CONFIRM→RISK_HOLD）→ HL ✓ → 距触发线（安全垫厚→薄）",
    "",
    "| # | 代码 | 名称 | Tier | HL | 实时价 | 涨跌% | 带下沿 | 带上沿 | 距触发线 | 距退出 |",
    "|---|------|------|------|----|--------|-------|--------|--------|----------|--------|",
]
for i, r in enumerate(rows, 1):
    trig = r['bl'] * 0.95
    dist_trig = (r['price'] / trig - 1) * 100
    lines.append(
        f"| {i} | {r['stock']} | {r['name']} | {tl.get(r['tier'], r['tier'])} | {'✓' if r['hl'] else '✗'} | "
        f"{r['price']} | {r['pct']:+.2f}% | {r['bl']} | {r['bh']} | {dist_trig:+.1f}% | {r['exit_d']*100:+.1f}% |"
    )
out = ROOT / 'data/r2/shadow/insup09_live_88.md'
out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'OK: {out} ({len(rows)} rows)')
for r in rows[:6]:
    print(' ', r['stock'], r['name'], tl.get(r['tier']), r['price'], f"{r['pct']:+.2f}%", f"{r['exit_d']*100:+.1f}%")