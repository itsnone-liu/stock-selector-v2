#!/usr/bin/env python3
"""Fixed IS2B v1 exploratory candidates; stdlib, no filling, no future labels.

Public API: build_features(weeks, index_rows), build_nodes(features, events=()),
build(weeks, index_rows, events=()). CSV missing numeric values are empty strings.
Dates are conservative visibility proxies, not historical-vintage PIT guarantees.
"""
import argparse
import csv
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE_FIELDS = ['week', 'week_end', 'assessment_at', 'index_close', 'index_low',
                  'index_days', 'index_week_return', 'dd12', 'low_change',
                  'downside_pressure', 'pressure_easing', 'margin_easing',
                  'l1_mean2', 'ax_breadth', 'ax_part', 'current_known',
                  'coverage_status', 'feature_reason', 'a_candidate']
NODE_FIELDS = ['episode_id', 'stage', 'week', 'week_end', 'assessment_at',
               'anchor_week', 'anchor_low', 'anchor_close', 'index_close',
               'feature_reason', 'known_event_ids']


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def day(value):
    if len(value) == 8 and value.isdigit():
        value = value[:4] + '-' + value[4:6] + '-' + value[6:]
    return date.fromisoformat(value)


def week_key(d):
    y, w, _ = d.isocalendar()
    return f'{y}-W{w:02d}'


def build_features(weeks, index_rows):
    """Keep every observed trading week, including bad/missing weekly inputs.

    Unioning index weeks with weekly rows prevents silently skipping an omitted
    weekly row. Entire market holiday weeks (neither input observes them) do not
    manufacture observations. Every history slice ends at the current endpoint.
    """
    weekly = {}
    for row in weeks:
        key = row['week']
        if key in weekly:
            raise ValueError(f'duplicate weekly row: {key}')
        weekly[key] = row
    if not weekly:
        return []
    prices = {}
    groups = {}
    for row in index_rows:
        d = day(row['trade_date'])
        if d in prices:
            raise ValueError(f'duplicate index date: {d}')
        prices[d] = {k: number(row.get(k)) for k in ('open', 'high', 'low', 'close')}
        groups.setdefault(week_key(d), []).append(d)
    days = sorted(prices)
    previous = {d: days[i - 1] if i else None for i, d in enumerate(days)}
    keys = sorted(set(weekly) | {k for k in groups if min(weekly) <= k <= max(weekly)})
    history = []
    output = []
    for key in keys:
        w = weekly.get(key, {})
        obs = sorted(groups.get(key, []))
        end = day(w['week_end']) if w else obs[-1]
        obs = [d for d in obs if d <= end]
        t = timestamp(w.get('usable_at'))
        timing_ok = bool(t and w.get('availability_unknown') in ('0', 0)
                         and t.date() > end + timedelta(days=4 - end.weekday()))
        assessment = w.get('usable_at', '')
        reasons = []
        if not w:
            reasons.append('MISSING_WEEKLY')
        if not timing_ok:
            reasons.append('UNKNOWN_TIME')
        endpoint = bool(obs and obs[-1] == end and week_key(end) == key)
        prev = previous.get(obs[0]) if obs else None
        gap = bool(obs and (not prev or (obs[0] - prev).days > 14
                           or any((b - a).days > 14 for a, b in zip(obs, obs[1:]))))
        good_ohlc = bool(obs and all(all(prices[d][k] is not None and prices[d][k] > 0
                                       for k in ('open', 'high', 'low', 'close'))
                                   and prices[d]['low'] <= min(prices[d]['open'], prices[d]['close'])
                                   and prices[d]['high'] >= max(prices[d]['open'], prices[d]['close'])
                                   for d in obs))
        count_ok = number(w.get('days_obs')) == len(obs) if w else False
        price_ok = bool(endpoint and good_ohlc and not gap and count_ok
                        and prev and prices[prev]['close'] is not None
                        and prices[prev]['close'] > 0)
        if not endpoint:
            reasons.append('MISSING_ENDPOINT')
        if gap:
            reasons.append('INDEX_GAP')
        if not good_ohlc:
            reasons.append('MISSING_OHLC')
        if not count_ok:
            reasons.append('DAY_COVERAGE')
        close = prices[end]['close'] if endpoint else None
        low = min(prices[d]['low'] for d in obs) if good_ohlc else None
        ret = None
        pressure = None
        if price_ok and prices[prev]['close']:
            ret = close / prices[prev]['close'] - 1
            pressure = sum(max(0.0, 1 - prices[d]['close'] / prices[previous[d]]['close'])
                           for d in obs if previous[d] and prices[previous[d]]['close'])
        item = dict(time=t, valid=bool(price_ok and timing_ok), close=close, low=low,
                    pressure=pressure, margin=number(w.get('m_fin_flow_w')),
                    l1=number(w.get('l1_fam_delta_w')))
        history.append(item)
        h12, h4, h2 = history[-12:], history[-4:], history[-2:]

        def covered(window, size):
            return bool(len(window) == size and t and all(
                x['valid'] and x['time'] <= t for x in window))

        c12, c4, c2 = covered(h12, 12), covered(h4, 4), covered(h2, 2)
        dd = close / max(x['close'] for x in h12) - 1 if c12 else None
        low_change = low / h2[0]['low'] - 1 if c2 else None
        pe = me = None
        if c4 and all(x['pressure'] is not None for x in h4):
            old = sum(x['pressure'] for x in h4[:2]) / 2
            new = sum(x['pressure'] for x in h4[2:]) / 2
            pe = old > 0 and new <= old
        if c4 and all(x['margin'] is not None for x in h4):
            old = sum(x['margin'] for x in h4[:2]) / 2
            new = sum(x['margin'] for x in h4[2:]) / 2
            me = old < 0 and new >= old
        l1 = sum(x['l1'] for x in h2) / 2 if c2 and all(x['l1'] is not None for x in h2) else None
        if not c12:
            reasons.append('HISTORY12_INCOMPLETE')
        if pe is None:
            reasons.append('PRESSURE4_INCOMPLETE')
        if me is None:
            reasons.append('MARGIN4_INCOMPLETE')
        if l1 is None:
            reasons.append('L1_2_INCOMPLETE')
        complete = bool(c12 and pe is not None and me is not None and l1 is not None)
        out = dict(week=key, week_end=end.strftime('%Y%m%d'), assessment_at=assessment,
                   index_close=close, index_low=low, index_days=len(obs),
                   index_week_return=ret, dd12=dd, low_change=low_change,
                   downside_pressure=pressure, pressure_easing=pe, margin_easing=me,
                   l1_mean2=l1, ax_breadth=number(w.get('ax_breadth')),
                   ax_part=number(w.get('ax_part')), current_known=bool(item['valid']),
                   coverage_status='COMPLETE' if complete else 'INCOMPLETE',
                   feature_reason=';'.join(reasons) or 'COMPLETE',
                   a_candidate=bool(complete and dd <= -0.05 and low_change >= -0.01
                                    and pe and me and l1 >= 0))
        output.append({k: '' if v is None else v for k, v in out.items()})
    return output


def truth(value):
    return value is True or str(value).lower() in ('1', 'true')


def build_nodes(features, events=()):
    """A then strictly later B then strictly later C; loss/expiry wins.

    A+12 is expiry (no upgrade); incomplete weeks still count and never restart
    an active episode. A completed C remains merged until loss/expiry as well.
    """
    if isinstance(events, dict):
        events = events.get('events', [])
    visible = [(e['event_id'], timestamp(e.get('first_usable_at'))) for e in events]
    nodes = []
    active = None
    previous_breadth = None
    for i, f in enumerate(features):
        t = timestamp(f.get('assessment_at'))
        known = truth(f.get('current_known')) and t is not None
        complete = known and f.get('coverage_status') == 'COMPLETE'
        breadth = number(f.get('ax_breadth')) if complete else None
        close = number(f.get('index_close'))
        stage = None
        if active:
            age = i - active['i']
            if (known and close is not None and close < active['low'] * 0.97) or age >= 12:
                active = None
                previous_breadth = breadth
                continue  # no re-A or upgrade in the failure/expiry week
            if complete and active['stage'] == 'A':
                part, ret = number(f.get('ax_part')), number(f.get('index_week_return'))
                if breadth is not None and breadth >= .50 and part is not None and part >= 1 and ret is not None and ret > 0:
                    stage = 'B'
            elif complete and active['stage'] == 'B':
                if breadth is not None and breadth >= .50 and previous_breadth is not None and previous_breadth >= .50 and close > active['close']:
                    stage = 'C'
        elif complete and truth(f.get('a_candidate')):
            stage = 'A'
            active = dict(i=i, week=f['week'], low=number(f['index_low']),
                          close=close, stage='A')
        if stage:
            active['stage'] = stage
            ids = sorted({eid for eid, et in visible if et is not None
                          and t - timedelta(days=28) <= et <= t})
            nodes.append(dict(episode_id='IS2B-' + active['week'], stage=stage,
                              week=f['week'], week_end=f['week_end'],
                              assessment_at=f['assessment_at'], anchor_week=active['week'],
                              anchor_low=active['low'], anchor_close=active['close'],
                              index_close=close, feature_reason=f'{stage}_FIXED_V1;' + f['feature_reason'],
                              known_event_ids=json.dumps(ids, ensure_ascii=False)))
        previous_breadth = breadth
    return nodes


def build(weeks, index_rows, events=()):
    features = build_features(weeks, index_rows)
    return features, build_nodes(features, events)


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weekly', default=str(ROOT / 'data/cfis/weekly_full_202201_202610.csv'))
    parser.add_argument('--index', default=str(ROOT / 'docs/phase_i/evidence/market_index_000985.json'))
    parser.add_argument('--events', default=str(ROOT / 'docs/research/cfis/macro_events_seed.json'))
    parser.add_argument('--features-out', default=str(ROOT / 'data/cfis/is2b_features.csv'))
    parser.add_argument('--nodes-out', default=str(ROOT / 'data/cfis/is2b_nodes.csv'))
    args = parser.parse_args()
    with open(args.weekly, encoding='utf-8') as stream:
        weeks = list(csv.DictReader(stream))
    with open(args.index, encoding='utf-8') as stream:
        index_rows = json.load(stream)['rows']
    with open(args.events, encoding='utf-8') as stream:
        events = json.load(stream)
    features, nodes = build(weeks, index_rows, events)
    write_csv(args.features_out, features, FEATURE_FIELDS)
    write_csv(args.nodes_out, nodes, NODE_FIELDS)
    print(f'features={len(features)} complete={sum(f["coverage_status"] == "COMPLETE" for f in features)} nodes={len(nodes)} episodes={len({n["episode_id"] for n in nodes})}')


if __name__ == '__main__':
    main()
