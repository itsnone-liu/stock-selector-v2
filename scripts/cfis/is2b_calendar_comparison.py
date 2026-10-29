#!/usr/bin/env python3
"""Evidence-scoped comparison only: partial 2024 calendar, NOT all years.

Frozen node/outcome rules are not modified. Only WEEKLY_GAP rows can be
re-evaluated; every other guard is independently checked to avoid masking.
"""
import argparse
import csv
import json
from datetime import timedelta
from pathlib import Path

try:
    from scripts.cfis import is2b_node_outcomes as original
except ModuleNotFoundError:
    import is2b_node_outcomes as original

ROOT = Path(__file__).resolve().parents[2]
METRICS = ('return', 'MAE', 'MFE', 'first_5pct_days', 'hit_5pct',
           'observed_days', 'wait_status')
EXTRA = ['old_status', 'new_status', 'evidence_id', 'comparison_reason'] + [
    'old_' + k for k in METRICS]


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def proven_gap(a, b, recorded, evidence):
    """All missing weekdays STRICTLY inside a gap must be officially closed.

    Recorded daily dates take precedence over a sparse weekly endpoint view.
    Ordinary weekends need no holiday claim; no other year's holiday is inferred.
    """
    intervals = [(original.as_date(x['start']), original.as_date(x['end']))
                 for x in evidence['closed_intervals']]
    d = a + timedelta(days=1)
    while d < b:
        if d.weekday() < 5 and d not in recorded:
            if not any(start <= d <= end for start, end in intervals):
                return False
        d += timedelta(days=1)
    return True


def compare(outcomes, nodes, weeks, index_rows, evidence):
    # Reuse validation and baseline selection, never relax or patch original code.
    horizons = sorted({int(r['horizon']) for r in outcomes})
    baseline = original.build(nodes, weeks, index_rows, horizons=horizons)
    identity = lambda r: (r['episode_id'], r['stage'], r['week'], int(r['horizon']))
    expected = {identity(r): r for r in baseline}
    weekly = {r['week']: original.as_date(r['week_end']) for r in weeks}
    bars = {original.as_date(r['trade_date']): {k: float(r[k]) for k in
            ('open', 'high', 'low', 'close')} for r in index_rows}
    days = sorted(bars)
    results = []
    for source in outcomes:
        row = dict(source)
        row.update(old_status=source['status'], new_status=source['status'],
                   evidence_id='', comparison_reason='UNCHANGED_NON_WEEKLY_GAP')
        row.update({'old_' + k: source[k] for k in METRICS})
        results.append(row)
        if source['status'] != 'WEEKLY_GAP':
            continue
        row['comparison_reason'] = 'REJECTED_OTHER_GUARD_OR_FROZEN_WINDOW'
        ref = expected.get(identity(source))
        frozen = ('assessment_at', 'entry_date', 'entry_open', 'entry_week',
                  'window_start_week', 'window_end_week', 'window_end_date', 'window_weeks')
        if not ref or ref['status'] != 'WEEKLY_GAP' or any(
                str(source[k]) != str(ref[k]) for k in frozen):
            continue
        selected = source['window_weeks'].split(';')
        if len(selected) != int(source['horizon']) or any(k not in weekly for k in selected):
            continue
        entry = original.as_date(source['entry_date'])
        end = original.as_date(source['window_end_date'])
        path = [d for d in days if entry <= d <= end]
        if (not path or path[0] != entry or path[-1] != end
                or {original.week_id(d) for d in path} - set(selected)):
            continue
        # WEEKLY_GAP was last in the old status precedence: do not mask endpoint,
        # weekly coverage, partial-cutoff or right-censoring guards underneath it.
        endpoint_ok = True
        for key in selected:
            endpoint = weekly[key]
            obs = [d for d in days if original.week_id(d) == key]
            if (endpoint not in bars or not obs or obs[-1] != endpoint
                    or (endpoint.weekday() < 4 and days[-1] <=
                        original.monday(endpoint) + timedelta(days=4))):
                endpoint_ok = False
                break
        if not endpoint_ok:
            continue
        gaps = [(a, b) for seq in (path, [weekly[k] for k in selected])
                for a, b in zip(seq, seq[1:]) if (b - a).days > 14]
        if not gaps or not all(proven_gap(a, b, bars, evidence) for a, b in gaps):
            row['comparison_reason'] = 'REJECTED_UNPROVEN_GAP_PARTIAL_CALENDAR'
            continue
        opening = bars[entry]['open']
        hit = next((i for i, d in enumerate(path, 1)
                    if bars[d]['close'] >= opening * 1.05), None)
        row.update(status='COMPLETE', new_status='COMPLETE',
                   evidence_id=evidence['evidence_id'],
                   comparison_reason='RECOVERED_OFFICIAL_PARTIAL_CALENDAR',
                   observed_days=len(path), **{
                       'return': bars[end]['close'] / opening - 1,
                       'MAE': min(0., min(bars[d]['low'] for d in path) / opening - 1),
                       'MFE': max(0., max(bars[d]['high'] for d in path) / opening - 1),
                       'first_5pct_days': hit if hit is not None else '',
                       'hit_5pct': int(hit is not None),
                       'wait_status': 'HIT' if hit is not None else 'NOT_REACHED_RIGHT_CENSORED'})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--outcomes', default=ROOT / 'data/cfis/is2b_node_outcomes.csv')
    ap.add_argument('--nodes', default=ROOT / 'data/cfis/is2b_nodes.csv')
    ap.add_argument('--weekly', default=ROOT / 'data/cfis/weekly_full_202201_202610.csv')
    ap.add_argument('--index', default=ROOT / 'docs/phase_i/evidence/market_index_000985.json')
    ap.add_argument('--evidence', default=ROOT / 'docs/research/cfis/calendar_evidence.json')
    ap.add_argument('--out', default=ROOT / 'data/cfis/is2b_calendar_outcome_comparison.csv')
    args = ap.parse_args()
    with open(args.index, encoding='utf-8') as f:
        index = json.load(f)['rows']
    with open(args.evidence, encoding='utf-8') as f:
        evidence = json.load(f)
    source = read_csv(args.outcomes)
    rows = compare(source, read_csv(args.nodes), read_csv(args.weekly), index, evidence)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(source[0]) + EXTRA)
        writer.writeheader()
        writer.writerows(rows)
    recovered = [r for r in rows if r['old_status'] != r['new_status']]
    print(f'{len(rows)} outcomes; {len(recovered)} recovered; partial calendar NOT all years')
    for r in recovered:
        print({k: r[k] for k in ('episode_id', 'stage', 'week', 'horizon', *METRICS)})


if __name__ == '__main__':
    main()
