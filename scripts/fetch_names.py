#!/usr/bin/env python3
"""给 shadow md 补股票名称 —— **TDX 名称表**（2026-10-21 起替代腾讯 qt.gtimg.cn）。

名称源 = `r2.tdx_quotes.names_map()`：一次性取 sh+sz 全表（实测 ~6s），按日落盘
缓存 data/r2/tdx_names/names_<ymd>.json，当日缓存命中 0s。键按**交易所+代码**，
避免 000001(上证指数) / 000001(平安银行) 串名（2026-10-21 实测踩过）。

应急回退：`--source tencent`（老链路原样保留，腾讯封 IP 时才需要）。
用法：python3 scripts/fetch_names.py [YYYY-MM-DD] [--source tdx|tencent]
"""
import json, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT / 'src'))

argv = [a for a in sys.argv[1:] if not a.startswith('--')]
day = argv[0] if argv else '2026-10-08'
source = 'tencent' if '--source' in sys.argv and 'tencent' in sys.argv else 'tdx'

md_path = ROOT / f'data/r2/shadow/shadow_{day}_top190.md'
shadow = json.load(open(ROOT / f'data/r2/shadow/shadow_{day}.json'))
codes = [r['stock'] for r in shadow['rows']]


def fetch_tdx(codes):
    """TDX 名称表：{code6: name}。北交所(4/8)前缀 bj 也走同一张表。"""
    from r2.tdx_quotes import names_map, _prefix
    nm = names_map()
    out = {}
    for c in codes:
        pref = _prefix(c)
        n = nm.get(pref + c) or nm.get(c)
        if n:
            out[c] = n
    return out


def fetch_tencent(codes):
    """老链路（腾讯 qt.gtimg.cn，每批60）——仅应急回退。"""
    def market(code):
        return 'sh' if code.startswith(('6', '9')) else 'sz'
    names = {}
    for i in range(0, len(codes), 60):
        batch = codes[i:i + 60]
        q = ','.join(f'{market(c)}{c}' for c in batch)
        req = urllib.request.Request(f'https://qt.gtimg.cn/q={q}',
                                     headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=15).read().decode('gbk', errors='ignore')
        for m in re.finditer(r'v_(\w+)="([^"]*)"', data):
            f = m.group(2).split('~')
            if len(f) > 1:
                names[m.group(1)[2:]] = f[1]
        time.sleep(0.3)
    return names


t0 = time.time()
names = fetch_tdx(codes) if source == 'tdx' else fetch_tencent(codes)
missing = [c for c in codes if c not in names]
print(f'[{source}] fetched {len(names)}/{len(codes)} names in {time.time()-t0:.1f}s; missing: {missing[:10]}')

text = md_path.read_text(encoding='utf-8')
for c, n in names.items():
    text = text.replace(f'| {c} | — |', f'| {c} | {n} |')
md_path.write_text(text, encoding='utf-8')

snap = json.load(open(ROOT / f'data/r2/scans/current_scan_{day}.json'))
conf = {c['stock']: c.get('confidence') for c in snap['cards']}
print('top3 names:', [names.get(r['stock']) for r in shadow['rows'][:3]])
print('OK updated:', md_path)