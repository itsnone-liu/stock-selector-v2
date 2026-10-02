#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NC-ERRATUM-1: build NATIONAL_CTX_V1e sidecars with an explicit
stock-layer disclosure summary.

Supersedes scripts/build_national_capital_context.py (frozen at the
H-PRE boundary, audited commit 6580e02) for ordinals >= 5 only.
Ordinals 1-4 keep their sealed v1 sidecars byte-identically; the frozen
builder remains the verifier for the sealed prefix.

Erratum content (ordered by the H2 canary closed-loop review,
2026-10-02):

* The v1 sidecar's `stock_capital_records: []` was AMBIGUOUS between
  "no PIT-visible report", "source unavailable" and "latest visible
  complete top-10 discloses no tracked national actor".  Consumers
  (annotators) then re-derived the distinction from selector-side
  data — an out-of-contract bypass (H2-CANARY-FIX1 item 2).
* v1e adds an explicit, in-band enum so the projection contract
  selector hidden domain -> NATIONAL_CTX -> annotator is closed:

      SOURCE_UNAVAILABLE                    (v1 S-000000 branch)
      NO_PIT_VISIBLE_REPORT                 (no cell with avail<=T)
      NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10 (complete latest visible
                                             top-10 discloses no
                                             tracked national actor)
      NATIONAL_ACTORS_PRESENT               (>=1 tracked actor in the
                                             latest/previous union)

  NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10 is a DISCLOSURE fact: it is
  NOT negative evidence that holdings do not exist (positions below
  the top-10 threshold or outside this disclosure regime remain
  unobserved).  Annotation wording must use disclosure semantics.

Everything else (record shapes, market layer, limitations, source
commitments, commitment derivation over the whole object minus the
commitment field) is semantically identical to the frozen v1 builder;
for the same ordinal the records arrays are byte-equal.
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/research/csr/national_capital'

STOCK_LAYER_SUMMARIES = (
    'SOURCE_UNAVAILABLE',
    'NO_PIT_VISIBLE_REPORT',
    'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10',
    'NATIONAL_ACTORS_PRESENT',
)


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def num(x):
    try:
        return float(x) if x not in ('', None) else None
    except Exception:  # noqa: BLE001
        return None


def build(ordinal):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import csr8_phase_c_annotation_seal as c4d
    cand = c4d.candidate_for_ordinal(ordinal)
    T = cand['T']
    ocid = cand['opaque_case_id']
    packet = c4d.c1.packet_id(ocid, T)
    salt = c4d.c1.load_salt()
    plan = json.loads(c4d.c1.PLAN_FILE.read_text())
    matches = [e for e in plan['entries']
               if c4d.c1.opaque_case_id(salt, e['case_key']) == ocid
               and e['T'] == T]
    if len(matches) != 1:
        raise SystemExit('candidate identity resolution is not unique')
    stock_code = matches[0]['case_key'].split('|')[1]
    h = list(csv.DictReader(
        (OUT / 'national_holdings_pit.csv').open()))
    all_rows = [r for r in h if r['stock_code'] == stock_code]
    ledger = list(csv.DictReader(
        (OUT / 'holdings_coverage_ledger.csv').open()))
    pub = {(r['stock_code'], r['report_period']): r for r in
           csv.DictReader((OUT / 'publication_dates.csv').open())}
    cal = sorted(x.strip() for x in
                 (ROOT / 'output/research/csr/08_pilot_cases/phase_b/'
                  'ingest_rt/frozen_exchange_calendar.csv')
                 .read_text().splitlines()[3:] if x.strip())

    def avail(period):
        rs = [r for r in all_rows
              if r['report_period'] == period
              and r.get('available_date') not in ('', 'UNKNOWN')]
        if rs:
            return min(r['available_date'] for r in rs)
        p = pub.get((stock_code, period), {}).get(
            'publication_date', '')
        p = f'{p[:4]}-{p[4:6]}-{p[6:]}' if len(p) == 8 else p
        return next((d for d in cal if d > p), '')

    cells = [r for r in ledger if r['stock_code'] == stock_code
             and avail(r['report_period'])
             and avail(r['report_period']) <= T]
    cells.sort(key=lambda r: (avail(r['report_period']),
                              r['report_period']))
    latest_cell = cells[-1] if cells else None
    prev_cell = cells[-2] if len(cells) > 1 else None
    latest_period = (latest_cell['report_period']
                     if latest_cell else None)
    previous_period = (prev_cell['report_period']
                       if prev_cell else None)
    latest = ([r for r in all_rows
               if r['report_period'] == latest_period]
              if latest_period
              and latest_cell['source_status'] == 'SUCCESS_NONEMPTY'
              else [])
    previous = ([r for r in all_rows
                 if r['report_period'] == previous_period
                 and prev_cell['source_status'] == 'SUCCESS_NONEMPTY']
                if previous_period else [])
    latest_by = {r.get('actor_id'): r for r in latest
                 if r.get('actor_id')}
    previous_by = {r.get('actor_id'): r for r in previous
                   if r.get('actor_id')}
    actors = sorted(set(latest_by) | set(previous_by))
    stock = []
    latest_unavailable = bool(
        latest_cell and latest_cell['source_status'] !=
        'SUCCESS_NONEMPTY')

    # NC-ERRATUM-1: explicit in-band stock-layer disclosure summary.
    if latest_unavailable:
        summary = 'SOURCE_UNAVAILABLE'
    elif latest_cell is None:
        summary = 'NO_PIT_VISIBLE_REPORT'
    elif not actors:
        summary = 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'
    else:
        summary = 'NATIONAL_ACTORS_PRESENT'

    if latest_unavailable:
        up = latest_period
        ua = avail(up)
        stock = [{'context_record_id': 'S-000000',
                  'capital_layer': 'STOCK',
                  'evidence_type': 'NATIONAL_ACTOR_HOLDING_STATE',
                  'actor_id': '', 'state': 'UNKNOWN',
                  'current_report_period': up,
                  'current_publication_date': '',
                  'current_available_date': ua,
                  'current_holding_ratio': '',
                  'previous_report_period': previous_period or '',
                  'previous_holding_ratio': '',
                  'evidence_grade': 'SOURCE_UNAVAILABLE',
                  'source_status': 'UNAVAILABLE'}]
    elif actors:
        for i, actor in enumerate(actors):
            cur = latest_by.get(actor)
            prev = previous_by.get(actor)
            state = ('UNKNOWN'
                     if not latest_cell or latest_cell[
                     'source_status'] != 'SUCCESS_NONEMPTY'
                     else 'FIRST_DISCLOSED' if cur and not prev
                     else 'NOT_DISCLOSED_IN_TOP10'
                     if not cur and prev
                     else 'UNKNOWN' if not cur
                     else 'INCREASE' if num(cur.get('holding_ratio'))
                     > num(prev.get('holding_ratio'))
                     else 'DECREASE' if num(cur.get('holding_ratio'))
                     < num(prev.get('holding_ratio'))
                     else 'STABLE')
            base = cur or prev
            stock.append({
                'context_record_id': f'S-{i:06d}',
                'capital_layer': 'STOCK',
                'evidence_type': 'NATIONAL_ACTOR_HOLDING_STATE',
                'actor_id': actor, 'state': state,
                'current_report_period': latest_period or '',
                'current_publication_date':
                    cur.get('publication_date', '') if cur else '',
                'current_available_date':
                    cur.get('available_date', '') if cur else '',
                'current_holding_ratio':
                    cur.get('holding_ratio', '')
                    if cur and state not in (
                        'UNKNOWN', 'NOT_DISCLOSED_IN_TOP10') else '',
                'previous_report_period':
                    prev['report_period'] if prev else '',
                'previous_holding_ratio':
                    prev.get('holding_ratio', '') if prev else '',
                'evidence_grade':
                    base.get('source_grade', 'SOURCE_UNAVAILABLE')
                    if base else 'SOURCE_UNAVAILABLE'})

    e = list(csv.DictReader((OUT / 'etf_share_daily_sse.csv').open()))
    market = []
    for code in sorted({r['etf_code'] for r in e}):
        rs = sorted([r for r in e if r['etf_code'] == code
                     and r.get('availability_status') == 'AVAILABLE_PIT'
                     and r.get('available_date') <= T],
                    key=lambda x: x['trade_date'])
        if not rs:
            continue
        q = rs[-1]
        p = rs[-2] if len(rs) > 1 else None
        v = num(q.get('total_shares'))
        pv = num(p.get('total_shares')) if p else None
        state = ('STABLE' if p is None or v == pv
                 else 'EXPANSION' if v > pv else 'CONTRACTION')
        market.append({
            'context_record_id': f'E-{len(market):06d}',
            'capital_layer': 'MARKET',
            'evidence_type': 'ETF_TOTAL_SHARES',
            'etf_code_hash': hashlib.sha256(code.encode()).hexdigest(),
            'latest_trade_date': q['trade_date'],
            'latest_available_date': q['available_date'],
            'latest_total_shares': q['total_shares'],
            'previous_trade_date': p['trade_date'] if p else '',
            'previous_total_shares': p['total_shares'] if p else '',
            'share_change': str(v - pv)
            if p and v is not None and pv is not None else '',
            'share_change_ratio': str((v - pv) / pv)
            if p and v is not None and pv else '',
            'state': state, 'actor_attribution': 'FORBIDDEN'})

    ctx = {'context_version': 'csr8-national-capital-v1e',
           'evidence_profile': 'BASE_V1+NATIONAL_CTX_V1',
           'ordinal': ordinal, 'packet_id': packet,
           'as_of': {'T': T, 'availability_rule': 'available_date<=T'},
           'stock_layer_summary': summary,
           'stock_layer_summary_report_period':
               latest_period if latest_cell else '',
           'stock_capital_records': stock,
           'market_etf_records': market,
           'limitations': [
               {'status': 'UNAVAILABLE', 'scope': 'SZSE_ETF_HISTORY'}],
           'source_commitments': {
               'holdings_sha256': hashlib.sha256(
                   (OUT / 'national_holdings_pit.csv')
                   .read_bytes()).hexdigest(),
               'etf_sha256': hashlib.sha256(
                   (OUT / 'etf_share_daily_sse.csv')
                   .read_bytes()).hexdigest()},
           'context_commitment_sha256': ''}
    ctx['context_commitment_sha256'] = hashlib.sha256(
        canon({k: v for k, v in ctx.items()
               if k != 'context_commitment_sha256'}).encode()).hexdigest()
    return ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ordinal', type=int, required=True)
    ap.add_argument('--packet-id')
    ap.add_argument('--as-of')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / 'scripts'))
    import csr8_phase_c_annotation_seal as c4d
    cand = c4d.candidate_for_ordinal(a.ordinal)
    if a.packet_id and a.packet_id != c4d.c1.packet_id(
            cand['opaque_case_id'], cand['T']):
        raise SystemExit('packet-id does not match candidate_for_ordinal')
    if a.as_of and a.as_of != cand['T']:
        raise SystemExit('as-of does not match candidate_for_ordinal')
    ctx = build(a.ordinal)
    Path(a.out).write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({
        'out': a.out, 'packet_id': ctx['packet_id'],
        'context_version': ctx['context_version'],
        'stock_layer_summary': ctx['stock_layer_summary'],
        'records': len(ctx['stock_capital_records'])
        + len(ctx['market_etf_records']),
        'context_commitment_sha256':
            ctx['context_commitment_sha256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
