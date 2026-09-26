#!/usr/bin/env python3
"""CSR-8 Phase B RT ingestion runner — HARDENED per RT-RUNNER-HARDENING audit.

Contract: INGESTION CONTRACT v1.0 FROZEN @ c22797f.
Hardening (vs 7abedaa):
  H1 FAILED-resume: a raw file is skippable only if meta exists,
     outcome in SUCCESS_*, and SHA256 re-verification passes; anything
     else (FAILED / missing meta / sha mismatch) is re-fetched.
     margin endpoints get retry/backoff like lhb.
  H2 request-level completeness: expected = SUCCESS_NONEMPTY +
     SUCCESS_EMPTY + FAILED; batch is COMPLETE only if FAILED=0 and all
     SHAs verify; otherwise PARTIAL (not a final ingestion artifact).
     manifest builder is a first-class command.
  H3 fetch-time provenance: raw meta stores akshare_version + endpoint +
     exact request args; normalize builds `source` from raw meta, never
     from the runtime environment.
  H4 case-window projection: raw -> normalized_universe84 ->
     normalized_case84. Two conservation ledgers:
       raw_total = outside_request + non84 + rejected + universe84
       universe84 = case_window + outside_case_window
     blind packets consume normalized_case84 only.
Five artifacts per batch: request/raw manifest, completeness summary,
normalized_universe84, normalized_case84, reject log.

Usage:
  calendar | plan | fetch START END | manifest START END | normalize START END
Batching policy (audit): margin per trading day (run by half-year windows);
lhb/dzjy monthly chunks independent of margin boundaries; edge months may be
fetched whole but normalize filters to the request window.
"""
import gzip, json, hashlib, sys, os, time, bisect, calendar as _calmod
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt'
RAW = ROOT / 'data/csr8_ingest/raw'
STEM = ROOT / 'data/adjustment_baostock/per_stock'
CAL = OUT / 'frozen_exchange_calendar.csv'
PLAN = OUT / 'ingest_plan.json'
SAMPLE = ROOT / 'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'

ENDPOINTS = {
    'margin_sse': 'stock_margin_detail_sse',      # per-day
    'margin_szse': 'stock_margin_detail_szse',    # per-day
    'lhb': 'stock_lhb_detail_em',                 # range
    'dzjy': 'stock_dzjy_mrmx',                    # range(symbol='A股')
}
CODE_COLS = {'margin_sse': '标的证券代码', 'margin_szse': '证券代码',
             'lhb': '代码', 'dzjy': '证券代码'}
SUCCESS_OUTCOMES = ('SUCCESS_NONEMPTY', 'SUCCESS_EMPTY')

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def _ak():
    import akshare as ak
    return ak

def _retry(fn, attempts=3, backoff=8):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(backoff * (i + 1))

def load_universe84():
    """84 unique codes (Phase A frozen multi-group=0) + asset provenance."""
    d = json.load(open(SAMPLE))
    codes = [c['code'] for g in d['groups'].values() for c in g['chosen']]
    assert len(codes) == 84, len(codes)
    assert len(set(codes)) == 84, 'multi-group membership must be 0 (frozen)'
    return codes

def bare(code):
    return code.split('.')[1]

def build_calendar():
    days = set()
    for f in sorted(STEM.glob('*.json.gz')):
        with gzip.open(f, 'rt') as fh:
            d = json.load(fh)
        unadj = d.get('unadj')
        if isinstance(unadj, list):
            days.update(r[0] for r in unadj if r)
        elif isinstance(unadj, dict) and 'date' in unadj:
            days.update(unadj['date'])
    days = sorted(days)
    OUT.mkdir(parents=True, exist_ok=True)
    body = 'date\n' + '\n'.join(days) + '\n'
    h = sha256_bytes(body.encode())
    CAL.write_text(f'# source=universe_stem_union(per_stock 5240 files, unadj dates)\n'
                   f'# n_days={len(days)} sha256={h}\n' + body)
    print(f'calendar: {len(days)} days, sha256={h}')

def load_calendar():
    lines = CAL.read_text().splitlines()
    meta = lines[1]
    days = [l for l in lines[3:] if l]
    h = sha256_bytes(('date\n' + '\n'.join(days) + '\n').encode())
    assert f'sha256={h}' in meta, 'calendar sha mismatch'
    return days

def next_trading_day(d, cal):
    """Strictly next trading day after d in frozen calendar (CONSERVATIVE_T1)."""
    i = bisect.bisect_right(cal, d)
    assert i < len(cal), f'no next trading day after {d}'
    return cal[i]

def build_plan():
    cal = load_calendar()
    d = json.load(open(SAMPLE))
    spans = []
    for g, obj in d['groups'].items():
        for c in obj['chosen']:
            if 'w_start' in c:
                spans.append([c['w_start'], c['w_end'], g, c['code']])
            else:  # G2: T0 .. T0+120 trading days
                t0 = c['T0']
                i = bisect.bisect_left(cal, t0)
                end_i = min(i + 120, len(cal) - 1)
                spans.append([t0, cal[end_i], g, c['code']])
    lo = min(s[0] for s in spans); hi = max(s[1] for s in spans)
    lo_i = bisect.bisect_left(cal, lo); hi_i = bisect.bisect_right(cal, hi)
    days = cal[lo_i:hi_i]
    sample_bytes = SAMPLE.read_bytes()
    PLAN.write_text(json.dumps({
        'n_cases': len(spans), 'span': [lo, hi],
        'n_target_days': len(days),
        'sample_selection_sha256': sha256_bytes(sample_bytes),
        'sample_selection_frozen_commit': '1cabde8 (Phase A FROZEN)',
        'calendar_sha_in_meta': True,
        'spans': sorted(spans)}, ensure_ascii=False, indent=1))
    print(f'plan: {len(spans)} cases, span {lo}..{hi}, {len(days)} trading days')

def load_plan_case_windows():
    """code(bare) -> (w_start, w_end) from frozen plan."""
    d = json.loads(PLAN.read_text())
    return {s[3].split('.')[1]: (s[0], s[1]) for s in d['spans']}

# ---------------- H1: valid-raw predicate ----------------
def _valid_raw(ep, stem):
    """Data integrity AND provenance integrity are the SAME skip gate (R2):
    raw+meta exist, outcome in SUCCESS_*, SHA verifies, retrieved_at /
    collector_version / request present, endpoint matches expected."""
    fp = RAW / ep / f'{stem}.json'
    mp = RAW / ep / f'{stem}.meta.json'
    if not (fp.exists() and mp.exists()):
        return False
    try:
        meta = json.loads(mp.read_text())
        if meta.get('outcome') not in SUCCESS_OUTCOMES:
            return False
        if not (meta.get('retrieved_at') and meta.get('collector_version')
                and meta.get('request')):
            return False
        if meta.get('endpoint') != ENDPOINTS[ep]:
            return False
        return sha256_bytes(fp.read_bytes()) == meta['sha256']
    except Exception:
        return False

def _write_raw(ep, stem, df_or_err, outcome, request_desc):
    ak = _ak()
    if isinstance(df_or_err, Exception):
        rec = {'error': f'{type(df_or_err).__name__}: {df_or_err}'}
    else:
        rec = {'rows': len(df_or_err), 'columns': list(df_or_err.columns),
               'data': df_or_err.to_dict('records')}
    body = json.dumps(rec, ensure_ascii=False, default=str).encode()
    fp = RAW / ep / f'{stem}.json'
    fp.parent.mkdir(parents=True, exist_ok=True)
    meta = {'retrieved_at': utcnow(), 'outcome': outcome,
            'sha256': sha256_bytes(body), 'query': stem,
            'collector_version': f'akshare@{ak.__version__}',
            'endpoint': ENDPOINTS[ep], 'request': request_desc}
    (RAW / ep / f'{stem}.meta.json').write_text(json.dumps(meta))
    fp.write_bytes(body)

def fetch(start, end):
    """Fetch raw per endpoint; resumable with H1 semantics + retry everywhere."""
    ak = _ak()
    cal = load_calendar()
    days = [d for d in cal[bisect.bisect_left(cal, start):bisect.bisect_right(cal, end)]]
    stats = {}
    for ep in ('margin_sse', 'margin_szse'):
        fn = getattr(ak, ENDPOINTS[ep])
        fetched = skipped = failed = 0
        for d in days:
            if _valid_raw(ep, d):
                skipped += 1
                continue
            req = {'date': d.replace('-', '')}
            try:
                df = _retry(lambda: fn(date=req['date']))
                outcome = 'SUCCESS_NONEMPTY' if len(df) else 'SUCCESS_EMPTY'
                _write_raw(ep, d, df, outcome, req)
            except Exception as e:
                _write_raw(ep, d, e, 'FAILED', req)
            time.sleep(1.2)
            fetched += 1; failed += not _valid_raw(ep, d)
        stats[ep] = {'expected': len(days), 'skipped_valid': skipped,
                     'attempted': fetched, 'failed_after_retry': failed}
        print(ep, stats[ep])
    chunks = []
    y, m = int(start[:4]), int(start[5:7]); ye, me = int(end[:4]), int(end[5:7])
    while (y, m) <= (ye, me):
        chunks.append(f'{y:04d}{m:02d}')
        m += 1
        if m == 13: m, y = 1, y + 1
    for ep in ('lhb', 'dzjy'):
        fn = getattr(ak, ENDPOINTS[ep])
        fetched = skipped = failed = 0
        for c in chunks:
            if _valid_raw(ep, c):
                skipped += 1
                continue
            last = _calmod.monthrange(int(c[:4]), int(c[4:6]))[1]
            sd, ed = f'{c}01', f'{c}{last:02d}'
            req = ({'start_date': sd, 'end_date': ed} if ep == 'lhb'
                   else {'symbol': 'A股', 'start_date': sd, 'end_date': ed})
            try:
                if ep == 'lhb':
                    df = _retry(lambda: fn(start_date=req['start_date'], end_date=req['end_date']))
                else:
                    df = _retry(lambda: fn(symbol=req['symbol'], start_date=req['start_date'], end_date=req['end_date']))
                outcome = 'SUCCESS_NONEMPTY' if len(df) else 'SUCCESS_EMPTY'
                _write_raw(ep, c, df, outcome, req)
            except Exception as e:
                _write_raw(ep, c, e, 'FAILED', req)
            time.sleep(1.5)
            fetched += 1; failed += not _valid_raw(ep, c)
        stats[ep] = {'expected': len(chunks), 'skipped_valid': skipped,
                     'attempted': fetched, 'failed_after_retry': failed}
        print(ep, stats[ep])
    (OUT / f'fetch_report_{start}_{end}.json').write_text(json.dumps(stats, indent=1))

# ---------------- H2: manifest + completeness ----------------
def manifest(start, end):
    """Build raw manifest + request-level completeness gate for [start,end]."""
    cal = load_calendar()
    days = [d for d in cal[bisect.bisect_left(cal, start):bisect.bisect_right(cal, end)]]
    chunks = []
    y, m = int(start[:4]), int(start[5:7]); ye, me = int(end[:4]), int(end[5:7])
    while (y, m) <= (ye, me):
        chunks.append(f'{y:04d}{m:02d}')
        m += 1
        if m == 13: m, y = 1, y + 1
    expected = {'margin_sse': days, 'margin_szse': days, 'lhb': chunks, 'dzjy': chunks}
    rows, summary = [], {}
    all_complete = True
    for ep, stems in expected.items():
        ok = empty = failed = missing = sha_bad = 0
        for stem in stems:
            mp = RAW / ep / f'{stem}.meta.json'
            if not _valid_raw(ep, stem):
                if mp.exists() and json.loads(mp.read_text()).get('outcome') == 'FAILED':
                    failed += 1
                    status = 'FAILED'
                elif mp.exists():
                    sha_bad += 1
                    status = 'SHA_MISMATCH_OR_INCOMPLETE'
                else:
                    missing += 1
                    status = 'MISSING'
                all_complete = False
                rows.append({'endpoint': ep, 'file': f'{ep}/{stem}.json',
                             'outcome': status, 'sha256': None,
                             'retrieved_at': None})
                continue
            meta = json.loads(mp.read_text())
            out = meta['outcome']
            ok += out == 'SUCCESS_NONEMPTY'; empty += out == 'SUCCESS_EMPTY'
            rows.append({'endpoint': ep, 'file': f'{ep}/{stem}.json',
                         'outcome': out, 'sha256': meta['sha256'],
                         'retrieved_at': meta['retrieved_at'],
                         'collector_version': meta.get('collector_version'),
                         'request': meta.get('request')})
        complete = (failed == 0 and missing == 0 and sha_bad == 0)
        summary[ep] = {'expected_requests': len(stems),
                       'SUCCESS_NONEMPTY': ok, 'SUCCESS_EMPTY': empty,
                       'FAILED': failed, 'MISSING': missing,
                       'SHA_BAD': sha_bad,
                       'batch_status': 'COMPLETE' if complete else 'PARTIAL'}
        all_complete = all_complete and complete
        print(ep, summary[ep])
    tag = 'COMPLETE' if all_complete else 'PARTIAL'
    with open(OUT / f'raw_manifest_{start}_{end}.jsonl', 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    summ = {'window': [start, end], 'batch_status': tag,
            'completeness_rule': 'expected = SUCCESS_NONEMPTY+SUCCESS_EMPTY+FAILED; '
                                 'COMPLETE iff FAILED=0, MISSING=0, SHA all verified',
            'per_endpoint': summary}
    (OUT / f'completeness_{start}_{end}.json').write_text(
        json.dumps(summ, ensure_ascii=False, indent=1))
    print('batch:', tag)
    return all_complete

def normalize(start, end):
    """H3/H4 hardened normalizer. source from raw meta; two conservation ledgers.
    R1: normalize enforces the completeness gate itself — a PARTIAL batch
    raises before any output is written (never relies on the operator
    remembering to run manifest first)."""
    if not manifest(start, end):
        raise RuntimeError(f'batch PARTIAL for {start}..{end}; normalization forbidden')
    cal = load_calendar()
    universe = {bare(c) for c in load_universe84()}
    case_win = load_plan_case_windows()
    days = [d for d in cal[bisect.bisect_left(cal, start):bisect.bisect_right(cal, end)]]
    dayset = set(days)
    out_rows, rejects = [], []
    ledger = {}
    for ep in ENDPOINTS:
        lo_m, hi_m = int(start[:4] + start[5:7]), int(end[:4] + end[5:7])
        fs = sorted(f for f in (RAW / ep).glob('*.json')
                    if not f.name.endswith('.meta.json'))
        if ep in ('margin_sse', 'margin_szse'):
            fs = [f for f in fs if start <= f.stem <= end]
        else:
            fs = [f for f in fs if f.stem.isdigit() and lo_m <= int(f.stem) <= hi_m]
        raw_total = outside_req = non84 = rej = norm = case_n = outside_case = 0
        for fp in fs:
            if not _valid_raw(ep, fp.stem):
                continue  # completeness gate covers this; PARTIAL batch refuses final use
            meta = json.loads((fp.parent / (fp.stem + '.meta.json')).read_text())
            rec = json.loads(fp.read_bytes())
            src = f"AGGREGATOR|research-node|{meta['collector_version']}|{meta['endpoint']}"
            for row in rec.get('data', []):
                raw_total += 1
                code = str(row.get(CODE_COLS[ep], '')).zfill(6).split('.')[0]
                if ep == 'margin_sse':
                    v = str(row.get('信用交易日期', meta['query']))
                    obs = (v[:4] + '-' + v[4:6] + '-' + v[6:8]
                           if v.isdigit() and len(v) == 8 else v[:10])
                elif ep == 'margin_szse':
                    obs = meta['query']
                else:
                    obs = str(row.get('上榜日' if ep == 'lhb' else '交易日期', ''))[:10].replace('/', '-')
                if obs not in dayset:  # H4: real request-window filter (was: pass)
                    outside_req += 1
                    continue
                if code not in universe:
                    non84 += 1
                    continue
                if not (len(obs) == 10 and obs[4] == '-' and obs[7] == '-'):
                    rej += 1
                    rejects.append(_reject(start, end, src, code, obs, fp, meta,
                                           'unparseable observation_date'))
                    continue
                try:
                    avail = next_trading_day(obs, cal)
                except AssertionError as e:
                    rej += 1
                    rejects.append(_reject(start, end, src, code, obs, fp, meta,
                                           f'no next trading day: {e}'))
                    continue
                in_case = case_win[code][0] <= obs <= case_win[code][1]
                out_rows.append({
                    'observation_date': obs, 'source': src,
                    'source_record_date': obs if ep != 'margin_szse' else None,
                    'publication_date': None,
                    'retrieved_at': meta['retrieved_at'],
                    'available_date': avail,
                    'availability_basis': 'CONSERVATIVE_T1',
                    'endpoint': ep, 'stock_code': code,
                    'in_case_window': in_case})
                norm += 1
                case_n += in_case
                outside_case += not in_case
        assert raw_total == outside_req + non84 + rej + norm, (ep, raw_total)
        assert norm == case_n + outside_case, (ep, norm, case_n, outside_case)
        ledger[ep] = {'raw_total': raw_total,
                      'filtered_outside_request_window': outside_req,
                      'filtered_non84': non84, 'rejected': rej,
                      'normalized_universe84': norm,
                      'normalized_case84': case_n,
                      'filtered_outside_case_window': outside_case}
        print(ep, ledger[ep])
    _write_outputs(start, end, out_rows, rejects, ledger)

def _reject(start, end, src, code, obs, fp, meta, reason):
    return {'ingest_run_id': f'{start}_{end}',
            'rejected_at': utcnow(), 'gate_id': 'RG-1',
            'source': src, 'record_identity': f'{code}|{obs}',
            'raw_ref': fp.name, 'raw_sha256': meta['sha256'],
            'reason': reason, 'payload_excerpt': ''}

def _write_outputs(start, end, rows, rejects, ledger):
    OUT.mkdir(parents=True, exist_ok=True)
    import csv
    fields = ['observation_date', 'source', 'source_record_date', 'publication_date',
              'retrieved_at', 'available_date', 'availability_basis', 'endpoint',
              'stock_code', 'in_case_window']
    for layer, sel in (('universe84', lambda r: True),
                       ('case84', lambda r: r['in_case_window'])):
        with open(OUT / f'normalized_{layer}_{start}_{end}.csv', 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                if sel(r):
                    w.writerow({k: r[k] for k in fields})
    with open(OUT / f'payloads_{start}_{end}.jsonl', 'w') as f:
        for r in rows:
            f.write(json.dumps({'stock_code': r['stock_code'],
                                'observation_date': r['observation_date'],
                                'endpoint': r['endpoint'],
                                'in_case_window': r['in_case_window']},
                               ensure_ascii=False) + '\n')
    with open(OUT / f'rejects_{start}_{end}.jsonl', 'w') as f:
        for r in rejects:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    n_u = len(rows); n_c = sum(r['in_case_window'] for r in rows)
    summary = {'window': [start, end], 'ledger': ledger,
               'conservation_L1': 'raw_total = outside_request + non84 + rejected + universe84 (asserted)',
               'conservation_L2': 'universe84 = case_window + outside_case_window (asserted)',
               'n_universe84': n_u, 'n_case84': n_c,
               'provenance': 'source built from raw meta collector_version+endpoint (H3)',
               'blind_packet_consumes': 'normalized_case84 only'}
    (OUT / f'summary_{start}_{end}.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print(f'universe84={n_u} case84={n_c}')

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'calendar':
        build_calendar()
    elif cmd == 'plan':
        build_plan()
    elif cmd == 'fetch':
        fetch(sys.argv[2], sys.argv[3])
    elif cmd == 'manifest':
        manifest(sys.argv[2], sys.argv[3])
    elif cmd == 'normalize':
        normalize(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
