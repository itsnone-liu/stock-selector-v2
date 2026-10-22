#!/usr/bin/env python3
"""出 R2 正式选股名单 md + 伤口交集审计。用法: export_r2_list.py <YYYY-MM-DD>"""
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
    p = TDX / mkt / 'lday' / f'{mkt}{code}.day'
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
print(f'[审计] 行动名单 px 与 TDX {DAY} 收盘不符: {len(stale)} 只 {stale[:8]}')

# ---- 3. 批量补名称 ----
import sys as _sys                        # noqa: E402
_sys.path.insert(0, str(ROOT / 'src'))
from r2.tdx_quotes import quotes as _tdx_quotes   # noqa: E402

codes = [r['stock'] for r in act]
_q = _tdx_quotes(codes)                    # 2026-10-21 起 TDX 通道（名称随快照一并返回）
names = {c: _q.get(c, {}).get('name', '') for c in codes}
miss = [c for c in codes if c not in names or not names[c]]
print(f'[名称] {len(names)}/{len(codes)}，缺失: {miss[:10]}')

# ---- 4. 写 md（按 p3_final 降序分组，组内保持 shadow 原序）----
# 档位动态推导（2026-10-22 老刘批准修复）：硬编码 BEAR 档位表在 OTHER(0.75) 环境下会静默丢票
# （0.375 等档不在表内 → 只写出 0.1875 一档 72/558 只，header 仍写"共 558 只"）
GRP_ORDER = sorted({round(r['p3_final'], 4) for r in act}, reverse=True)
# ⭐=q5 拥挤档 = 另一档位值 × 0.75（BEAR: 0.1875/0.0938；OTHER: 0.2812/0.1125）
STAR_G = {v for v in GRP_ORDER if any(abs(round(u * 0.75, 4) - v) < 1e-9 for u in GRP_ORDER)}
groups = {g: [] for g in GRP_ORDER}
for r in act:
    groups.setdefault(round(r['p3_final'], 4), []).append(r)

n_qfq = sum(1 for v in wound.values() if v == 'overlap_qfq_mismatch')
n_tdx = sum(1 for v in wound.values() if v == 'tdx_mismatch')
tdx_codes = sorted(c for c, v in wound.items() if v == 'tdx_mismatch')
qfq_codes = sorted(c for c, v in wound.items() if v == 'overlap_qfq_mismatch')
in_act = {r['stock'] for r in act}

def _brief(codes, k=3):
    if not codes:
        return '无'
    return '/'.join(codes[:k]) + ('…' if len(codes) > k else '')

def _scope(codes, in_list_extra=''):
    hit = [c for c in codes if c in in_act]
    return f'名单内 {_brief(hit)}{in_list_extra}' if hit else '均非名单内'

tdx_txt = (f'tdx_bar_not_fetched {n_tdx} 只（{_brief(tdx_codes)}，{_scope(tdx_codes)}）'
           if n_tdx else 'tdx_bar_not_fetched 0 只')
qfq_txt = (f'另有 {n_qfq} 只除权股 qfq 重定基停在 {DAY} 前一日（{_scope(qfq_codes, "，见下带伤票")}）'
           if n_qfq else '无除权 qfq 错位')
head = (f"# {DAY} 盘后选股名单·正式版（sealed {shadow['sealed_sha256']}）\n\n"
        f"环境 {shadow['regime_grp']}（R_DEPRESSED），推荐仓位已含 0.5 乘数；⭐=q5 拥挤档（距5%分位成本带≤3%）；"
        f"数据基准={DAY} 收盘价；⚠️=ST/退市风险股；共 {len(act)} 只\n\n"
        f"数据口径：A 步扩窗修复后重跑，{tdx_txt}；{qfq_txt}\n")

lines = [head]
for g in GRP_ORDER:
    if g not in groups or not groups[g]:
        continue
    star = '⭐' if g in STAR_G else ''
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
print('[自检] ⭐档合计', sum(len(groups[g]) for g in STAR_G), '应 == shadow counts.q5_reduce', shadow['counts']['q5_reduce'])
print('[除权清单]', sorted(c for c, v in wound.items() if v == 'overlap_qfq_mismatch'))