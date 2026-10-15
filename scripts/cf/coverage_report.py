#!/usr/bin/env python3
"""CF-1A coverage report — backfill 覆盖统计 (纯本地, 秒级)

Usage: python3 scripts/cf/coverage_report.py
Output: docs/cf/cf1a_probes/coverage_report.json (+stdout 摘要)
"""
import datetime as dt
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, 'data', 'cf', 'raw')
OUT = os.path.join(ROOT, 'docs', 'cf', 'cf1a_probes', 'coverage_report.json')


def d_range(files, suffix):
    dates = []
    for f in files:
        b = os.path.basename(f)[:-len(suffix)]
        d = b[:8]
        if len(d) == 8 and d.isdigit():
            dates.append(d)
    return sorted(dates)


def gaps(dates):
    """相邻数据日之间的自然日缺口(>5天=长缺口, 排除周末)"""
    out = []
    for a, b in zip(dates, dates[1:]):
        da = dt.datetime.strptime(a, '%Y%m%d')
        db = dt.datetime.strptime(b, '%Y%m%d')
        gap = (db - da).days
        if gap > 5:
            out.append([a, b, gap])
    return out


def stat_module(name, csvs, empties):
    d_csv = d_range(csvs, '.csv')
    d_empty = d_range(empties, '.EMPTY')
    res = {
        'data_days': len(d_csv), 'empty_days': len(d_empty),
        'first_data': d_csv[0] if d_csv else None, 'last_data': d_csv[-1] if d_csv else None,
        'first_empty': d_empty[0] if d_empty else None, 'last_empty': d_empty[-1] if d_empty else None,
        'long_gaps': gaps(d_csv),
    }
    # 数据日密集度: 按年统计
    by_year = {}
    for d in d_csv:
        by_year.setdefault(d[:4], 0)
        by_year[d[:4]] += 1
    res['data_days_by_year'] = dict(sorted(by_year.items()))
    return res


def main():
    report = {'generated_at': dt.datetime.now().isoformat(timespec='seconds'), 'modules': {}}
    mods = {
        'sse_etf_scale': 'sse_etf_scale',
        'szse_etf_scale': 'szse_etf_scale',
        'szse_margin': 'szse_margin',
    }
    for key, dirname in mods.items():
        p = os.path.join(RAW, dirname)
        if not os.path.isdir(p):
            report['modules'][key] = {'missing': True}
            continue
        report['modules'][key] = stat_module(key, glob.glob(p + '/*.csv'), glob.glob(p + '/*.EMPTY'))
    # sse_margin 单文件
    p = os.path.join(RAW, 'sse_margin', 'summary_20180102_20261015.csv')
    if os.path.exists(p):
        with open(p) as f:
            lines = f.readlines()
        report['modules']['sse_margin'] = {'rows': len(lines) - 1}
    else:
        report['modules']['sse_margin'] = {'missing': True}

    json.dump(report, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print('saved:', OUT)


if __name__ == '__main__':
    main()
