#!/usr/bin/env python3
"""102 只 IN_SUPPORT+0.9（昨收口径）的实时体检：今天还站得住带内的有几只。"""
import json, re, time, urllib.request
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
day = '2026-10-08'
snap = json.load(open(ROOT / f'data/r2/scans/current_scan_{day}.json'))
shadow = json.load(open(ROOT / f'data/r2/shadow/shadow_{day}.json'))
sids = {r['stock'] for r in shadow['rows']}
sel = [c for c in snap['cards'] if c['stock'] in sids and c.get('capital_support', {}).get('support_state') == 'IN_SUPPORT' and c.get('confidence') == 0.9]
meta = {r['stock']: r for r in shadow['rows']}

def market(code):
    return 'sh' if code.startswith(('6', '9')) else ('bj' if code[0] in '48' else 'sz')

q = {}
codes = [c['stock'] for c in sel]
for i in range(0, len(codes), 60):
    batch = codes[i:i+60]
    url = 'http://qt.gtimg.cn/q=' + ','.join(f'{market(c)}{c}' for c in batch)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    s = urllib.request.urlopen(req, timeout=15).read().decode('gbk', errors='ignore')
    for line in s.split(';'):
        if '~' not in line: continue
        f = line.split('~')
        try:
            q[f[2]] = {'name': f[1], 'price': float(f[3]), 'pct': float(f[32]) if f[32] else 0.0}
        except (ValueError, IndexError):
            pass
    time.sleep(0.4)

rows = []
for c in sel:
    t = q.get(c['stock'])
    if not t or t['price'] <= 0:
        rows.append({'stock': c['stock'], 'name': t.get('name', '—') if t else '—', 'price': None, 'err': 'missing'})
        continue
    bl = c['capital_support']['cost_band_low']; bh = c['capital_support']['cost_band_high']
    trig = bl * 0.95
    px = t['price']
    if px >= bh: ss = 'ABOVE_SUPPORT(live)'
    elif px >= bl: ss = 'IN_SUPPORT(live)'
    else: ss = 'UNDERCUT(live)'
    alert = 'CROSS_TRIGGER' if px < trig else ('NEAR_TRIGGER' if px/trig-1 < 0.02 else '—')
    rows.append({'stock': c['stock'], 'name': t['name'], 'price': px, 'pct': t['pct'],
                 'bl': bl, 'bh': bh, 'ss': ss, 'alert': alert,
                 'exit_d': px/trig-1, 'tier': c['decision']['decision_tier'], 'hl': c['decision'].get('higher_low')})

from collections import Counter
print('实时状态分布:', Counter(r['ss'] for r in rows))
print('警报分布:', Counter(r['alert'] for r in rows))
still = [r for r in rows if r['ss'] == 'IN_SUPPORT(live)']
undercut = [r for r in rows if r['ss'] == 'UNDERCUT(live)']
above = [r for r in rows if r['ss'] == 'ABOVE_SUPPORT(live)']
print(f"\n实时仍站带内: {len(still)} 只 | 已破带: {len(undercut)} 只 | 站上带: {len(above)} 只")

# 破带且接近/触发退出线的
warn = [r for r in rows if r['alert'] != '—']
print(f"\n实时已触发警报 {len(warn)} 只:")
for r in sorted(warn, key=lambda x: x['exit_d'])[:15]:
    print(f"  {r['stock']} {r['name']} {r['price']} ({r['pct']:+.2f}%) {r['alert']} exit_d={r['exit_d']:+.1%} {r['tier']}")

out = ROOT / f'data/r2/shadow/insup09_live_check_{time.strftime("%H%M")}.json'
out.write_text(json.dumps({'rows': rows, 'n_still': len(still), 'n_undercut': len(undercut), 'n_above': len(above)}, ensure_ascii=False, indent=1))
print('\nsaved:', out)