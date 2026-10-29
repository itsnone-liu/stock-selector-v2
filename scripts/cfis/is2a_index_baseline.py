#!/usr/bin/env python3
"""Join existing frozen CSI All-Share closes to CF-IS observation weeks.
No fetching, no filling missing index weeks; third-party source != official feed.
"""
import argparse
import csv
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(weeks, index_rows):
    closes = {}
    for r in index_rows:
        d = date.fromisoformat(r['trade_date'])
        if d in closes:
            raise ValueError(f'duplicate index date: {d}')
        c = float(r['close'])
        if c <= 0:
            raise ValueError('nonpositive index close')
        closes[d] = c
    days = sorted(closes)
    out = []
    for w in weeks:
        end = date.fromisoformat(w['week_end'][:4] + '-' + w['week_end'][4:6] + '-' + w['week_end'][6:])
        iso = end.isocalendar()
        start = date.fromisocalendar(iso.year, iso.week, 1)
        prev = [d for d in days if d < start]
        obs = [d for d in days if start <= d <= end]
        # Conservative guard: never bridge a months-long hole as one weekly return.
        # A long holiday may be conservatively excluded; not falsely treated as known.
        complete = bool(prev and obs and obs[-1] == end
                        and (obs[0] - prev[-1]).days <= 14
                        and all((b - a).days <= 14 for a, b in zip(obs, obs[1:])))
        out.append({
            'week': w['week'], 'week_end': w['week_end'],
            'index': '000985 CSI All-Share',
            'index_last_date': obs[-1].isoformat() if obs else '',
            'index_days': len(obs),
            'index_week_return': closes[obs[-1]] / closes[prev[-1]] - 1 if complete else '',
            'coverage_status': 'ENDPOINT_AVAILABLE' if complete else 'MISSING_OR_PARTIAL',
            'provenance': 'frozen Tencent close series; not an official vendor feed',
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--weekly', default=str(ROOT / 'data/cfis/weekly_full_202201_202610.csv'))
    ap.add_argument('--index', default=str(ROOT / 'docs/phase_i/evidence/market_index_000985.json'))
    ap.add_argument('--out', default=str(ROOT / 'data/cfis/is2a_index_baseline.csv'))
    args = ap.parse_args()
    with open(args.weekly) as f:
        weeks = list(csv.DictReader(f))
    with open(args.index) as f:
        series = json.load(f)['rows']
    rows = build(weeks, series)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(f'index weeks {sum(r["coverage_status"] == "ENDPOINT_AVAILABLE" for r in rows)}/{len(rows)}; no fill for missing weeks')


if __name__ == '__main__':
    main()
