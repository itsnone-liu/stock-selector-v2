#!/usr/bin/env python3
"""Independent, conservative CF-IS node outcomes on frozen unadjusted index OHLC.

No node mutation, fetching, filling or strategy-return claim. Entry is the first
recorded 09:30 Asia/Shanghai open strictly after assessment (not a later chosen
Monday). A partial entry week is rejected, not rolled forward. Short holiday
weeks need a weekly endpoint AND subsequent-week index evidence; in particular a
Thursday at the data cutoff is not a confirmed complete week. Waiting is counted
in observed trading days, entry day = 1; non-hits have no invented wait duration.
"""
import argparse
import csv
import json
import math
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))
HORIZONS = (4, 8, 12)
FIELDS = ['episode_id', 'stage', 'week', 'assessment_at', 'entry_date',
          'entry_open', 'horizon', 'status', 'return', 'MAE', 'MFE',
          'first_5pct_days', 'hit_5pct', 'entry_week', 'window_start_week',
          'window_end_week', 'window_end_date', 'window_weeks', 'observed_days',
          'wait_status']


def as_date(value):
    s = str(value)
    return date.fromisoformat(s if '-' in s else f'{s[:4]}-{s[4:6]}-{s[6:8]}')


def assessment_time(value):
    # Date-only timestamps lack intraday precision: use the end of that day.
    if len(value) == 10:
        return datetime.combine(as_date(value), time.max, TZ)
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def monday(d):
    return d - timedelta(days=d.weekday())


def week_id(d):
    y, w, _ = d.isocalendar()
    return f'{y}-W{w:02d}'


def build(nodes, weeks, index_rows, horizons=HORIZONS):
    """Return one row per node/horizon; only COMPLETE rows have outcome numbers."""
    bars = {}
    for raw in index_rows:
        d = as_date(raw['trade_date'])
        if d in bars:
            raise ValueError(f'duplicate index date: {d}')
        bar = {k: float(raw[k]) for k in ('open', 'high', 'low', 'close')}
        if (not all(math.isfinite(x) and x > 0 for x in bar.values())
                or bar['low'] > min(bar['open'], bar['close'])
                or bar['high'] < max(bar['open'], bar['close'])):
            raise ValueError(f'invalid OHLC: {d}')
        bars[d] = bar
    days = sorted(bars)
    opens = [datetime.combine(d, time(9, 30), TZ) for d in days]
    weekly = {}
    for raw in weeks:
        key = raw['week']
        if key in weekly:
            raise ValueError(f'duplicate weekly key: {key}')
        end = as_date(raw['week_end'])
        if week_id(end) != key or end.weekday() > 4:
            raise ValueError(f'invalid weekly endpoint: {key} {end}')
        weekly[key] = end
    ordered = sorted(weekly, key=lambda k: weekly[k])
    out = []
    for node in nodes:
        assessment = assessment_time(node['assessment_at'])
        pos = bisect_right(opens, assessment)
        entry = days[pos] if pos < len(days) else None
        initial = ''
        if entry is None:
            initial = 'RIGHT_CENSORED_NO_ENTRY'
        elif ((entry - assessment.date()).days > 7
              or (pos and (entry - days[pos - 1]).days > 14)):
            initial = 'ENTRY_GAP'
        elif week_id(entry) not in weekly:
            initial = 'MISSING_ENTRY_WEEK'
        else:
            first_in_week = next(d for d in days if monday(d) == monday(entry))
            # Entire entry trading week must begin after the assessment. Do not
            # skip a partial entry week to manufacture a later eligible entry.
            if first_in_week != entry or monday(entry) < assessment.date():
                initial = 'INCOMPLETE_ENTRY_WEEK'
        for horizon in horizons:
            if horizon <= 0:
                raise ValueError('horizons must be positive')
            r = dict.fromkeys(FIELDS, '')
            r.update({k: node[k] for k in ('episode_id', 'stage', 'week', 'assessment_at')})
            r.update(horizon=horizon, status=initial, wait_status='NOT_EVALUABLE')
            if entry:
                r.update(entry_date=entry.isoformat(), entry_open=bars[entry]['open'],
                         entry_week=week_id(entry))
            if initial:
                out.append(r)
                continue
            start = ordered.index(week_id(entry))
            selected = ordered[start:start + horizon]
            r.update(window_start_week=selected[0], window_end_week=selected[-1],
                     window_end_date=weekly[selected[-1]].isoformat(),
                     window_weeks=';'.join(selected))
            status = ''
            if len(selected) < horizon:
                status = 'RIGHT_CENSORED_WEEKLY'
            end = weekly[selected[-1]]
            path = [d for d in days if entry <= d <= end]
            # Never silently jump a missing benchmark week that has index data.
            path_keys = {week_id(d) for d in path}
            if path_keys - set(selected):
                status = 'MISSING_WEEKLY'
            for key in selected:
                endpoint = weekly[key]
                obs = [d for d in days if week_id(d) == key]
                if endpoint not in bars:
                    status = ('RIGHT_CENSORED' if not days or endpoint > days[-1]
                              else 'MISSING_ENDPOINT')
                    break
                if obs[-1] != endpoint:
                    status = 'MISSING_ENDPOINT'
                    break
                # A final Thursday is not holiday confirmation. Weekly end
                # labels alone cannot prove the raw daily cutoff is complete.
                if endpoint.weekday() < 4 and days[-1] <= monday(endpoint) + timedelta(days=4):
                    status = 'RIGHT_CENSORED_PARTIAL_WEEK'
                    break
            if any((b - a).days > 14 for a, b in zip(path, path[1:])):
                status = 'INDEX_GAP'
            if any((weekly[b] - weekly[a]).days > 14
                   for a, b in zip(selected, selected[1:])):
                status = 'WEEKLY_GAP'
            if not status:
                opening = bars[entry]['open']
                hit = next((i for i, d in enumerate(path, 1)
                            if bars[d]['close'] >= opening * 1.05), None)
                r.update(status='COMPLETE', observed_days=len(path),
                         **{'return': bars[end]['close'] / opening - 1,
                            'MAE': min(0.0, min(bars[d]['low'] for d in path) / opening - 1),
                            'MFE': max(0.0, max(bars[d]['high'] for d in path) / opening - 1),
                            'first_5pct_days': hit if hit is not None else '',
                            'hit_5pct': int(hit is not None),
                            'wait_status': 'HIT' if hit is not None else 'NOT_REACHED_RIGHT_CENSORED'})
            else:
                r['status'] = status
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nodes', default=str(ROOT / 'data/cfis/is2b_nodes.csv'))
    ap.add_argument('--weekly', default=str(ROOT / 'data/cfis/weekly_full_202201_202610.csv'))
    ap.add_argument('--index', default=str(ROOT / 'docs/phase_i/evidence/market_index_000985.json'))
    ap.add_argument('--out', default=str(ROOT / 'data/cfis/is2b_node_outcomes.csv'))
    args = ap.parse_args()
    with open(args.nodes, encoding='utf-8-sig', newline='') as f:
        nodes = list(csv.DictReader(f))
    with open(args.weekly, encoding='utf-8-sig', newline='') as f:
        weeks = list(csv.DictReader(f))
    with open(args.index, encoding='utf-8') as f:
        index_rows = json.load(f)['rows']
    rows = build(nodes, weeks, index_rows)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f'{len(nodes)} nodes; {len(rows)} outcomes; '
          f'{sum(r["status"] == "COMPLETE" for r in rows)} complete; '
          'actual window weeks are recorded in window_weeks; no partial-period metrics')


if __name__ == '__main__':
    main()
