#!/usr/bin/env python3
"""CSR-8 Phase I / I4A — External Market Context FREEZE.

DATA / PROVENANCE / PREREGISTRATION ONLY. Computes ZERO relation statistics
(no R5, no deltas, no direction tests) — those belong to I4B.

Mandated order (user ruling 2026-10-04, ERR-I3-1 lesson):
  data inventory -> PIT/provenance audit -> coverage matrix ->
  preregistration -> freeze.

FROZEN DESIGN CHOICES (all made BEFORE any result; rationale recorded in the
contract, selection criterion = economic correspondence, not fit):
  - index: CSI All-Share Index 000985 (中证全指) — whole-market proxy matching
    the cross-sector allocation channel the ETF layer measures; NOT chosen
    after comparing results (no result existed at freeze time)
  - price convention: raw close (index, no adjustment ambiguity)
  - PIT availability: index daily bar is public end-of-day on trade_date;
    analysis rule is STRICTLY BEFORE T (trade_date < T) — double margin
  - regime: binary, close(T-1) vs median(close of the 120 trading days
    ending at T-1): UP if above, DOWN otherwise. One parameter (120 ~
    two quarterly disclosure cycles), no thresholds, no tuning.
  - sector regime: DEFERRED — only a 2026-09-21 single-snapshot CSRC
    classification exists (data/t4/sector_map); retroactive use = future
    information; PIT time-basis requirement not satisfiable. Recorded
    honestly instead of silently back-filling.

Outputs:
  docs/phase_i/evidence/market_index_000985_raw_urls.json   (verbatim API response)
  docs/phase_i/evidence/market_index_000985.json       (normalized daily closes)
  docs/phase_i/evidence/manifest.json                  (provenance + sha256)
  docs/phase_i/i4a_coverage_matrix.json          (coverage, NO outcomes)
  docs/phase_i/i4a_preregistration.json          (frozen contract)
"""
import json, hashlib, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
DATA = ROOT / 'docs/phase_i/evidence'
OUT = ROOT / 'docs/phase_i'
RC = ROOT / 'data/csr8_phase_c/c4d_receipts/c4-prod-0002'

INDEX_CODE = 'sh000985'
FETCH_START, FETCH_END = '2020-06-01', '2026-04-30'
WINDOW = 120                       # trading days, frozen
URLS = [(f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?'
         f'param={INDEX_CODE},day,{a},{b},640,qfq')
        for a, b in (('2020-06-01', '2023-03-31'),
                     ('2023-04-01', '2026-04-30'))]   # API caps ~640 rows/request


def fetch_index():
    days = {}
    for url in URLS:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        raw = urllib.request.urlopen(req, timeout=60).read()
        j = json.loads(raw)
        got = j['data'][INDEX_CODE].get('day') or j['data'][INDEX_CODE].get('qfqday')
        for d in got:
            days[d[0]] = d          # dedupe by trade_date across segments
    norm = [{'trade_date': d, 'open': float(v[1]), 'close': float(v[2]),
             'high': float(v[3]), 'low': float(v[4]), 'volume': float(v[5])}
            for d, v in days.items()]
    norm.sort(key=lambda r: r['trade_date'])
    return norm


ELIGIBLE_RELATIONS = ['ETF_4_vs_8', 'ETF_8_vs_9']   # frozen; ND-vs-NO_PIT excluded
MIN_DISTINCT_DATES_PER_CELL_REGIME = 3   # preregistered minimal coverage floor


def sha(b):
    return hashlib.sha256(b).hexdigest()


def regime_at(norm, T, window=WINDOW):
    """Binary market regime at observation date T using ONLY trade_date < T."""
    closes = [r['close'] for r in norm if r['trade_date'] < T]
    if len(closes) < window:
        return None                     # insufficient history -> INSUFFICIENT
    w = closes[-window:]
    return 'UP' if w[-1] > sorted(w)[len(w) // 2] - 1e-12 else 'DOWN'


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    # 1) inventory (full corpus census — no probe generalization)
    atlas = json.loads((OUT / 'i1_structural_atlas.json').read_text())
    cards = atlas['cards']
    cases = [c for c in cards.values() if c['ordinal'] >= 7
             and isinstance(c.get('capital_state'), dict)]
    Ts = sorted({c['T'] for c in cases})
    etf_cell = {c['ordinal']: str(c['capital_state']['etf']['expansion'])
                for c in cases}
    inventory = {
        'readout_cases': len(cases), 'distinct_T': len(Ts),
        'T_range': [Ts[0], Ts[-1]],
        'in_repo_index_series': ['NONE found under data/ (csr8_ingest: dzjy/lhb/margin; national_capital: etf_shares/holdings; t4: sector_map only)'],
        'in_repo_sector_classification': 'data/t4/sector_map/csrc_industry_snapshot.json — 5555 rows ALL stamped 2026-09-21 (single current snapshot, some empty industry labels)',
        'fetch_channel': 'Tencent fqkline HTTP API (same family as production-era market data channels), provenance = full URL recorded in manifest',
    }
    # 2) fetch + normalize + provenance
    norm = fetch_index()
    (DATA / 'market_index_000985_raw_urls.json').write_text(
        json.dumps({'urls': URLS, 'note': 'raw HTTP responses not persisted; '
                    'provenance = URL list + row count + trade-date range; '
                    'normalized file is the frozen artifact'}, indent=1) + '\n')
    (DATA / 'market_index_000985.json').write_text(
        json.dumps({'index': '000985 CSI All-Share', 'convention': 'raw close',
                    'rows': norm}, ensure_ascii=False, sort_keys=True) + '\n')
    manifest = {'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
                'url_segments': URLS,
                'normalized_file_sha256': sha((DATA / 'market_index_000985.json').read_bytes()),
                'n_rows': len(norm),
                'trade_date_range': [norm[0]['trade_date'], norm[-1]['trade_date']],
                'pit_rule': 'analysis uses trade_date < T strictly; index EOD bar public on trade_date'}
    (DATA / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    # 3) PIT audit: no future bars used by construction; completeness check
    gaps = None
    dates = [r['trade_date'] for r in norm]
    assert dates == sorted(dates) and len(set(dates)) == len(dates), 'index dates not clean'
    # 4) coverage matrix (NO outcomes computed)
    per_case, cov = {}, defaultdict(lambda: defaultdict(lambda: {'dates': set(), 'cases': 0}))
    for c in cases:
        T = c['T']
        reg = regime_at(norm, T)
        per_case[c['ordinal']] = {'T': T, 'regime': reg,
                                  'etf_expansion': etf_cell[c['ordinal']]}
        if reg:
            for rel in ELIGIBLE_RELATIONS:
                side = rel.split('_')[1] if rel == 'ETF_4_vs_8' else '8'
                a, b = (4, 8) if rel == 'ETF_4_vs_8' else (8, 9)
                if etf_cell[c['ordinal']] in (str(a), str(b)):
                    cell = f'cell{etf_cell[c["ordinal"]]}'
                    k = f'{cell}|{reg}'
                    cov[rel][k]['dates'].add(T)
                    cov[rel][k]['cases'] += 1
    covm = {rel: {k: {'distinct_dates': len(v['dates']), 'cases': v['cases']}
                  for k, v in cells.items()} for rel, cells in cov.items()}
    insufficient = []
    for rel, cells in covm.items():
        for k, v in cells.items():
            if v['distinct_dates'] < MIN_DISTINCT_DATES_PER_CELL_REGIME:
                insufficient.append({'relation': rel, 'cell_regime': k, **v})
    coverage = {
        'index_inventory': inventory, 'manifest': manifest,
        'regime_definition': {'window_trading_days': WINDOW,
                              'rule': f'close(T-1) vs median(close of last {WINDOW} trading days ending T-1, all trade_date < T)',
                              'values': ['UP', 'DOWN']},
        'per_case_regime': {str(k): v for k, v in per_case.items()},
        'cell_regime_coverage': covm,
        'insufficient_context_coverage':
            insufficient or 'NONE — every eligible cell×regime stratum has >= '
            f'{MIN_DISTINCT_DATES_PER_CELL_REGIME} distinct observation dates',
        'note': 'coverage matrix contains dates/counts only; NO path outcomes '
                'or relation statistics were computed in I4A',
    }
    (OUT / 'i4a_coverage_matrix.json').write_text(
        json.dumps(coverage, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    up = sum(1 for v in per_case.values() if v['regime'] == 'UP')
    dn = sum(1 for v in per_case.values() if v['regime'] == 'DOWN')
    non = sum(1 for v in per_case.values() if v['regime'] is None)
    print(json.dumps({'rows_fetched': len(norm), 'cases': len(cases),
                      'regime_UP': up, 'regime_DOWN': dn, 'regime_insufficient_history': non,
                      'insufficient_strata': len(insufficient)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
