#!/usr/bin/env python3
"""R2 crossval trend viewer — day-by-day factor cross stats for validation.

Reads data/r2/daily_update/crossval_history.jsonl (written by daily_report.py).
Usage:
  python src/r2/crossval_trend.py --dim T2                 # up_ratio by default
  python src/r2/crossval_trend.py --dim state --metric mean --days 30
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HP = ROOT / 'data/r2/daily_update/crossval_history.jsonl'
DIMS = ('band_pos', 'support_state', 'state', 'conf', 'E3', 'T2', 'T3')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dim', default='T2', choices=DIMS)
    ap.add_argument('--metric', default='up_ratio', choices=('mean', 'median', 'up_ratio'))
    ap.add_argument('--days', type=int, default=15)
    ap.add_argument('--md', action='store_true', help='markdown table output')
    a = ap.parse_args()

    rows = [json.loads(ln) for ln in HP.read_text().splitlines() if ln.strip()]
    rows.sort(key=lambda r: r['day'])
    rows = rows[-a.days:]
    days = [r['day'] for r in rows]

    cells = {}
    for r in rows:
        for grp, d in (r.get(a.dim) or {}).items():
            cells.setdefault(grp, {})[r['day']] = d

    def val(d):
        x = d.get(a.metric)
        return f'{x:+.4f}' if isinstance(x, float) else '-'

    sep = '|' if a.md else ''
    hdr_joiner = '|' if a.md else '  '
    line = '-' * 70
    out = [f'{a.dim} / {a.metric}' + (f'  (最近{len(days)}天)' if len(days) != a.days else '')]
    if a.md:
        out.append('')
        out.append('| 分组 | ' + ' | '.join(d[5:] for d in days) + ' |')
        out.append('|' + '---|' * (len(days) + 1))
    else:
        out.append(line)
        out.append('分组'.ljust(16) + ''.join(d[5:].rjust(10) for d in days))
        out.append(line)

    # rank groups by best recent metric value
    def best(g):
        vs = [d.get(a.metric) for d in cells[g].values() if isinstance(d.get(a.metric), float)]
        return max(vs) if vs else -9e9

    for g in sorted(cells, key=best, reverse=True):
        if a.md:
            cells_row = ' | '.join(val(cells[g].get(d, {})) for d in days)
            ns = ' / '.join(str(cells[g][d].get('n')) for d in days if d in cells[g])
            out.append(f'| {g} | {cells_row} |')
            if ns:
                pass
        else:
            out.append(str(g).ljust(16) + ''.join(val(cells[g].get(d, {})).rjust(10) for d in days))
            ns = [str(cells[g][d].get('n')) for d in days if d in cells[g]]
            out.append('  n='.ljust(16) + ''.join((cells[g].get(d, {}).get('n', '-') if d in cells[g] else '-').__str__().rjust(10) for d in days))
    if not a.md:
        out.append(line)
    out.append('')
    out.append('pool mean_pct: ' + '  '.join(f"{r['day'][5:]}:{r.get('pool', {}).get('mean_pct')}" for r in rows))
    out.append('pool up_ratio: ' + '  '.join(f"{r['day'][5:]}:{r.get('pool', {}).get('up_ratio')}" for r in rows))
    print('\n'.join(out))


if __name__ == '__main__':
    main()
