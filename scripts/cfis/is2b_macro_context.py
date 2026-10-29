#!/usr/bin/env python3
"""NYFed overnight-rate context only; latest vintage, not historical release replay."""
import argparse
import csv
import hashlib
import json
import math
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))
SERIES = ('sofr', 'effr')
URL = 'https://markets.newyorkfed.org/api/rates/{kind}/{series}/search.json?startDate=2021-12-01&endDate=2026-04-30'


def parse(raw, series):
    rows = []
    seen = set()
    for r in raw['refRates']:
        d = date.fromisoformat(r['effectiveDate'])
        value = float(r['percentRate'])
        if d in seen or not math.isfinite(value) or r['type'].lower() != series:
            raise ValueError('duplicate/invalid/type-mismatched rate observation')
        seen.add(d)
        # 7-day lag is an explicit research assumption, not a verified first release.
        rows.append({'date': d, 'value': value,
                     'usable': datetime.combine(d + timedelta(days=7), datetime.min.time(), TZ),
                     'revision': r.get('revisionIndicator', '')})
    if not rows:
        raise ValueError('empty reference-rate response')
    return sorted(rows, key=lambda r: r['date'])


def point(rows, at):
    eligible = [r for r in rows if r['usable'] <= at]
    if not eligible:
        return None
    row = eligible[-1]
    return row if (at.date() - row['date']).days <= 14 else None


def build(features, rates):
    result = []
    for f in features:
        if f.get('current_known') not in ('True', True):
            continue
        at = datetime.fromisoformat(f['assessment_at'])
        if at.tzinfo is None:
            raise ValueError('assessment must have timezone')
        out = dict(week=f['week'], assessment_at=f['assessment_at'],
                   vintage_status='LATEST_VINTAGE_NOT_PIT',
                   timing_policy='ASSUMED_7_CALENDAR_DAY_LAG_MAX_14D_STALENESS')
        for series in SERIES:
            now, before = point(rates[series], at), point(rates[series], at-timedelta(days=28))
            out.update({series+'_date': now['date'].isoformat() if now else '',
                        series+'_percent': now['value'] if now else '',
                        series+'_change_28d_pp': now['value']-before['value'] if now and before else '',
                        series+'_status': 'AVAILABLE_ASSUMPTION' if now else 'MISSING_OR_STALE'})
        out['sofr_minus_effr_pp'] = (out['sofr_percent']-out['effr_percent']
                                    if out['sofr_percent'] != '' and out['effr_percent'] != '' else '')
        out['spread_date_alignment'] = ('SAME_EFFECTIVE_DATE' if out['sofr_date'] and out['sofr_date'] == out['effr_date']
                                        else 'DIFFERENT_OR_MISSING_DATES')
        if out['spread_date_alignment'] != 'SAME_EFFECTIVE_DATE':
            out['sofr_minus_effr_pp'] = ''
        result.append(out)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fetch', action='store_true', help='explicit network refresh; frozen dates')
    args = ap.parse_args()
    rates, manifest = {}, {}
    rawdir = ROOT/'data/cfis/macro_raw'
    rawdir.mkdir(parents=True, exist_ok=True)
    for series in SERIES:
        url = URL.format(kind='secured' if series=='sofr' else 'unsecured', series=series)
        path = rawdir/f'nyfed_{series}_20211201_20260430.json'
        if args.fetch:
            with urllib.request.urlopen(url, timeout=45) as response:
                payload = response.read()
            parse(json.loads(payload), series)  # reject invalid payload before replacing snapshot
            path.write_bytes(payload)
        payload = path.read_bytes()
        rates[series] = parse(json.loads(payload), series)
        manifest[series] = dict(url=url, path=str(path.relative_to(ROOT)), rows=len(rates[series]),
                                sha256=hashlib.sha256(payload).hexdigest(),
                                snapshot_file_mtime_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                                fetched_snapshot_not_historical_vintage=True)
    with open(ROOT/'data/cfis/is2b_features.csv') as f:
        features = list(csv.DictReader(f))
    rows = build(features, rates)
    with open(ROOT/'data/cfis/is2b_macro_context.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    dest = ROOT/'docs/research/cfis/is2b_macro_manifest.json'
    dest.write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'{len(rows)} macro context rows; snapshots recorded in {dest}')


if __name__ == '__main__':
    main()
