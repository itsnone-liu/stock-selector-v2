#!/usr/bin/env python3
"""CF-1A closure evidence assembler — 汇总五时点采样+修订复查+覆盖统计 → 闭合报告数据节

Usage: python3 scripts/cf/assemble_closure.py
Reads:  docs/cf/cf1a_probes/release_time/*.json, rev_baseline_20261015_evening.json, coverage_report.json
Output: docs/cf/cf1a_probes/closure_evidence.md
纯汇总，不产生任何市场结论 (G4-G7 clean)。
"""
import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = os.path.join(ROOT, 'docs', 'cf', 'cf1a_probes')
OUT = os.path.join(P, 'closure_evidence.md')

SLOT_ORDER = ['morning_0830', 'intraday_1100', 'tail_1430', 'post_1530', 'evening',
              'evening_replay_check', 'evening_revcheck_T15', 'adhoc']


def h16(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_probes():
    out = {}
    for f in sorted(glob.glob(os.path.join(P, 'release_time', '*.json'))):
        d = json.load(open(f))
        out[os.path.basename(f)] = d
    return out


def first_available(probe_files, T, field):
    """field 在 T 日各时点首次 ok 且 rows>0 的时点"""
    seen = []
    for fn in sorted(probe_files):
        d = probe_files[fn]
        if d['_meta']['T'] != T:
            continue
        slot = d['_meta']['label']
        v = d.get(field) or {}
        seen.append((slot, v.get('ok'), v.get('rows', 0)))
    seen.sort(key=lambda x: SLOT_ORDER.index(x[0]) if x[0] in SLOT_ORDER else 99)
    for slot, ok, rows in seen:
        if ok and rows and rows > 0:
            return slot
    return None


def revcheck(probe_files, baseline):
    """T=20261015 修订复查: evening_revcheck_T15 vs 基线"""
    rc = None
    for fn, d in probe_files.items():
        if d['_meta']['T'] == '20261015' and d['_meta']['label'] == 'evening_revcheck_T15':
            rc = d
    if rc is None:
        return {'status': 'PENDING (等待 10-16 20:05 自动采样)'}
    res = {'queried_at': rc['_meta']['queried_at']}
    for day, key in [('20261014', 'sse_etf_Tm1'), ('20261015', 'sse_etf_T')]:
        b = baseline.get(f'sse_etf_{day}')
        r = rc.get(key) or {}
        if b is None or not r.get('ok') or r.get('rows', 0) == 0:
            res[f'etf_{day}'] = 'MISSING'
            continue
        bh = h16(b)
        res[f'etf_{day}'] = {'baseline_h16': bh, 'replay_h16': r.get('hash16'),
                             'identical': bh == r.get('hash16')}
    bm = str((baseline.get('sse_margin_20261014') or {}).get('融资余额'))
    rm = (rc.get('sse_margin_Tm1') or {}).get('zye')
    res['margin_20261014'] = {'baseline': bm, 'replay': str(rm), 'identical': bm == str(rm)}
    return res


def main():
    probes = load_probes()
    lines = ['# CF-1A 闭合证据（自动汇总）\n']
    lines.append(f'生成: 见文件时间戳 · 输入: release_time/*.json ({len(probes)} 份)\n')

    lines.append('## 发布时点结论（T=20261016 各传感器首次可查时点）\n')
    lines.append('| 传感器 | 首次可查时点 | 说明 |')
    lines.append('|---|---|---|')
    for field, name in [('sse_etf_T', 'SSE ETF 份额(T)'), ('szse_etf_T', 'SZSE ETF 份额(T)'),
                        ('sse_margin_T', 'SSE 两融(T)'), ('szse_margin_T', 'SZSE 两融(T)')]:
        slot = first_available(probes, '20261016', field)
        lines.append(f'| {name} | {slot or "采样未齐"} | {"same-day" if slot and slot not in ("morning_0830",) else "见采样矩阵"} |')
    lines.append('')

    baseline = json.load(open(os.path.join(P, 'rev_baseline_20261015_evening.json')))
    lines.append('## 修订复查（10-15 数据于 10-16 晚重查 vs 基线）\n')
    lines.append('```json\n' + json.dumps(revcheck(probes, baseline), ensure_ascii=False, indent=1, default=str) + '\n```\n')

    cov = os.path.join(P, 'coverage_report.json')
    if os.path.exists(cov):
        c = json.load(open(cov))
        lines.append('## Backfill 覆盖统计\n')
        lines.append('```json\n' + json.dumps(c['modules'], ensure_ascii=False, indent=1, default=str) + '\n```\n')

    lines.append('## 采样矩阵原始状态\n')
    lines.append('| 文件 | T | 时点 | sse_etf_T | sse_margin_T | szse_etf_T | szse_margin_T |')
    lines.append('|---|---|---|---|---|---|---|')
    for fn, d in sorted(probes.items()):
        def st(k):
            v = d.get(k) or {}
            return f"{v.get('rows','-')}{'✅' if v.get('ok') and v.get('rows',0)>0 else '❌'}"
        lines.append(f"| {fn} | {d['_meta']['T']} | {d['_meta']['label']} | {st('sse_etf_T')} | {st('sse_margin_T')} | {st('szse_etf_T')} | {st('szse_margin_T')} |")
    lines.append('')
    open(OUT, 'w').write('\n'.join(lines))
    print('\n'.join(lines[:40]))
    print('...\nsaved:', OUT)


if __name__ == '__main__':
    main()
