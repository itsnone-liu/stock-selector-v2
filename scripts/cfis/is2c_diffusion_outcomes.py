#!/usr/bin/env python3
"""Frozen independent-index monthly outcomes; never alters entry/node inputs.

TDX dates are a source-consistency check, not an official exchange calendar.
Only COMPLETE windows have metrics; no partial-window substitutes or filling.
"""
import argparse
import calendar
import csv
import json
import math
from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))
FIELDS = ['episode_id', 'arm', 'week', 'assessment_at', 'horizon_months',
          'status', 'entry_date', 'entry_open', 'target_date', 'end_date',
          'return', 'MAE', 'MFE', 'first_10pct_days', 'hit_10pct', 'observed_days']


def addmonth(day, months):
    """Add calendar months, clamping the day to the target month end."""
    month = day.year * 12 + day.month - 1 + months
    year, month = divmod(month, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def assessment(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('assessment_at must have a timezone')
    return parsed.astimezone(TZ)


def dated_map(rows, key):
    result = {}
    for row in rows:
        day = date.fromisoformat(str(row[key]))
        if day in result:
            raise ValueError(f'duplicate {key}: {day}')
        result[day] = row
    return result


def valid_bar(row):
    try:
        o, h, l, c = (float(row[k]) for k in ('open', 'high', 'low', 'close'))
        return all(math.isfinite(v) and v > 0 for v in (o, h, l, c)) and l <= min(o, c) <= max(o, c) <= h
    except (KeyError, TypeError, ValueError):
        return False


def build(entries, index_rows, tdx_rows, horizons=(3, 6, 12)):
    """Return one outcome per entry/horizon, in input order (ratios, not %).

    Entry is the first *recorded* 09:30 open strictly after assessment, even
    when that record is invalid: never skip a bad bar to choose a nicer entry.
    A missing predecessor cannot establish the entry-gap bound and is rejected.
    Noncomplete windows leave all six outcome metrics blank. hit_10pct is 0
    only for a complete non-hit; successful wait counts entry day as day one.
    """
    horizons = tuple(horizons)
    if any(not isinstance(h, int) or h <= 0 for h in horizons):
        raise ValueError('horizons must be positive integer months')
    prices = dated_map(index_rows, 'trade_date')
    days = sorted(prices)
    opens = [datetime.combine(d, time(9, 30), TZ) for d in days]
    tdx_days = sorted(dated_map(tdx_rows, 'date'))
    output = []
    for entry in entries:
        at = assessment(entry['assessment_at'])
        pos = bisect_right(opens, at)
        entry_status = None
        day = days[pos] if pos < len(days) else None
        if day is None:
            entry_status = 'NO_ENTRY'
        elif opens[pos] - at > timedelta(days=7):
            entry_status = 'ENTRY_LAG'
        elif pos == 0:
            entry_status = 'NO_PREVIOUS_PRICE'
        elif (day - days[pos - 1]).days > 14:
            entry_status = 'ENTRY_PRICE_GAP'
        elif not valid_bar(prices[day]):
            entry_status = 'INVALID_PRICE'
        for months in horizons:
            row = dict.fromkeys(FIELDS, '')
            row.update({k: entry.get(k, '') for k in ('episode_id', 'arm', 'week', 'assessment_at')})
            row['horizon_months'] = months
            if day is not None:
                row.update(entry_date=day.isoformat(), entry_open=prices[day].get('open', ''),
                           target_date=addmonth(day, months).isoformat())
            if entry_status:
                row['status'] = entry_status
                output.append(row)
                continue
            target = addmonth(day, months)
            if target > days[-1]:
                row['status'] = 'RIGHT_CENSORED'
                output.append(row)
                continue
            endpos = bisect_right(days, target) - 1
            end = days[endpos]
            row['end_date'] = end.isoformat()
            path = days[pos:endpos + 1]
            expected = tdx_days[bisect_left(tdx_days, day):bisect_right(tdx_days, end)]
            if (target - end).days > 7:
                row['status'] = 'ENDPOINT_LAG'
            elif path != expected:
                row['status'] = 'TDX_DATE_MISMATCH'
            elif any((b - a).days > 14 for a, b in zip(path, path[1:])):
                row['status'] = 'PATH_PRICE_GAP'
            elif not all(valid_bar(prices[d]) for d in path):
                row['status'] = 'INVALID_PRICE'
            else:
                opening = float(prices[day]['open'])
                hit = next((i for i, d in enumerate(path, 1)
                            if Decimal(str(prices[d]['close'])) >=
                            Decimal(str(prices[day]['open'])) * Decimal('1.10')), None)
                row.update(status='COMPLETE', **{
                    'return': float(prices[end]['close']) / opening - 1,
                    'MAE': min(0.0, min(float(prices[d]['low']) for d in path) / opening - 1),
                    'MFE': max(0.0, max(float(prices[d]['high']) for d in path) / opening - 1),
                    'first_10pct_days': hit if hit is not None else '',
                    'hit_10pct': int(hit is not None), 'observed_days': len(path)})
            output.append(row)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entries', type=Path, default=ROOT / 'data/cfis/is2c_diffusion_entries.csv')
    parser.add_argument('--index', type=Path, default=ROOT / 'docs/phase_i/evidence/market_index_000985.json')
    parser.add_argument('--tdx', type=Path, default=ROOT / 'data/cfis/is2c_turnover_daily.csv')
    parser.add_argument('--out', type=Path, default=ROOT / 'data/cfis/is2c_diffusion_outcomes.csv')
    args = parser.parse_args()
    with args.entries.open(encoding='utf-8', newline='') as stream:
        entries = list(csv.DictReader(stream))
    with args.index.open(encoding='utf-8') as stream:
        index = json.load(stream)['rows']
    with args.tdx.open(encoding='utf-8', newline='') as stream:
        tdx = list(csv.DictReader(stream))
    rows = build(entries, index, tdx)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f'{len(entries)} entries; {len(rows)} outcomes; '
          f'{sum(r["status"] == "COMPLETE" for r in rows)} complete')


if __name__ == '__main__':
    main()
