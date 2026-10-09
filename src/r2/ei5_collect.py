#!/usr/bin/env python3
"""EI-5P prospective collector — candidate-triggered intraday capture.

Scope frozen 2026-10-09 by 老刘: only candidate pool (T-1 frozen scan), only
auction + 09:30-10:00 window, data only. Touches NO existing EOD logic.

Usage:
  ei5_collect.py --stage backfill --day 2026-10-09 --base 2026-10-08
  ei5_collect.py --stage auction  --day <T>          # live ~09:25:30
  ei5_collect.py --stage window   --day <T>          # live ~10:00:30
  ei5_collect.py --stage labels   --day <T>          # after close, backfill fwd labels

Outputs:
  data/r2/ei5/raw/<day>/<code>.json.zst
  data/r2/ei5/features/day=<day>.parquet
  data/r2/ei5/labels/ei5_labels.parquet
  data/r2/ei5/manifest.jsonl
  data/r2/ei5/coverage/<day>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANS = ROOT / 'data/r2/scans'
TDX = Path('/root/tdx_data/vipdoc')
EI5 = ROOT / 'data/r2/ei5'
COHORT_KEEP = {'CONFIRM_CANDIDATE', 'BUILD', 'WATCH'}
WIN_END = '1000'          # window upper bound (inclusive)
CST = timezone(timedelta(hours=8))
RAW_KEEP_DAYS = 90

SCHEMA_RAW = 'ei5raw/1'
SCHEMA_FEAT = 'ei5feat/1'


# ---------------------------------------------------------------- helpers
def now_cst() -> str:
    return datetime.now(CST).isoformat(timespec='seconds')


def git_sha() -> str:
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return 'unknown'


def mkt_prefix(code: str) -> str:
    return 'sh' if code[0] == '6' else ('bj' if code[0] in '48' else 'sz')


def qcode(code: str) -> str:
    return mkt_prefix(code) + code


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def _get(url: str, timeout: int = 15, gbk: bool = False, retries: int = 2) -> str:
    last = None
    for a in range(retries + 1):
        try:
            r = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(r, timeout=timeout).read()
            return data.decode('gbk', 'replace') if gbk else data.decode('utf-8', 'replace')
        except Exception as e:      # noqa: BLE001
            last = e
            if a < retries:
                time.sleep(0.8 * (a + 1))
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------- cohort
def resolve_base(day: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    snaps = sorted(p.stem[-10:] for p in SCANS.glob('current_scan_*.json'))
    prior = [d for d in snaps if d < day]
    if not prior:
        raise SystemExit(f'no scan snapshot before {day}; use --base')
    return prior[-1]


def load_cohort(base_day: str) -> tuple[list[dict], dict]:
    snap = SCANS / f'current_scan_{base_day}.json'
    if not snap.exists():
        raise SystemExit(f'missing {snap}')
    d = json.load(open(snap))
    cards = [c for c in d['cards'] if c.get('capital_support') and c.get('decision')]
    out = []
    for c in cards:
        dec = c['decision']; cs = c['capital_support']
        if dec['decision_tier'] in COHORT_KEEP or cs['support_state'] in ('IN_SUPPORT', 'UNDERCUT_TEST'):
            out.append({
                'code': c['stock'], 'name': c.get('name') or '',
                'tier': dec['decision_tier'], 'support_state': cs['support_state'],
                'band_low': cs.get('cost_band_low'), 'band_high': cs.get('cost_band_high'),
            })
    meta = {'base_day': base_day, 'scan_generated': d.get('generated'), 'asof_ym': d.get('asof_ym'),
            'n_cards': len(d['cards']), 'n_cohort': len(out)}
    return out, meta


# ---------------------------------------------------------------- sources
def quotes(codes: list[str], sleep: float = 0.4) -> dict:
    """Batch qt.gtimg snapshot (60 per request). Used for auction + backfill prev_close."""
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 60):
        batch = codes[i:i + 60]
        pre = ','.join(qcode(c) for c in batch)
        try:
            s = _get('http://qt.gtimg.cn/q=' + pre, gbk=True)
        except Exception:                                  # noqa: BLE001
            continue
        for line in s.split(';'):
            if '~' not in line:
                continue
            f = line.split('~')
            if len(f) < 40:
                continue
            def fl(k):
                try:
                    return float(f[k]) if f[k] not in ('', '-') else 0.0
                except ValueError:
                    return 0.0
            out[f[2]] = {'name': f[1], 'last': fl(3), 'prev_close': fl(4), 'open': fl(5),
                         'vol': fl(6), 'amount_wan': fl(37), 'pct': fl(32),
                         'high': fl(33), 'low': fl(34), 'ts': f[30] if len(f) > 30 else ''}
        time.sleep(sleep)
    return out


def fetch_minute(code: str) -> tuple[str, list]:
    """Return (yyyymmdd, bars) where bars = [[HHMM, price, cumvol_hand, cumamt_yuan], ...]."""
    s = _get(f'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={qcode(code)}')
    j = json.loads(s)
    node = j.get('data', {}).get(qcode(code), {})
    if not node or node.get('data') is None:
        raise ValueError('no data node')
    blk = node['data']
    date = str(blk.get('date') or '')
    bars = []
    for row in blk.get('data', []):
        p = row.split()
        if len(p) < 4:
            continue
        try:
            bars.append([p[0], float(p[1]), float(p[2]), float(p[3])])
        except ValueError:
            continue
    if not bars:
        raise ValueError('empty bars')
    return date, bars


def tdx_daily(code: str, before_day: str, n: int = 20) -> dict | None:
    """Last n trading days strictly BEFORE day: avg volume(hand), avg amount(yuan), prev close."""
    p = TDX / mkt_prefix(code) / 'lday' / f'{qcode(code)}.day'
    if not p.exists():
        return None
    b = p.read_bytes()
    cut = int(str(before_day).replace('-', ''))
    recs = []
    for i in range(len(b) // 32):
        d, o, h, l, c, amt, vol, _ = struct.unpack('<IIIIIfII', b[i * 32:(i + 1) * 32])
        if d < cut:
            recs.append((str(d), c / 100.0, amt, vol / 100.0))
    if not recs:
        return None
    tail = recs[-n:]
    return {'n_days': len(tail),
            'avg_vol': sum(x[3] for x in tail) / len(tail),
            'avg_amt': sum(x[2] for x in tail) / len(tail),
            'prev_close': recs[-1][1],
            'last_hist_day': recs[-1][0]}


# ---------------------------------------------------------------- features
def compute_features(day, base_day, row, q, bars, base20, stage) -> dict:
    code = row['code']
    fx = {'schema': SCHEMA_FEAT, 'day': day, 'code': code, 'base_day': base_day,
          'name': (q or {}).get('name') or row['name'], 'tier': row['tier'],
          'support_state': row['support_state'], 'band_low': row['band_low'],
          'band_high': row['band_high'], 'stage': stage,
          'src_date': '', 'n_bars': 0, 'fetched_at': now_cst()}

    q = q or {}
    prev_close = q.get('prev_close') or (base20 or {}).get('prev_close')
    a_price = q.get('open') or 0.0                       # 竞价价 = 今开
    if not a_price and bars:
        a_price = bars[0][1]
    fx.update({
        'auction_price': a_price, 'auction_prev_close': prev_close,
        'auction_gap': (a_price / prev_close - 1) if (a_price and prev_close) else None,
        'auction_vol': bars[0][2] if bars else None,
        'auction_amt': bars[0][3] if bars else None,
    })

    if base20:
        fx['avg20_vol'] = base20['avg_vol']
        fx['avg20_amt'] = base20['avg_amt']
        fx['has_20d'] = True
        if bars and base20['avg_vol']:
            fx['auction_vol_ratio'] = bars[0][2] / base20['avg_vol']
        if bars and base20['avg_amt']:
            fx['auction_amt_ratio'] = bars[0][3] / base20['avg_amt']
    else:
        fx['avg20_vol'] = None; fx['avg20_amt'] = None; fx['has_20d'] = False

    if not bars:
        return fx

    win = [b for b in bars if b[0] <= WIN_END]
    fx['src_date'] = day.replace('-', '')
    fx['n_bars'] = len(win)
    fx['first_hhmm'] = win[0][0]
    fx['last_hhmm'] = win[-1][0]
    if len(win) < 3:
        fx['partial'] = True
        return fx

    # per-minute deltas
    vs, ams, rs, ps = [], [], [], []
    for i in range(1, len(win)):
        p0, p1 = win[i - 1][1], win[i][1]
        v = max(win[i][2] - win[i - 1][2], 0.0)
        a = max(win[i][3] - win[i - 1][3], 0.0)
        vs.append(v); ams.append(a); rs.append((p1 / p0 - 1) if p0 else 0.0); ps.append(p1)
    win_vol, win_amt = sum(vs), sum(ams)
    p_last = win[-1][1]
    p_peak = max(ps) if ps else p_last
    p_low = min(ps) if ps else p_last
    disp = (p_last / a_price - 1) if a_price else None
    fx.update({'win_vol': win_vol, 'win_amt': win_amt, 'close_1000': p_last, 'disp': disp,
               'up_amt': sum(ams[i] for i in range(len(ams)) if rs[i] > 0),
               'dn_amt': sum(ams[i] for i in range(len(ams)) if rs[i] < 0),
               'range_cproxy': (p_peak / p_low - 1) if p_low else None,
               'retrace_from_peak': (p_last / p_peak - 1) if p_peak else None,
               'time_to_peak_frac': (ps.index(p_peak) / len(ps)) if ps else None})
    if base20 and base20['avg_amt']:
        fx['win_amt_ratio'] = win_amt / base20['avg_amt']
    if base20 and base20['avg_vol']:
        fx['win_vol_ratio'] = win_vol / base20['avg_vol']
    if fx.get('win_amt_ratio'):
        fx['PE1'] = disp / fx['win_amt_ratio'] if disp is not None else None
    if fx.get('win_vol_ratio'):
        fx['PE2'] = disp / fx['win_vol_ratio'] if disp is not None else None
    fx['PE3'] = (fx['dn_amt'] / fx['up_amt']) if fx.get('up_amt') else None
    # 尾段/峰后缩量
    n = len(vs)
    if n >= 10:
        fx['tail_vol_ratio'] = sum(vs[int(n * 2 / 3):]) / sum(vs[:int(n / 3)]) if sum(vs[:int(n / 3)]) else None
    pk = ps.index(p_peak) if ps else 0
    pre = sum(vs[:pk]); post = sum(vs[pk:])
    fx['peak_dn_vol_ratio'] = (post / pre) if pre else None
    if len(win) < 25:
        fx['partial'] = True
    return fx


# ---------------------------------------------------------------- io
def write_raw_day(day: str, stage: str, items: list[tuple[str, dict]]) -> tuple[Path, dict]:
    """Freeze raw for one (day, stage) as a single zstd jsonl (1 line per code).

    Single-file layout: ~0.7 MB/day net (vs 4.1 MB on disk when split into 1036
    tiny files, due to 4K block padding), and stages never clobber each other.
    """
    import zstandard as zstd
    d = EI5 / 'raw'
    d.mkdir(parents=True, exist_ok=True)
    p = d / f'{day}_{stage}.jsonl.zst'
    merged: dict[str, str] = {}
    if p.exists():                       # merge: never lose already-frozen codes
        prev = zstd.ZstdDecompressor().decompress(p.read_bytes(), max_output_size=1 << 30).decode()
        for ln in prev.splitlines():
            if ln:
                merged[json.loads(ln)['code']] = ln
    lines, hashes = [], {}
    for code, payload in sorted(items):
        canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        merged[code] = canon
        hashes[code] = sha256_text(canon)
    for code in sorted(merged):
        lines.append(merged[code])
    blob = ('\n'.join(lines) + '\n').encode('utf-8')
    tmp = p.with_suffix('.tmp')
    tmp.write_bytes(zstd.ZstdCompressor(level=10).compress(blob))
    tmp.replace(p)
    return p, hashes


def upsert_parquet(path: Path, rows: list[dict], key=('day', 'code')) -> None:
    import pandas as pd
    new = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_parquet(path)
        old = old.set_index(list(key))
        newi = new.set_index(list(key))
        old = old[~old.index.isin(newi.index)]          # drop replaced keys
        out = pd.concat([old, newi]).sort_index().reset_index()
    else:
        out = new
    tmp = path.with_suffix('.tmp.parquet')
    out.to_parquet(tmp, index=False)
    tmp.replace(path)


def append_manifest(path: Path, recs: list[dict]) -> None:
    keyed = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                keyed[(r['day'], r['code'], r['stage'])] = r
            except Exception:                              # noqa: BLE001
                pass
    for r in recs:
        keyed[(r['day'], r['code'], r['stage'])] = r
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w') as fh:
        for k in sorted(keyed):
            fh.write(json.dumps(keyed[k], ensure_ascii=False) + '\n')
    tmp.replace(path)


# ---------------------------------------------------------------- labels
def stage_labels(day: str) -> dict:
    import pandas as pd
    fpath = EI5 / 'features' / f'day={day}.parquet'
    if not fpath.exists():
        raise SystemExit(f'no features for {day}; run window/backfill first')
    df = pd.read_parquet(fpath)
    rows = []
    for _, r in df.iterrows():
        code = r['code']
        p = TDX / mkt_prefix(code) / 'lday' / f'{qcode(code)}.day'
        if not p.exists():
            continue
        b = p.read_bytes()
        recs = []
        for i in range(len(b) // 32):
            d, o, h, l, c, amt, vol, _ = struct.unpack('<IIIIIfII', b[i * 32:(i + 1) * 32])
            recs.append((str(d), o / 100, h / 100, l / 100, c / 100))
        idx = [i for i, x in enumerate(recs) if x[0] == day.replace('-', '')]
        if not idx:
            continue
        i0 = idx[0]
        base_c = recs[i0][4]
        out = {'day': day, 'code': code}
        for k in (1, 5, 10, 20):
            if i0 + k < len(recs):
                out[f'r{k}'] = recs[i0 + k][4] / base_c - 1
                seg = recs[i0 + 1:i0 + k + 1]
                out[f'mfe{k}'] = max(x[2] for x in seg) / base_c - 1
                out[f'mae{k}'] = min(x[3] for x in seg) / base_c - 1
            else:
                out[f'r{k}'] = None; out[f'mfe{k}'] = None; out[f'mae{k}'] = None
        rows.append(out)
    if rows:
        upsert_parquet(EI5 / 'labels' / 'ei5_labels.parquet', rows, key=('day', 'code'))
    return {'day': day, 'n_labeled': len(rows)}


# ---------------------------------------------------------------- main
def check_trading_day(day: str) -> tuple[bool, str]:
    """True if sh000001 quote timestamp date == day (i.e. auction already happened today)."""
    try:
        s = _get('http://qt.gtimg.cn/q=sh000001', gbk=True)
        f = s.split('~')
        ts = f[30] if len(f) > 30 else ''
        return ts[:8] == day.replace('-', ''), ts
    except Exception as e:                                 # noqa: BLE001
        return False, f'quote_err:{type(e).__name__}'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True, choices=['auction', 'window', 'backfill', 'labels'])
    ap.add_argument('--day', required=True, help='target trading day YYYY-MM-DD')
    ap.add_argument('--base', default=None, help='T-1 scan day (default: latest snapshot before --day)')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=0.1)
    ap.add_argument('--ignore-guard', action='store_true', help='skip trading-day gate')
    a = ap.parse_args()

    if a.stage in ('auction', 'window') and not a.ignore_guard:
        okd, ts = check_trading_day(a.day)
        if not okd:
            print(json.dumps({'day': a.day, 'stage': a.stage, 'skipped': 'NOT_TRADING_DAY',
                              'quote_ts': ts}, ensure_ascii=False))
            return

    if a.stage == 'labels':
        print(json.dumps(stage_labels(a.day), ensure_ascii=False)); return

    for sub in ('features', 'labels', 'coverage', 'raw'):
        (EI5 / sub).mkdir(parents=True, exist_ok=True)

    base_day = resolve_base(a.day, a.base)
    cohort, meta = load_cohort(base_day)
    if a.limit:
        cohort = cohort[:a.limit]
    codes = [c['code'] for c in cohort]
    t0 = time.time()
    print(f'[{a.stage}] day={a.day} base={base_day} cohort={len(codes)} '
          f'(scan cards={meta["n_cards"]})', flush=True)

    q = quotes(codes, sleep=0.4)
    rows_f, man, fails, ok = [], [], [], 0
    raw_items: list[tuple[str, dict]] = []

    for n, row in enumerate(cohort, 1):
        code = row['code']
        try:
            bars, src_date = [], ''
            if a.stage in ('window', 'backfill'):
                src_date, allbars = fetch_minute(code)
                if src_date != a.day.replace('-', ''):
                    raise ValueError(f'stale_date:{src_date}')
                bars = [b for b in allbars if b[0] <= WIN_END]
                time.sleep(a.sleep)
            base20 = tdx_daily(code, a.day)
            fx = compute_features(a.day, base_day, row, q.get(code), bars, base20, a.stage)
            payload = {'schema': SCHEMA_RAW, 'code': code, 'day': a.day, 'base_day': base_day,
                       'stage': a.stage, 'source': 'tencent:ifzq.minute+qt.gtimg',
                       'fetched_at': now_cst(), 'git_sha': git_sha(),
                       'quote': q.get(code), 'bars': bars}
            raw_items.append((code, payload))
            rows_f.append(fx)
            ok += 1
        except Exception as e:                             # noqa: BLE001
            fails.append({'code': code, 'err': f'{type(e).__name__}:{e}'[:160]})
            man.append({'day': a.day, 'code': code, 'stage': a.stage, 'base_day': base_day,
                        'ok': False, 'err': f'{type(e).__name__}:{e}'[:160],
                        'fetched_at': now_cst(), 'git_sha': git_sha()})
        if n % 100 == 0:
            print(f'  ...{n}/{len(codes)} ok={ok} fail={len(fails)} '
                  f'{time.time()-t0:.0f}s', flush=True)

    raw_path, raw_bytes = '', 0
    if raw_items:
        p, hashes = write_raw_day(a.day, a.stage, raw_items)
        raw_path, raw_bytes = str(p.relative_to(ROOT)), p.stat().st_size
        for fx in rows_f:
            man.append({'day': a.day, 'code': fx['code'], 'stage': a.stage, 'base_day': base_day,
                        'raw_path': raw_path, 'raw_sha256': hashes.get(fx['code'], ''),
                        'n_bars': fx.get('n_bars'), 'src_date': fx.get('src_date', ''),
                        'source': 'tencent:ifzq.minute+qt.gtimg', 'fetched_at': fx['fetched_at'],
                        'git_sha': git_sha(), 'ok': True})
    if rows_f:
        upsert_parquet(EI5 / 'features' / f'day={a.day}.parquet', rows_f)
    append_manifest(EI5 / 'manifest.jsonl', man)

    cov = {'day': a.day, 'base_day': base_day, 'stage': a.stage, 'cohort': len(codes),
           'ok': ok, 'fail': len(fails), 'coverage': round(ok / max(len(codes), 1), 4),
           'fail_reasons': {}, 'raw_file': raw_path, 'raw_bytes': raw_bytes,
           'elapsed_s': round(time.time() - t0, 1), 'git_sha': git_sha(), 'run_at': now_cst()}
    for f in fails:
        k = f['err'].split(':')[0]
        cov['fail_reasons'][k] = cov['fail_reasons'].get(k, 0) + 1
    (EI5 / 'coverage').mkdir(parents=True, exist_ok=True)
    (EI5 / 'coverage' / f'{a.day}_{a.stage}.json').write_text(
        json.dumps(cov, ensure_ascii=False, indent=1))
    print(json.dumps(cov, ensure_ascii=False))
    if fails[:5]:
        print('sample fails:', json.dumps(fails[:5], ensure_ascii=False))


if __name__ == '__main__':
    main()