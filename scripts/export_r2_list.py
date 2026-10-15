#!/usr/bin/env python3
"""出 R2 正式选股名单 md + 伤口交集审计（2026-10-14）。"""
import json, re, struct, time, urllib.request
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
import sys
DAY = sys.argv[1] if len(sys.argv) > 1 else '2026-10-14'
TDX = Path('/root/tdx_data/vipdoc')

shadow = json.load(open(ROOT / f'data/r2/shadow/shadow_{DAY}.json'))
upd = json.load(open(ROOT / f'data/r2/daily_update/update_{DAY}.json'))
rows = shadow['rows']

ACT = {'CONFIRM_CANDIDATE': 'C', 'RISK_HOLD': 'R', 'BUILD': 'B'}
act = [r for r in rows if r['tier'] in ACT]

# ---- 1. 伤口交集审计 ----
wound = {}
for code, kind, det in upd['tdx_mismatch']:
    wound.setdefault(code, kind)
inter = [r for r in act if r['stock'] in wound]
print(f'[审计] mismatch 清单 {len(wound)} 只（{sum(1 for v in wound.values() if v=="tdx_mismatch")} tdx_bar_not_fetched + '
      f'{sum(1 for v in wound.values() if v=="overlap_qfq_mismatch")} overlap_qfq）')
print(f'[审计] 行动名单 {len(act)} 只，带伤 {len(inter)} 只: '
      + ', '.join(f"{r['stock']}({ACT[r['tier']]}/{wound[r['stock']]})" for r in inter))

# ---- 2. px 新鲜度审计（vs TDX 当日收盘）----
def tdx_close(code):
    mkt = 'sh' if code.startswith(('6', '9')) else ('bj' if code.startswith(('4', '8')) else 'sz')
    p = TDX / mkt / 'lday' / f'{code}.day'
    if not p.exists():
        return None
    b = p.read_bytes()[-32:]
    d, o, h, l, c, amt, vol, _ = struct.unpack('<IIIIIfII', b)
    return str(d), c / 100.0

stale = []
for r in act:
    tc = tdx_close(r['stock'])
    if tc and tc[0] == DAY.replace('-', '') and abs(tc[1] - r['px']) > 0.011:
        stale.append((r['stock'], r['px'], tc[1]))
print(f'[审计] 行动名单 px 与 TDX 10-14 收盘不符: {len(stale)} 只 {stale[:8]}')

# ---- 3. 批量补名称 ----
def mkt(c):
    return 'sh' if c.startswith(('6', '9')) else ('bj' if c.startswith(('4', '8')) else 'sz')

codes = [r['stock'] for r in act]
names = {}
for i in range(0, len(codes), 60):
    q = ','.join(f'{mkt(c)}{c}' for c in codes[i:i+60])
    req = urllib.request.Request(f'https://qt.gtimg.cn/q={q}', headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=15).read().decode('gbk', errors='ignore')
    for m in re.finditer(r'v_(\w+)="([^"]*)"', data):
        f = m.group(2).split('~')
        if len(f) > 1:
            names[m.group(1)[2:]] = f[1]
    time.sleep(0.25)
miss = [c for c in codes if c not in names or not names[c]]
print(f'[名称] {len(names)}/{len(codes)}，缺失: {miss[:10]}')

# ---- 4. 写 md（按 p3_final 降序分组，组内保持 shadow 原序）----
GRP_ORDER = [0.25, 0.1875, 0.125, 0.0938, 0.0625, 0.05]
groups = {g: [] for g in GRP_ORDER}
for r in act:
    groups.setdefault(round(r['p3_final'], 4), []).append(r)

n_qfq = sum(1 for v in wound.values() if v == 'overlap_qfq_mismatch')
n_tdx = sum(1 for v in wound.values() if v == 'tdx_mismatch')
head = (f"# {DAY} 盘后选股名单·正式版（sealed {shadow['sealed_sha256']}）\n\n"
        f"环境 {shadow['regime_grp']}（R_DEPRESSED），推荐仓位已含 0.5 乘数；⭐=q5 拥挤档（距5%分位成本带≤3%）；"
        f"数据基准={DAY} 收盘价；⚠️=ST/退市风险股；共 {len(act)} 只\n\n"
        f"数据口径：A 步扩窗修复后重跑，tdx_bar_not_fetched 仅 {n_tdx} 只（000007/000411，非名单内）；"
        f"另有 {n_qfq} 只除权股 qfq 重定基停在昨日（非名单内，见下）\n")

lines = [head]
for g in GRP_ORDER:
    if g not in groups or not groups[g]:
        continue
    star = '⭐' if g in (0.1875, 0.0938) else ''
    lines.append(f"## 仓位 {g}{star}（{len(groups[g])} 只）\n")
    for r in groups[g]:
        nm = names.get(r['stock'], '')
        flag = ' ⚠️' if ('ST' in nm or '退' in nm) else ''
        lines.append(f"- {r['stock']} {nm}{flag}({ACT[r['tier']]}) px {r['px']}  dtc {r['dtc']*100:+.1f}%")
    lines.append('')

# 伤口点名
if inter:
    lines.append(f"\n## ⚠️ 带伤行动票（{len(inter)} 只，tier/band 为 T-1 近似）\n")
    for r in inter:
        lines.append(f"- {r['stock']} {names.get(r['stock'],'')}({ACT[r['tier']]}) {wound[r['stock']]}")
    lines.append('')
if stale:
    lines.append(f"\n## ⚠️ px 与 TDX 收盘不符（{len(stale)} 只）\n")
    for c, px, tc in stale:
        lines.append(f"- {c} shadow {px} vs TDX {tc}")
    lines.append('')

out = ROOT.parent.parent / f'/root/选股名单_{DAY}.md'
Path(f'/root/选股名单_{DAY}.md').write_text('\n'.join(lines), encoding='utf-8')
print(f'[写出] /root/选股名单_{DAY}.md  总行数 {len(lines)}')
print('[档位小计]', {g: len(groups[g]) for g in GRP_ORDER if groups.get(g)}, '合计', sum(len(groups[g]) for g in GRP_ORDER))
print('[除权清单]', sorted(c for c, v in wound.items() if v == 'overlap_qfq_mismatch'))