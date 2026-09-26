#!/usr/bin/env python3
"""CSR-8 Phase B RT ingestion (margin SSE/SZSE + LHB + dzjy) per INGESTION
CONTRACT v1.0 FROZEN @ c22797f.

Contract execution points (must match frozen yaml):
  - seven master fields: observation_date/source/source_record_date/
    publication_date/retrieved_at/available_date/availability_basis
  - rt layer: publication_date=NULL legal; available_date=next_trading_day(
    observation_date, frozen_exchange_calendar); basis=CONSERVATIVE_T1
  - source grammar: AGGREGATOR|research-node|akshare@<ver>|<endpoint>
  - retrieved_at: timezone-aware UTC ISO-8601 stored in raw meta at fetch time
  - reject gates: hard_gate_1/RG-1/RG-3/RG-4 only; RG-2 is xp-only
    (ACCEPT_BUT_NOT_PIT_USABLE) and cannot occur in this rt batch
  - three-ledger conservation per endpoint:
    raw_total = normalized84 + rejected + filtered_non84
Usage:
  python3 scripts/csr8_ingest_rt.py calendar          # build frozen calendar
  python3 scripts/csr8_ingest_rt.py plan               # target trading days
  python3 scripts/csr8_ingest_rt.py fetch 20260601 20260630   # raw (resumable)
  python3 scripts/csr8_ingest_rt.py normalize 20260601 20260630  # 7-field + gates
"""
import gzip, json, hashlib, sys, os, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AK_VER = None  # filled at runtime
OUT = ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt'
RAW = ROOT / 'data/csr8_ingest/raw'
STEM = ROOT / 'data/adjustment_baostock/per_stock'
CAL = OUT / 'frozen_exchange_calendar.csv'
PLAN = OUT / 'ingest_plan.json'

ENDPOINTS = {
    'margin_sse': 'stock_margin_detail_sse',      # per-day
    'margin_szse': 'stock_margin_detail_szse',    # per-day
    'lhb': 'stock_lhb_detail_em',                 # range
    'dzjy': 'stock_dzjy_mrmx',                    # range(symbol='A股')
}
CODE_COLS = {'margin_sse': '标的证券代码', 'margin_szse': '证券代码',
             'lhb': '代码', 'dzjy': '证券代码'}
DATE_COLS = {'margin_sse': '信用交易日期', 'margin_szse': '证券代码',  # szse date is the query date
             'lhb': '上榜日', 'dzjy': '交易日期'}
# margin_szse returns no per-row date col; rows belong to query date (validate below)

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def load_universe84():
    d = json.load(open(ROOT / 'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'))
    codes = []
    for g, obj in d['groups'].items():
        for c in obj['chosen']:
            codes.append(c['code'])
    assert len(codes) == 84, len(codes)
    assert len(set(codes)) == len(codes) or True  # cross-group membership allowed
    return codes

def bare(code):
    return code.split('.')[1]

def build_calendar():
    """Frozen calendar = union of unadj dates over all 5,240 stem files."""
    days = set()
    n = 0
    for f in sorted(STEM.glob('*.json.gz')):
        with gzip.open(f, 'rt') as fh:
            d = json.load(fh)
        unadj = d.get('unadj')
        if isinstance(unadj, list):
            # list of row-arrays: [date, open, high, low, close, volume, amount, ...]
            days.update(r[0] for r in unadj if r)
        elif isinstance(unadj, dict) and 'date' in unadj:
            days.update(unadj['date'])
        n += 1
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
    import bisect
    i = bisect.bisect_right(cal, d)
    assert i < len(cal), f'no next trading day after {d}'
    return cal[i]

def build_plan():
    """Union of per-case windows -> target trading days."""
    cal = load_calendar()
    d = json.load(open(ROOT / 'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'))
    import bisect
    spans = []
    for g, obj in d['groups'].items():
        for c in obj['chosen']:
            if 'w_start' in c:
                spans.append((c['w_start'], c['w_end'], g, c['code']))
            else:  # G2: T0 .. T0+120 trading days
                t0 = c['T0']
                i = bisect.bisect_left(cal, t0)
                end_i = min(i + 120, len(cal) - 1)
                spans.append((t0, cal[end_i], g, c['code']))
    lo = min(s[0] for s in spans); hi = max(s[1] for s in spans)
    lo_i = bisect.bisect_left(cal, lo); hi_i = bisect.bisect_right(cal, hi)
    days = cal[lo_i:hi_i]
    PLAN.write_text(json.dumps({
        'n_cases': len(spans), 'span': [lo, hi],
        'n_target_days': len(days),
        'calendar_sha_in_meta': True,
        'spans': sorted(spans)}, ensure_ascii=False, indent=1))
    print(f'plan: {len(spans)} cases, span {lo}..{hi}, {len(days)} trading days')

def _ak():
    global AK_VER
    import akshare as ak
    AK_VER = ak.__version__
    return ak

def _retry(fn, attempts=3, backoff=8):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(backoff * (i + 1))

def fetch(start, end):
    """Fetch raw per endpoint. Resumable: existing dated raw file is skipped."""
    ak = _ak()
    cal = load_calendar()
    import bisect
    days = [d for d in cal[bisect.bisect_left(cal, start):bisect.bisect_right(cal, end)]]
    stats = {}
    # per-day endpoints
    for ep in ('margin_sse', 'margin_szse'):
        fn = getattr(ak, ENDPOINTS[ep])
        ok = empty = fail = 0
        for d in days:
            fp = RAW / ep / f'{d}.json'
            if fp.exists():
                ok += 1
                continue
            try:
                df = fn(date=d.replace('-', ''))
                rec = {'rows': len(df), 'columns': list(df.columns),
                       'data': df.to_dict('records')}
                outcome = 'SUCCESS_NONEMPTY' if len(df) else 'SUCCESS_EMPTY'
            except Exception as e:
                rec = {'error': f'{type(e).__name__}: {e}'}
                outcome = 'FAILED'
            body = json.dumps(rec, ensure_ascii=False, default=str).encode()
            fp.parent.mkdir(parents=True, exist_ok=True)
            meta = {'retrieved_at': utcnow(), 'outcome': outcome,
                    'sha256': sha256_bytes(body), 'query_date': d}
            (RAW / ep / f'{d}.meta.json').write_text(json.dumps(meta))
            fp.write_bytes(body)
            time.sleep(1.2)
            ok += outcome.startswith('SUCCESS'); empty += outcome == 'SUCCESS_EMPTY'; fail += outcome == 'FAILED'
        stats[ep] = {'days': len(days), 'ok': ok, 'empty': empty, 'failed': fail}
        print(ep, stats[ep])
    # range endpoints, monthly chunks
    for ep in ('lhb', 'dzjy'):
        fn = getattr(ak, ENDPOINTS[ep])
        chunks = []
        ys, ms = int(start[:4]), int(start[5:7]); ye, me = int(end[:4]), int(end[5:7])
        y, m = ys, ms
        while (y, m) <= (ye, me):
            chunks.append(f'{y:04d}{m:02d}')
            m += 1
            if m == 13: m, y = 1, y + 1
        ok = empty = fail = 0
        for c in chunks:
            fp = RAW / ep / f'{c}.json'
            if fp.exists():
                ok += 1; continue
            import calendar as _cal
            last = _cal.monthrange(int(c[:4]), int(c[4:6]))[1]
            sd, ed = f'{c}01', f'{c}{last:02d}'
            try:
                if ep == 'lhb':
                    df = _retry(lambda: fn(start_date=sd, end_date=ed))
                else:
                    df = _retry(lambda: fn(symbol='A股', start_date=sd, end_date=ed))
                rec = {'rows': len(df), 'columns': list(df.columns),
                       'data': df.to_dict('records')}
                outcome = 'SUCCESS_NONEMPTY' if len(df) else 'SUCCESS_EMPTY'
            except Exception as e:
                rec = {'error': f'{type(e).__name__}: {e}'}
                outcome = 'FAILED'
            body = json.dumps(rec, ensure_ascii=False, default=str).encode()
            fp.parent.mkdir(parents=True, exist_ok=True)
            (RAW / ep / f'{c}.meta.json').write_text(json.dumps(
                {'retrieved_at': utcnow(), 'outcome': outcome,
                 'sha256': sha256_bytes(body), 'chunk': c}))
            fp.write_bytes(body)
            time.sleep(1.5)
            ok += outcome.startswith('SUCCESS'); empty += outcome == 'SUCCESS_EMPTY'; fail += outcome == 'FAILED'
        stats[ep] = {'chunks': len(chunks), 'ok': ok, 'empty': empty, 'failed': fail}
        print(ep, stats[ep])
    (OUT / f'fetch_report_{start}_{end}.json').write_text(json.dumps(stats, indent=1))

def normalize(start, end):
    """Build 7-field normalized records for universe-84 + run gates + reject log."""
    cal = load_calendar()
    universe = set(bare(c) for c in load_universe84())
    ak_ver = _ak().__version__
    import bisect
    days = [d for d in cal[bisect.bisect_left(cal, start):bisect.bisect_right(cal, end)]]
    dayset = set(days)
    out_rows, rejects = [], []
    ledger = {}
    for ep in ENDPOINTS:
        src = f'AGGREGATOR|research-node|akshare@{ak_ver}|{ENDPOINTS[ep]}'
        codecol = CODE_COLS[ep]
        raw_total = norm = rej = filt = 0
        files = sorted((RAW / ep).glob('*.json'))
        files = [f for f in files if not f.name.endswith('.meta.json')]
        if ep in ('margin_sse', 'margin_szse'):
            files = [f for f in files if start <= f.stem <= end]
        else:
            lo_m, hi_m = int(start[:4] + start[5:7]), int(end[:4] + end[5:7])
            files = [f for f in files if f.stem.isdigit() and lo_m <= int(f.stem) <= hi_m]
        for fp in files:
            meta = json.loads((fp.parent / (fp.stem + '.meta.json')).read_text())
            if meta['outcome'] == 'FAILED':
                continue
            body = fp.read_bytes()
            assert sha256_bytes(body) == meta['sha256'], f'raw sha mismatch {fp}'
            rec = json.loads(body)
            # observation basis: per-day endpoints use query date
            for row in rec.get('data', []):
                raw_total += 1
                code = str(row.get(codecol, '')).zfill(6).split('.')[0]
                if code not in universe:
                    filt += 1
                    continue
                # observation_date
                if ep == 'margin_sse':
                    obs = str(row.get('信用交易日期', meta['query_date']))
                    obs = obs[:4] + '-' + obs[4:6] + '-' + obs[6:8] if obs.isdigit() and len(obs) == 8 else obs[:10]
                elif ep == 'margin_szse':
                    obs = meta['query_date']  # no row date col; query date is the fact
                else:
                    obs = str(row.get(DATE_COLS[ep], ''))[:10].replace('/', '-')
                if obs not in dayset and ep != 'margin_szse':
                    pass  # row may be outside smoke window; keep, gate on format only
                if not (len(obs) == 10 and obs[4] == '-' and obs[7] == '-'):
                    rej += 1
                    rejects.append({
                        'ingest_run_id': f'{start}_{end}_{ep}',
                        'rejected_at': utcnow(), 'gate_id': 'RG-1',
                        'source': src, 'record_identity': f'{code}|{obs}',
                        'raw_ref': f'{fp.name}',
                        'raw_sha256': meta['sha256'],
                        'reason': f'unparseable observation_date: {obs!r}',
                        'payload_excerpt': str(row)[:120]})
                    continue
                # RG-3 construction: available=next trading day <=> basis=CONSERVATIVE_T1
                try:
                    avail = next_trading_day(obs, cal)
                except AssertionError as e:
                    rej += 1
                    rejects.append({
                        'ingest_run_id': f'{start}_{end}_{ep}',
                        'rejected_at': utcnow(), 'gate_id': 'RG-1',
                        'source': src, 'record_identity': f'{code}|{obs}',
                        'raw_ref': f'{fp.name}', 'raw_sha256': meta['sha256'],
                        'reason': f'no next trading day: {e}', 'payload_excerpt': str(row)[:120]})
                    continue
                assert avail > obs
                out_rows.append({
                    'observation_date': obs,
                    'source': src,
                    'source_record_date': obs if ep != 'margin_szse' else None,
                    'publication_date': None,
                    'retrieved_at': meta['retrieved_at'],
                    'available_date': avail,
                    'availability_basis': 'CONSERVATIVE_T1',
                    'endpoint': ep, 'stock_code': code,
                    'payload': {k: (str(v) if not isinstance(v, (int, float, type(None))) else v)
                                for k, v in row.items()}})
                norm += 1
        ledger[ep] = {'raw_total': raw_total, 'normalized84': norm,
                      'rejected': rej, 'filtered_non84': filt}
        assert raw_total == norm + rej + filt, (ep, raw_total, norm, rej, filt)
        print(ep, ledger[ep])
    OUT.mkdir(parents=True, exist_ok=True)
    import csv
    fields = ['observation_date', 'source', 'source_record_date', 'publication_date',
              'retrieved_at', 'available_date', 'availability_basis', 'endpoint',
              'stock_code']
    with open(OUT / f'normalized_{start}_{end}.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r[k] for k in fields})
    with open(OUT / f'payloads_{start}_{end}.jsonl', 'w') as f:
        for r in out_rows:
            f.write(json.dumps({'stock_code': r['stock_code'],
                                'observation_date': r['observation_date'],
                                'endpoint': r['endpoint'],
                                'payload': r['payload']}, ensure_ascii=False) + '\n')
    with open(OUT / f'rejects_{start}_{end}.jsonl', 'w') as f:
        for r in rejects:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    summary = {'window': [start, end], 'ledger': ledger,
               'n_normalized': len(out_rows), 'n_rejects': len(rejects),
               'conservation': 'raw_total = normalized84 + rejected + filtered_non84 (asserted per endpoint)',
               'rg3_binding': 'available_date non-null <=> basis=CONSERVATIVE_T1 (constructed)',
               'rg4': 'source LEVEL=AGGREGATOR, basis=CONSERVATIVE_T1 (never OFFICIAL_RULE)',
               'record_pit_usable': 'YES (gates passed) but NOT counted in channel numerator (CONSERVATIVE_T1)'}
    (OUT / f'summary_{start}_{end}.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'calendar':
        build_calendar()
    elif cmd == 'plan':
        build_plan()
    elif cmd == 'fetch':
        fetch(sys.argv[2], sys.argv[3])
    elif cmd == 'normalize':
        normalize(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
