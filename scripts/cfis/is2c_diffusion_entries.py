#!/usr/bin/env python3
"""Frozen IS2C diffusion v1, descriptive market entries (stdlib only).

API: build_features(weeks, turnover_rows, index_rows), build_entries(features),
build(weeks, turnover_rows, index_rows) -> (features, entries). Unknown booleans
are None (empty CSV cells), never false. No A events or future outcomes are read.
"""
import argparse
from bisect import bisect_right
from collections import Counter
import csv
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))
ARMS = ('DIFFUSION', 'AMOUNT_ONLY', 'PRICE_ONLY')
FEATURE_FIELDS = [
    'week', 'week_end', 'assessment_at', 'available_at', 'index_close',
    'ax_breadth', 'previous_ax_breadth', 'amount_count10', 'amount_days',
    'amount_first_date', 'amount_last_date', 'price_previous_high4',
    'current_known', 'previous_known', 'amount_known', 'breadth_known',
    'price_known', 'amount', 'breadth', 'price', 'eligible', 'diffusion',
    'coverage_status', 'detail',
]
ENTRY_FIELDS = ['episode_id', 'arm', 'stage', 'week', 'assessment_at',
                'index_close', 'reason']


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def day(value):
    value = str(value)
    if len(value) == 8 and value.isdigit():
        value = f'{value[:4]}-{value[4:6]}-{value[6:]}'
    return date.fromisoformat(value)


def timestamp(value):
    try:
        t = datetime.fromisoformat(value)
        return t if t.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def next_day(d):
    return datetime.combine(d + timedelta(days=1), time(), TZ)


def weekly_known(row):
    assessed, usable = timestamp(row.get('assessment_at')), timestamp(row.get('usable_at'))
    return bool(assessed and usable
                and str(row.get('availability_unknown')) in ('0', 'False', 'false'))


def unique_rows(rows, key):
    result = {}
    for row in rows:
        d = day(row[key])
        if d in result:
            raise ValueError(f'duplicate {key}: {d}')
        result[d] = row
    return result


def build_features(weeks, turnover_rows, index_rows):
    """One row per frozen observation week, without filling or skipping holes.

    Assessment is the later of the frozen assessment, weekly usable time and
    current TDX availability. Previous unknown weeks are never filled.
    """
    weeks = sorted(weeks, key=lambda r: day(r['week_end']))
    if len({r['week'] for r in weeks}) != len(weeks):
        raise ValueError('duplicate observation week')
    if len({day(r['week_end']) for r in weeks}) != len(weeks):
        raise ValueError('duplicate week_end')
    daily = unique_rows(turnover_rows, 'date')
    prices = unique_rows(index_rows, 'trade_date')
    days = sorted(daily)
    price_days = sorted(prices)
    out = []
    for i, w in enumerate(weeks):
        end = day(w['week_end'])
        assessment = timestamp(w.get('assessment_at'))
        current_window = days[max(0, bisect_right(days, end) - 10):bisect_right(days, end)]
        current_times = [max(next_day(d), timestamp(daily[d].get('available_at')) or next_day(d))
                         for d in current_window]
        if assessment and timestamp(w.get('usable_at')):
            assessment = max([assessment, timestamp(w['usable_at']), next_day(end)] + current_times)
        current_known = weekly_known(w)
        prev = weeks[i - 1] if i else None
        previous_known = bool(prev and weekly_known(prev) and assessment
                              and timestamp(prev['usable_at']) <= assessment
                              and next_day(day(prev['week_end'])) <= assessment
                              and 0 < (end - day(prev['week_end'])).days <= 14)
        reasons = []
        if not current_known:
            reasons.append('CURRENT_WEEK_UNKNOWN_OR_NOT_VISIBLE')
        if not previous_known:
            reasons.append('PREVIOUS_WEEK_UNKNOWN_OR_GAP')
        visible = bool(current_known and previous_known)
        window = days[max(0, bisect_right(days, end) - 10):bisect_right(days, end)]
        amount_values = [number(daily[d].get('amount_yuan')) for d in window]
        ratios = [number(daily[d].get('ratio60')) for d in window]
        td_times = [max(next_day(d), timestamp(daily[d].get('available_at')) or next_day(d))
                    for d in window]
        amount_data_ok = bool(len(window) == 10 and window[-1] == end
                              and all((b - a).days <= 14 for a, b in zip(window, window[1:]))
                              and all(v is not None and v > 0 for v in amount_values)
                              and all(v is not None and v >= 0 for v in ratios)
                              and assessment and all(t <= assessment for t in td_times))
        amount_known = bool(visible and amount_data_ok)
        count = sum(v >= 1.2 for v in ratios) if amount_data_ok else None
        if not amount_data_ok:
            reasons.append('AMOUNT10_INCOMPLETE_INVALID_GAP_OR_NOT_VISIBLE')
        breadth_now = number(w.get('ax_breadth'))
        breadth_prev = number(prev.get('ax_breadth')) if prev else None
        breadth_known = bool(visible and breadth_now is not None and breadth_prev is not None)
        if breadth_now is None or breadth_prev is None:
            reasons.append('BREADTH_MISSING')
        endpoints = [day(r['week_end']) for r in weeks[max(0, i - 4):i + 1]]
        closes = [number(prices.get(d, {}).get('close')) for d in endpoints]
        raw = price_days[bisect_right(price_days, endpoints[0] - timedelta(days=1)):
                         bisect_right(price_days, end)]
        price_data_ok = bool(len(endpoints) == 5 and all(c is not None and c > 0 for c in closes)
                             and all(0 < (b - a).days <= 14 for a, b in zip(endpoints, endpoints[1:]))
                             and all((b - a).days <= 14 for a, b in zip(raw, raw[1:]))
                             and assessment and next_day(end) <= assessment)
        price_known = bool(visible and price_data_ok)
        if not price_data_ok:
            reasons.append('PRICE5_MISSING_INVALID_GAP_OR_NOT_VISIBLE')
        amount = count >= 7 if amount_known else None
        breadth = breadth_now >= .5 and breadth_prev >= .5 if breadth_known else None
        price = closes[-1] > max(closes[:-1]) if price_known else None
        eligible = bool(amount_known and breadth_known and price_known)
        availability = [timestamp(w.get('usable_at'))] + td_times
        if prev:
            availability.append(timestamp(prev.get('usable_at')))
        available = max(t for t in availability if t is not None) if any(availability) else None
        out.append(dict(zip(FEATURE_FIELDS, [
            w['week'], w['week_end'], assessment.isoformat() if assessment else '',
            available.isoformat() if available else '', number(prices.get(end, {}).get('close')),
            breadth_now, breadth_prev, count, len(window),
            window[0].isoformat() if window else '', window[-1].isoformat() if window else '',
            max(closes[:-1]) if price_data_ok else None,
            current_known, previous_known, amount_known, breadth_known, price_known,
            amount, breadth, price, eligible, bool(amount and breadth and price) if eligible else None,
            'ELIGIBLE' if eligible else 'UNKNOWN', ';'.join(reasons) or 'ALL_INPUTS_KNOWN',
        ])))
    return out


def truth(value):
    return value is True or value == 1 or str(value).lower() == 'true'


def build_entries(features):
    """Deduplicate each signal arm independently; any unknown breaks a run.

    ALL_ELIGIBLE is one background row per common week, not an episode arm.
    Stable IDs use arm + first week, unaffected by later appended data.
    """
    active = {arm: False for arm in ARMS}
    entries = []
    for row in features:
        eligible = truth(row['eligible'])
        triggers = {'DIFFUSION': row['diffusion'], 'AMOUNT_ONLY': row['amount'],
                    'PRICE_ONLY': row['price']}
        for arm in (*ARMS, 'ALL_ELIGIBLE'):
            triggered = bool(eligible and (arm == 'ALL_ELIGIBLE' or truth(triggers[arm])))
            if triggered and (arm == 'ALL_ELIGIBLE' or not active[arm]):
                entries.append({
                    'episode_id': f'IS2C-{arm}-{row["week"]}', 'arm': arm, 'stage': arm,
                    'week': row['week'], 'assessment_at': row['assessment_at'],
                    'index_close': row['index_close'],
                    'reason': ('COMMON_ELIGIBLE_WEEK_BACKGROUND' if arm == 'ALL_ELIGIBLE'
                               else f'{arm}_FIRST_TRIGGER_IN_CONTIGUOUS_RUN'),
                })
            if arm != 'ALL_ELIGIBLE':
                active[arm] = triggered
    return entries


def build(weeks, turnover_rows, index_rows):
    features = build_features(weeks, turnover_rows, index_rows)
    return features, build_entries(features)


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--weekly', type=Path, default=ROOT / 'data/cfis/weekly_full_202201_202610.csv')
    ap.add_argument('--turnover', type=Path, default=ROOT / 'data/cfis/is2c_turnover_daily.csv')
    ap.add_argument('--index', type=Path, default=ROOT / 'docs/phase_i/evidence/market_index_000985.json')
    ap.add_argument('--out-dir', type=Path, default=ROOT / 'data/cfis')
    args = ap.parse_args()
    with args.weekly.open() as f:
        weeks = list(csv.DictReader(f))
    with args.turnover.open() as f:
        daily = list(csv.DictReader(f))
    index_rows = json.loads(args.index.read_text())['rows']
    features, entries = build(weeks, daily, index_rows)
    write_csv(args.out_dir / 'is2c_diffusion_features.csv', features, FEATURE_FIELDS)
    write_csv(args.out_dir / 'is2c_diffusion_entries.csv', entries, ENTRY_FIELDS)
    print(json.dumps({'observation_weeks': len(features),
                      'common_eligible_weeks': sum(r['eligible'] for r in features),
                      'entries_by_arm': dict(Counter(r['arm'] for r in entries)),
                      'coverage': dict(Counter(r['coverage_status'] for r in features))}, sort_keys=True))


if __name__ == '__main__':
    main()
