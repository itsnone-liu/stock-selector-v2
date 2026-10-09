#!/usr/bin/env python3
"""给 shadow md 补股票名称：腾讯 qt.gtimg.cn 批量拉取（每批60）。"""
import json, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
day = sys.argv[1] if len(sys.argv) > 1 else '2026-10-08'
md_path = ROOT / f'data/r2/shadow/shadow_{day}_top190.md'
shadow = json.load(open(ROOT / f'data/r2/shadow/shadow_{day}.json'))

def market(code):
    return 'sh' if code.startswith(('6', '9')) else 'sz'

codes = [r['stock'] for r in shadow['rows']]
names = {}
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

missing = [c for c in codes if c not in names]
print(f'fetched {len(names)}/{len(codes)} names; missing: {missing[:10]}')

text = md_path.read_text(encoding='utf-8')
for c, n in names.items():
    text = text.replace(f'| {c} | — |', f'| {c} | {n} |')
md_path.write_text(text, encoding='utf-8')

# 置信度从 current_scan 再核对一遍首行
snap = json.load(open(ROOT / f'data/r2/scans/current_scan_{day}.json'))
conf = {c['stock']: c.get('confidence') for c in snap['cards']}
print('top3 names:', [names.get(r['stock']) for r in shadow['rows'][:3]])
print('OK updated:', md_path)