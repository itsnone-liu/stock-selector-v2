#!/usr/bin/env python3
"""CSR-8 Phase J / J1 — Batch 1 corpus production under frozen J0 protocol.

STRUCTURAL BLINDNESS (J0 appendix 3): this script reads ONLY unadjusted
prices at dates <= T (packet panel). The hfq side of the frozen series is
never loaded; R values, deltas, verdicts are never computed. The control
plane emits coverage counts only.

Per frozen protocol: admitted dates 2024-08-23 / 2024-09-09 / 2024-09-26 /
2025-01-14; entities = frozen universe84 in canonical order, per-date cap 32;
every skip recorded with reason; ETF cell composition computed from the
frozen PIT ETF share table only AFTER packets build; missing cells =>
admitted-but-non-contributing.
"""
import csv, gzip, hashlib, hmac, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

BATCHES = {1: ['2024-08-23', '2024-09-09', '2024-09-26', '2025-01-14'],
           2: ['2025-02-06', '2025-04-15', '2025-04-30', '2025-05-20'],
           3: ['2025-06-05', '2025-06-24', '2025-12-17', '2026-04-07']}
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 1
BATCH_DATES = BATCHES[BATCH]
PANEL_N = 120
OUTD = ROOT / f'data/phase_j/corpus/batch{BATCH}'
DOCS = ROOT / 'docs/phase_j/evidence'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load_calendar():
    lines = (ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt/'
             'frozen_exchange_calendar.csv').read_text().splitlines()
    dates = [l for l in lines if l and not l.startswith('#') and l != 'date']
    assert sha(('date\n' + '\n'.join(dates) + '\n').encode()).startswith('87f8f959')
    return dates


def load_universe_with_keys():
    """universe84 canonical order + Phase H case_key per code (same key as
    discovery -> same ocid per entity; supports the dependency disclosure)."""
    d = json.load(open(ROOT / 'output/research/csr/08_pilot_cases/'
                       'phase_a/sample_selection.json'))
    out = []
    for g, obj in d['groups'].items():
        for c in obj['chosen']:
            if 'w_start' in c:
                key = f"{g}|{c['code']}|{c['w_start']}|{c['w_end']}"
            else:
                key = f"{g}|{c['code']}|{c['T0']}|{c['T0']}"
            out.append((c['code'], key))
    codes = [x[0] for x in out]
    assert len(codes) == 84 and len(set(codes)) == 84
    assert sha(json.dumps(codes).encode()).startswith('2cd7d202')
    return out


def load_unadj(code, cal_index):
    d = json.loads(gzip.decompress(
        (ROOT / f'data/adjustment_baostock/per_stock/{code}.json.gz')
        .read_bytes()))
    idx = {}
    for row in d['unadj']:
        idx[row[0]] = row[4]
    return idx


def etf_states_at(T):
    """Frozen ETF PIT rule (v1e1 semantics): per code, latest two AVAILABLE_PIT
    rows with available_date <= T; EXPANSION if shares rose, etc."""
    e = list(csv.DictReader((ROOT / 'output/research/csr/national_capital/'
                             'etf_share_daily_sse.csv').open()))
    states = []
    for code in sorted({r['etf_code'] for r in e}):
        rs = sorted([r for r in e if r['etf_code'] == code
                     and r.get('availability_status') == 'AVAILABLE_PIT'
                     and r['available_date'] <= T],
                    key=lambda x: x['trade_date'])
        if not rs:
            continue
        q, p = rs[-1], (rs[-2] if len(rs) > 1 else None)
        v = float(q['total_shares'])
        pv = float(p['total_shares']) if p else None
        st = ('STABLE' if p is None or v == pv
              else 'EXPANSION' if v > pv else 'CONTRACTION')
        states.append({'etf_code_hash': sha(code.encode()),
                       'latest_trade_date': q['trade_date'],
                       'state': st})
    return states


def stock_layer_at(code, T, pit, ledger, pub, cal):
    """Verbatim replication of build_national_capital_context_v1e1 stock-layer
    semantics for a (code, T) pair (no ordinal machinery in Phase J)."""
    all_rows = [r for r in pit if r['stock_code'] == code]
    pubmap = {(r['stock_code'], r['report_period']): r for r in pub}

    def avail(period):
        rs = [r for r in all_rows if r['report_period'] == period
              and r.get('available_date') not in ('', 'UNKNOWN')]
        if rs:
            return min(r['available_date'] for r in rs)
        p = pubmap.get((code, period), {}).get('publication_date', '')
        p = f'{p[:4]}-{p[4:6]}-{p[6:]}' if len(p) == 8 else p
        return next((d for d in cal if d > p), '')

    cells = [r for r in ledger if r['stock_code'] == code
             and avail(r['report_period']) and avail(r['report_period']) <= T]
    cells.sort(key=lambda r: (avail(r['report_period']), r['report_period']))
    latest_cell = cells[-1] if cells else None
    prev_cell = cells[-2] if len(cells) > 1 else None
    if latest_cell is None:
        return 'NO_PIT_VISIBLE_REPORT', 'UNKNOWN'
    if latest_cell['source_status'] != 'SUCCESS_NONEMPTY':
        return 'SOURCE_UNAVAILABLE', 'UNKNOWN'
    lp = latest_cell['report_period']
    latest = [r for r in all_rows if r['report_period'] == lp
              and r.get('actor_id')]
    if latest:
        # states vs previous visible period (v1e1 rules, abridged to counts:
        # Phase J does not use the stock layer in any hypothesis)
        pp = prev_cell['report_period'] if prev_cell else None
        prev = {r['actor_id']: r for r in all_rows
                if r['report_period'] == pp and r.get('actor_id')} if pp else {}
        cur = {r['actor_id']: r for r in latest}
        n_states = {'INCREASE': 0, 'DECREASE': 0, 'STABLE': 0,
                    'FIRST_DISCLOSED': 0, 'NOT_DISCLOSED_IN_TOP10': 0}
        for a in set(cur) | set(prev):
            c, p = cur.get(a), prev.get(a)
            s = ('FIRST_DISCLOSED' if c and not p
                 else 'NOT_DISCLOSED_IN_TOP10' if not c and p
                 else 'INCREASE' if c and p and float(c['holding_ratio']) >
                 float(p['holding_ratio'])
                 else 'DECREASE' if c and p and float(c['holding_ratio']) <
                 float(p['holding_ratio']) else 'STABLE')
            n_states[s if s in n_states else 'STABLE'] += 1
        return 'NATIONAL_ACTORS_PRESENT', n_states
    return 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10', {}


def finite_pos(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if (math.isfinite(v) and v > 0) else None


def main():
    OUTD.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    cal = load_calendar()
    cal_index = {d: i for i, d in enumerate(cal)}
    salt = (ROOT / 'data/csr8_phase_c/secret/secret_salt').read_text().strip()
    universe = load_universe_with_keys()
    pit = list(csv.DictReader((ROOT / 'output/research/csr/national_capital/'
                               'national_holdings_pit.csv').open()))
    ledger = list(csv.DictReader((ROOT / 'output/research/csr/'
                                  'national_capital/'
                                  'holdings_coverage_ledger.csv').open()))
    pub = list(csv.DictReader((ROOT / 'output/research/csr/national_capital/'
                               'publication_dates.csv').open()))
    series = {code: load_unadj(code, cal_index) for code, _ in universe}

    corpus, skip_ledger, per_date = [], [], []
    for T in BATCH_DATES:
        states = etf_states_at(T)
        expansion = sum(1 for s in states if s['state'] == 'EXPANSION')
        contraction = sum(1 for s in states if s['state'] == 'CONTRACTION')
        built, d_skips = 0, {}
        i = cal_index[T]
        for code, key in universe:                      # canonical order
            if built >= 32:                             # frozen per-date cap
                d_skips['cap_32_reached'] = d_skips.get('cap_32_reached', 0) + 1
                break
            ocid = hmac.new(salt.encode(), key.encode(),
                            hashlib.sha256).hexdigest()
            unadj = series[code]
            reasons = []
            pT = finite_pos(unadj.get(T))
            panel_dates = cal[max(0, i - PANEL_N + 1):i + 1]
            panel_vals = [finite_pos(unadj.get(d)) for d in panel_dates]
            if pT is None:
                reasons.append('no_valid_price_at_T')
            if sum(1 for v in panel_vals if v is not None) < PANEL_N:
                reasons.append('panel_lt_120_valid_sessions')
            if reasons:
                d_skips[reasons[0]] = d_skips.get(reasons[0], 0) + 1
                skip_ledger.append({'T': T, 'code': code, 'reasons': reasons})
                continue
            panel = [v for v in panel_vals]
            assert abs(panel[-1] - pT) < 5e-5           # P0 identity (same source)
            summary, n_states = stock_layer_at(code, T, pit, ledger, pub, cal)
            corpus.append({
                'T': T, 'code_hash': sha(code.encode()), 'ocid': ocid,
                'case_key_group_anon': key.split('|')[0],
                'packet_id': sha(f'{ocid}|{T}'.encode()),
                'panel': {'start': panel_dates[0], 'end': T, 'n': PANEL_N,
                          'sha256': sha(json.dumps(panel).encode())},
                'etf_expansion_count': expansion,
                'etf_contraction_count': contraction,
                'stock_layer_summary': summary,
                'stock_actor_state_counts': n_states,
                'corpus': 'pj-val-0001', 'batch': BATCH})
            built += 1
        per_date.append({'T': T, 'expansion': expansion,
                         'contraction': contraction, 'n_built': built,
                         'n_skipped': sum(d_skips.values()),
                         'skip_census': d_skips})
    (OUTD / 'cases.jsonl').write_text(
        '\n'.join(json.dumps(c, ensure_ascii=False, sort_keys=True)
                  for c in corpus) + '\n')
    (OUTD / 'skip_ledger.json').write_text(
        json.dumps(skip_ledger, ensure_ascii=False, indent=1, sort_keys=True))

    # ---- coverage-only control plane (J0 appendix 3) ----
    cells = {}
    for d in per_date:
        cells[d['expansion']] = cells.get(d['expansion'], 0) + (1 if d['n_built'] else 0)
    def arm_dates(a, b):
        return sum(1 for d in per_date if d['expansion'] in (a, b) and d['n_built'])
    cov = {'arm_HJ1_4v8': {'cell4_dates': sum(1 for d in per_date if d['expansion'] == 4 and d['n_built']),
                           'cell8_dates': sum(1 for d in per_date if d['expansion'] == 8 and d['n_built'])},
           'arm_HJ2_8v9': {'cell8_dates': sum(1 for d in per_date if d['expansion'] == 8 and d['n_built']),
                           'cell9_dates': sum(1 for d in per_date if d['expansion'] == 9 and d['n_built'])}}
    # dependency-structure disclosure (preregistered reporting items)
    from collections import Counter
    oc = Counter(c['ocid'] for c in corpus)
    per_cell_rec = {}
    for c in corpus:
        per_cell_rec.setdefault(c['etf_expansion_count'], Counter())[c['ocid']] += 1
    disclosure = {
        'unique_opaque_entities': len(oc),
        'entities_on_multiple_admitted_dates': sum(1 for v in oc.values() if v > 1),
        'max_dates_per_entity': max(oc.values()),
        'per_cell_entity_recurrence': {str(k): {'distinct_entities': len(v),
                                                'max_cases_per_entity': max(v.values())}
                                       for k, v in sorted(per_cell_rec.items())}}
    out = {'batch': BATCH, 'dates': BATCH_DATES, 'per_date': per_date,
           'expansion_counts_present': sorted(cells),
           'coverage': cov,
           'coverage_note': 'counts only; no R values, signs, deltas, or verdicts computed',
           'dependency_disclosure': disclosure,
           'inputs': {'universe84_sha': '2cd7d202bd4aa987cbe7753b4b9126d2403b594811dac6cbd096a525bd357d23',
                      'price_source': 'data/adjustment_baostock/per_stock (unadj only, dates<=T)',
                      'etf_source': 'output/research/csr/national_capital/etf_share_daily_sse.csv',
                      'holdings': 'national_holdings_pit.csv + holdings_coverage_ledger.csv + publication_dates.csv',
                      'stock_layer_semantics': 'replicated from build_national_capital_context_v1e1'}}
    (DOCS / f'j1_batch{BATCH}_coverage.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    print(json.dumps({f'batch{BATCH}_dates': BATCH_DATES,
                      'per_date': [{'T': d['T'], 'expansion': d['expansion'],
                                    'built': d['n_built']} for d in per_date],
                      'coverage': cov}, ensure_ascii=False))


if __name__ == '__main__':
    main()
