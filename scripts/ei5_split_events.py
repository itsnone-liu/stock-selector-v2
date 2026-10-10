#!/usr/bin/env python3
"""EI-5P 除权事件表刷新（每晚 R2 A 步之后跑，ei5_cron.sh labels 开头调用）。

扫主系统每日档 data/cd/daily_fullmarket/<code>.json.gz 的 adjust_factor_model_derived
相邻跳变，|f_i/f_{i-1} - 1| > 1% 记为除权事件（>5% 为送转大跳、实质影响量纲；
1%~5% 多为小额分红，量纲影响 <5% 但同样记录备查）。

事件表 data/r2/ei5/split_events.json：累积不删，code+date 去重。
用法: ei5_split_events.py [--day <T>]   # --day 仅写入 refreshed_day 字段，便于审计
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / 'data/cd/daily_fullmarket'
OUT = ROOT / 'data/r2/ei5/split_events.json'
THRESH = 0.01          # 记录阈值 1%
MATERIAL = 0.05        # 实质影响量纲阈值 5%（写入 jump 分级用）


def scan_all():
    events = []
    files = sorted(DAILY.glob('*.json.gz'))
    for i, p in enumerate(files):
        code = p.name.split('.')[0]
        try:
            j = json.loads(gzip.decompress(p.read_bytes()))
            dates, fac = j.get('dates'), j.get('adjust_factor_model_derived')
            if not dates or not fac or len(dates) != len(fac):
                continue
            for k in range(1, len(fac)):
                fb, fa = fac[k - 1], fac[k]
                if not fb or fa is None:
                    continue
                jump = fa / fb
                if abs(jump - 1.0) > THRESH:
                    events.append({'code': code, 'date': dates[k],
                                   'f_before': round(float(fb), 6), 'f_after': round(float(fa), 6),
                                   'jump': round(float(jump), 4),
                                   'material': bool(abs(jump - 1.0) > MATERIAL)})
        except Exception:
            continue
        if (i + 1) % 1000 == 0:
            print(f'  ...{i + 1}/{len(files)}', file=__import__('sys').stderr)
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default='')
    a = ap.parse_args()
    t0 = time.time()
    new = scan_all()
    old = []
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text()).get('events') or []
        except Exception:
            old = []
    seen = {(e['code'], e['date']) for e in old}
    merged = list(old)
    n_add = 0
    for e in new:
        if (e['code'], e['date']) not in seen:
            merged.append(e)
            seen.add((e['code'], e['date']))
            n_add += 1
    merged.sort(key=lambda e: (e['date'], e['code']))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {'refreshed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
           'refreshed_day': a.day or time.strftime('%Y-%m-%d'),
           'thresh': THRESH, 'material_thresh': MATERIAL,
           'n_events': len(merged),
           'n_material': sum(1 for e in merged if e.get('material')),
           'events': merged}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(json.dumps({'status': 'ok', 'scanned': len(list(DAILY.glob('*.json.gz'))),
                      'new': n_add, 'total': len(merged),
                      'n_material': doc['n_material'], 'elapsed_s': round(time.time() - t0, 1)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
