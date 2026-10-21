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
import gzip
import hashlib
import json
import math
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'src') not in sys.path:                     # r2.* 导入引导（cron 环境无 PYTHONPATH）
    sys.path.insert(0, str(ROOT / 'src'))
SCANS = ROOT / 'data/r2/scans'
TDX = Path('/root/tdx_data/vipdoc')
EI5 = ROOT / 'data/r2/ei5'
DAILY_FM = ROOT / 'data/cd/daily_fullmarket'   # 主系统每日档（权威 factor 序列）
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
    """批量实时快照 —— 2026-10-21 起走 TDX 通道（退役腾讯 qt.gtimg.cn）。

    字段名与旧腾讯解析**同名同义**（last/prev_close/open/vol/amount_wan/pct/high/low/ts），
    调用方零改动。TDX 侧 vol 单位=手、amount 单位=元（故 /1e4 得万元），与旧 f[6]/f[37] 一致。
    """
    from r2.tdx_quotes import quotes as _tdx_quotes
    raw = _tdx_quotes(codes)
    return {c6: {'name': r['name'], 'last': r['price'], 'prev_close': r['last_close'],
                 'open': r['open'], 'vol': r['vol'],
                 'amount_wan': (r['amount'] or 0.0) / 1e4,
                 'pct': r['pct'], 'high': r['high'], 'low': r['low'], 'ts': r['ts']}
            for c6, r in raw.items()}


def fetch_minute(code: str) -> tuple[str, list]:
    """Return (yyyymmdd, bars) where bars = [[HHMM, price, cumvol_hand, cumamt_yuan], ...].

    2026-10-21：401/501 是突发限流（非端点失效），命中后退避重试一次；
    最终失败由 main 走平均值替代，不留空行。
    """
    url = f'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={qcode(code)}'
    # 2026-10-21 实测：突发限流返回 501（当天 179 次成功后全灭，7h 后自动恢复）。
    # 命中 403/429/501 → 退避 5s 重试一次；仍失败才抛错，由 main 走平均值替代。
    for att in range(2):
        try:
            s = _get(url, timeout=8, retries=0)
            break
        except urllib.error.HTTPError as e:
            if att == 0 and e.code in (403, 429, 501):
                time.sleep(5)
                continue
            raise
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


def _factor_series(code: str) -> dict:
    """主系统每日档的 adjust_factor_model_derived 序列 {'YYYY-MM-DD': f}；缺失返回 {}。"""
    p = DAILY_FM / f'{code}.json.gz'
    if not p.exists():
        return {}
    try:
        j = json.loads(gzip.decompress(p.read_bytes()))
        return dict(zip(j.get('dates') or [], j.get('adjust_factor_model_derived') or []))
    except Exception:
        return {}


def _ymd(d) -> str:
    s = str(d)
    return s if '-' in s else f'{s[:4]}-{s[4:6]}-{s[6:]}'


def _restate_vols(code: str, dates: list, vols: list) -> list:
    """把基线量重述到 T-1 股本口径：vol_restated_k = vol_raw_k * f_t1 / f_k。

    f = 主系统每日档 adjust_factor_model_derived（qfq/unadj）。送转除权前旧股本口径的
    量按因子比折算，消除 auction_vol_ratio 的系统性稀释；f 缺失/非正的天不重述。
    """
    fmap = _factor_series(code)
    if not fmap or not dates:
        return vols
    f_now = fmap.get(_ymd(dates[-1]))          # T-1 口径
    if not f_now or f_now <= 0:
        return vols
    out = []
    for d, v in zip(dates, vols):
        fk = fmap.get(_ymd(d))
        out.append(v * f_now / fk if (fk and fk > 0) else v)
    return out


def tdx_daily(code: str, before_day: str, n: int = 20) -> dict | None:
    """Last n trading days strictly BEFORE day: avg volume(hand, restated), avg amount(yuan), prev close.

    avg_vol 经主系统 factor 重述到 T-1 股本口径（送转不再稀释 auction_vol_ratio）；
    avg_vol_raw 保留未重述值备审计。
    """
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
    vols_raw = [x[3] for x in tail]
    vols = _restate_vols(code, [x[0] for x in tail], vols_raw)
    return {'n_days': len(tail),
            'avg_vol': sum(vols) / len(vols),
            'avg_vol_raw': sum(vols_raw) / len(vols_raw),
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
        fx['avg20_vol_raw'] = base20['avg_vol_raw']
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


# ---------------------------------------------------------------- impute
# 2026-10-21 老刘口径：分时源断掉时**不留空行**，直接用平均值替代。
# 不做百分百精确科研复现，只保面板连续/趋势可用；imputed 标记 + 原始错误留存备查。
IMPUTE_FIELDS = ['win_vol', 'win_amt', 'close_1000', 'disp', 'up_amt', 'dn_amt',
                 'range_cproxy', 'retrace_from_peak', 'time_to_peak_frac',
                 'win_amt_ratio', 'win_vol_ratio', 'PE1', 'PE2', 'PE3',
                 'tail_vol_ratio', 'peak_dn_vol_ratio']


def _num(v):
    """数值化：None/NaN/非数 → None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def load_hist_means(day: str, lookback: int = 10) -> dict:
    """该票历史窗口特征的平均值 —— {code: {field: mean, 'n_days': k}}（跳过已 imputed 行）。"""
    import pandas as pd
    d = EI5 / 'features'
    files = sorted(p for p in d.glob('day=*.parquet')
                   if p.stem.split('=', 1)[1] < day)[-lookback:]
    acc: dict = {}
    for p in files:
        try:
            df = pd.read_parquet(p)
        except Exception:                                  # noqa: BLE001
            continue
        for rec in df.to_dict('records'):
            if rec.get('imputed'):
                continue
            c = rec.get('code')
            if not c:
                continue
            for f in IMPUTE_FIELDS:
                v = _num(rec.get(f))
                if v is not None:
                    acc.setdefault(c, {}).setdefault(f, []).append(v)
    out: dict = {}
    for c, fs in acc.items():
        if not fs:
            continue
        out[c] = {f: sum(vs) / len(vs) for f, vs in fs.items() if vs}
        out[c]['n_days'] = max(len(vs) for vs in fs.values())
    return out


def xsect_means(rows: list) -> dict:
    """当日截面平均值（保底：该票无历史时用它）。"""
    out: dict = {}
    for f in IMPUTE_FIELDS:
        vs = [v for v in (_num(r.get(f)) for r in rows) if v is not None]
        if vs:
            out[f] = sum(vs) / len(vs)
    out['n_days'] = 0
    return out


def apply_impute(fx: dict, hist: dict, xs: dict) -> dict:
    """把平均值灌进缺口字段，标 impute_src；原 n_bars/src_date 作为事实保留。"""
    src = ''
    if hist:
        for f, v in hist.items():
            if f != 'n_days' and fx.get(f) is None:
                fx[f] = v
        src = 'hist_mean'
        fx['impute_days'] = hist.get('n_days', 0)
    if not src and xs:
        for f, v in xs.items():
            if f != 'n_days' and fx.get(f) is None:
                fx[f] = v
        src = 'xsect_mean'
        fx['impute_days'] = 0
    fx['impute_src'] = src or 'none'
    # 用替代后的比值重算 PE 系列（口径一致：disp / ratio）
    if fx.get('impute_src') != 'none':
        if fx.get('PE1') is None and _num(fx.get('disp')) is not None and _num(fx.get('win_amt_ratio')):
            fx['PE1'] = fx['disp'] / fx['win_amt_ratio']
        if fx.get('PE2') is None and _num(fx.get('disp')) is not None and _num(fx.get('win_vol_ratio')):
            fx['PE2'] = fx['disp'] / fx['win_vol_ratio']
        if fx.get('PE3') is None and _num(fx.get('up_amt')) and _num(fx.get('dn_amt')) is not None:
            fx['PE3'] = fx['dn_amt'] / fx['up_amt']
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


# ---------------------------------------------------------------- consistency
def load_raw_day(day: str, stage: str) -> dict:
    import zstandard as zstd
    p = EI5 / 'raw' / f'{day}_{stage}.jsonl.zst'
    if not p.exists():
        return {}
    out = {}
    for line in zstd.ZstdDecompressor().decompress(p.read_bytes(), max_output_size=1 << 30).decode().splitlines():
        if line.strip():
            o = json.loads(line)
            out[o['code']] = o
    return out


def canon_bars(bars: list) -> str:
    """Canonical JSON of a minute-bar list: [[HHMM, price, cumvol, cumamt], ...]."""
    return json.dumps(bars, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def first_bar_diff(truth: list, live: list) -> str:
    if truth == live:
        return 'identical'
    if len(truth) != len(live):
        return f'n_bars {len(truth)} vs {len(live)}'
    for t, l in zip(truth, live):
        if list(t) != list(l):
            return f'bar@{t[0]} live={list(l)} truth={list(t)}'
    return 'same_len_order_diff'


FX_CMP_FIELDS = ['auction_gap', 'auction_vol_ratio', 'auction_amt_ratio', 'n_bars',
                 'win_vol_ratio', 'win_amt_ratio', 'disp', 'PE1', 'PE2', 'PE3',
                 'retrace_from_peak', 'tail_vol_ratio', 'peak_dn_vol_ratio', 'close_1000']


def _is_null(v) -> bool:
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def fx_close(a: dict, b: dict) -> tuple[bool, str]:
    for f in FX_CMP_FIELDS:
        x, y = a.get(f), b.get(f)
        if _is_null(x) and _is_null(y):
            continue
        try:
            xf, yf = float(x), float(y)
        except (TypeError, ValueError):
            if x != y:
                return False, f'{f}: {x} vs {y}'
            continue
        if not math.isclose(xf, yf, rel_tol=1e-6, abs_tol=1e-9):
            return False, f'{f}: {xf} vs {yf}'
    return True, ''


def stage_consistency(day: str, base: str | None, limit: int, sleep: float) -> dict:
    """盘后真值 vs 当日 10:01 实采：逐票逐点比对，验证实采无半根量/脏数据污染。"""
    import pandas as pd
    t0 = time.time()
    base_day = resolve_base(day, base)
    cohort, meta = load_cohort(base_day)
    if limit:
        cohort = cohort[:limit]

    live = load_raw_day(day, 'window')
    if not live:
        return {'day': day, 'error': f'no live window raw (raw/{day}_window.jsonl.zst)'}

    fx_live: dict = {}
    fx_path = EI5 / 'features' / f'day={day}.parquet'
    if fx_path.exists():
        fx_live = pd.read_parquet(fx_path).set_index('code').to_dict('index')

    codes = [r['code'] for r in cohort]
    q = quotes(codes, sleep=0.4)
    raw_match = raw_mis = fx_match = fx_mis = live_missing = 0
    examples: list = []
    for n, row in enumerate(cohort, 1):
        code = row['code']
        if code not in live:
            live_missing += 1
            continue
        try:
            src_date, allbars = fetch_minute(code)
            if src_date != day.replace('-', ''):
                if len(examples) < 10:
                    examples.append({'code': code, 'err': f'stale_date:{src_date}'})
                continue
            bars = [b for b in allbars if b[0] <= WIN_END]
            lbars = live[code].get('bars') or []
            if canon_bars(bars) == canon_bars(lbars):
                raw_match += 1
            else:
                raw_mis += 1
                if len(examples) < 10:
                    examples.append({'code': code, 'raw_diff': first_bar_diff(bars, lbars)})
            if code in fx_live:
                base20 = tdx_daily(code, day)
                fx = compute_features(day, base_day, row, q.get(code), bars, base20, 'consistency')
                ok, why = fx_close(fx, fx_live[code])
                if ok:
                    fx_match += 1
                else:
                    fx_mis += 1
                    if len(examples) < 10:
                        examples.append({'code': code, 'fx_diff': why})
        except Exception as e:                                # noqa: BLE001
            if len(examples) < 10:
                examples.append({'code': code, 'err': f'{type(e).__name__}:{e}'[:120]})
        if sleep:
            time.sleep(sleep)
        if n % 100 == 0:
            print(f'  ...{n}/{len(cohort)}', file=sys.stderr)

    denom = max(1, len(cohort) - live_missing)
    rate = round(raw_match / denom, 4)
    rep = {'day': day, 'base_day': base_day, 'cohort': len(cohort), 'n_live_raw': len(live),
           'raw_match': raw_match, 'raw_mismatch': raw_mis, 'live_missing': live_missing,
           'raw_match_rate': rate, 'fx_match': fx_match, 'fx_mismatch': fx_mis,
           'verdict': 'PASS' if rate >= 0.99 else 'FAIL', 'examples': examples,
           'elapsed_s': round(time.time() - t0, 1)}
    d = EI5 / 'consistency'
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{day}.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


# ---------------------------------------------------------------- main
def check_time_window(stage: str) -> tuple[bool, str]:
    """live stage 只能在自己的时间窗内写盘，防把收盘后快照当竞价/窗口数据写进去。"""
    win = {'auction': ('0912', '0945'), 'window': ('0955', '1030')}.get(stage)
    if not win:
        return True, ''
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H%M')
    except Exception:                                      # noqa: BLE001
        now = datetime.now().strftime('%H%M')
    return win[0] <= now <= win[1], now


def check_trading_day(day: str) -> tuple[bool, str]:
    """交易日闸门（2026-10-21 起 TDX 口径，退役腾讯 sh000001 时间戳）。

    旧口径依靠腾讯 quote 时间戳 f[30] 的 YYYYMMDD 前缀；TDX servertime 只有 HH:MM:SS.sss 无日期，
    故改用**数据新鲜度**判定：若实时快照与 day 之前最后一根日线 bar 的 (close, amount) 完全相同，
    说明快照是隔夜冻结（非交易日或尚未开盘）；否则当日已有成交 → 是交易日且行情在跑。
    用 sh600519（茅台，竞价必成交）而非指数：实测 Session.daily 对指数解析异常。
    """
    try:
        from r2.tdx_quotes import quotes as _tdx_quotes
        from r2.tdx_client import with_session
        q = (_tdx_quotes(['sh600519'], with_name=False).get('600519') or {})
        bars = with_session(lambda s: s.daily(1, '600519', count=6))
        prior = [b for b in bars if b['date'] < day]
        prev = prior[-1] if prior else bars[-1]
        frozen = (abs(float(q.get('price') or 0.0) - prev['close']) < 1e-6
                  and abs(float(q.get('amount') or 0.0) - prev['amount']) < 1.0)
        detail = (f"tdx:{q.get('ts', '')} px={q.get('price')}/{prev['close']}"
                  f" amt={q.get('amount')}/{prev['amount']} prev_bar={prev['date']}")
        return (not frozen), detail
    except Exception as e:                                 # noqa: BLE001
        return False, f'tdx_err:{type(e).__name__}'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True,
                    choices=['auction', 'window', 'backfill', 'labels', 'consistency'])
    ap.add_argument('--day', required=True, help='target trading day YYYY-MM-DD')
    ap.add_argument('--base', default=None, help='T-1 scan day (default: latest snapshot before --day)')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=0.1)
    ap.add_argument('--no-minute', action='store_true',
                    help='不打分时端点，直接走平均值替代（限流期间的离线补数）')
    ap.add_argument('--skip-live', action='store_true',
                    help='已有真分时行(n_bars>0 且非 imputed)的票直接跳过，不重取')
    ap.add_argument('--ignore-guard', action='store_true', help='skip trading-day gate')
    a = ap.parse_args()

    if a.stage in ('auction', 'window') and not a.ignore_guard:
        okd, ts = check_trading_day(a.day)
        if not okd:
            print(json.dumps({'day': a.day, 'stage': a.stage, 'skipped': 'NOT_TRADING_DAY',
                              'quote_ts': ts}, ensure_ascii=False))
            return
        okt, nowhhmm = check_time_window(a.stage)
        if not okt:
            print(json.dumps({'day': a.day, 'stage': a.stage, 'skipped': 'OUT_OF_TIME_WINDOW',
                              'now': nowhhmm}, ensure_ascii=False))
            print('  提示：live 阶段只在自己时间窗内写盘；要补历史数据用 --stage backfill', file=sys.stderr)
            return

    if a.stage == 'labels':
        print(json.dumps(stage_labels(a.day), ensure_ascii=False)); return
    if a.stage == 'consistency':
        print(json.dumps(stage_consistency(a.day, a.base, a.limit, a.sleep),
                         ensure_ascii=False, indent=1)); return

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
    imp: list = []                       # 分时断源 → 走平均值替代，不留空行
    kept = 0                             # 当日真数据已在盘 → 保留不覆盖
    raw_items: list[tuple[str, dict]] = []
    fx_prev: dict = {}                   # 当日已有行（upsert 前快照，防替代值盖真值）
    fx_path0 = EI5 / 'features' / f'day={a.day}.parquet'
    if fx_path0.exists():
        try:
            import pandas as pd
            fx_prev = pd.read_parquet(fx_path0).set_index('code').to_dict('index')
        except Exception:                                # noqa: BLE001
            fx_prev = {}

    for n, row in enumerate(cohort, 1):
        code = row['code']
        if a.skip_live and a.stage in ('window', 'backfill'):
            pv0 = fx_prev.get(code) or {}
            if _num(pv0.get('n_bars')) and not pv0.get('imputed'):
                kept += 1
                ok += 1
                continue
        try:
            bars, src_date = [], ''
            win_err = ''
            if a.stage in ('window', 'backfill'):
                if a.no_minute:
                    win_err = 'skipped:--no-minute'
                else:
                    try:
                        src_date, allbars = fetch_minute(code)
                        if src_date != a.day.replace('-', ''):
                            raise ValueError(f'stale_date:{src_date}')
                        bars = [b for b in allbars if b[0] <= WIN_END]
                    except Exception as e:                 # noqa: BLE001
                        win_err = f'{type(e).__name__}:{e}'[:120]
                        bars, src_date = [], ''
                    time.sleep(a.sleep)
            base20 = tdx_daily(code, a.day)
            fx = compute_features(a.day, base_day, row, q.get(code), bars, base20, a.stage)
            if win_err:
                pv = fx_prev.get(code) or {}
                if _num(pv.get('n_bars')) and not pv.get('imputed'):
                    kept += 1      # 今日已采到真分时 → 保留，不拿替代值覆盖
                    ok += 1
                    continue
                fx['imputed'] = 1
                fx['impute_err'] = win_err
                imp.append(fx)
                ok += 1
                continue
            payload = {'schema': SCHEMA_RAW, 'code': code, 'day': a.day, 'base_day': base_day,
                       'stage': a.stage, 'source': 'tdx:snapshot+ifzq.minute',
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
            print(f'  ...{n}/{len(codes)} ok={ok} fail={len(fails)} imp={len(imp)} '
                  f'{time.time()-t0:.0f}s', flush=True)

    # 平均值替代：先该票历史均值，无历史用当日截面均值
    if imp:
        hist = load_hist_means(a.day)
        xs = xsect_means(rows_f)
        n_hist = n_xs = n_none = 0
        for fx in imp:
            apply_impute(fx, hist.get(fx['code']) or {}, xs)
            s = fx.get('impute_src')
            n_hist += s == 'hist_mean'
            n_xs += s == 'xsect_mean'
            n_none += s == 'none'
            rows_f.append(fx)
        print(f'[impute] hist_mean={n_hist} xsect_mean={n_xs} none={n_none}', flush=True)

    raw_path, raw_bytes = '', 0
    if raw_items:
        p, hashes = write_raw_day(a.day, a.stage, raw_items)
        raw_path, raw_bytes = str(p.relative_to(ROOT)), p.stat().st_size
        for fx in rows_f:
            if fx.get('imputed'):
                continue
            man.append({'day': a.day, 'code': fx['code'], 'stage': a.stage, 'base_day': base_day,
                        'raw_path': raw_path, 'raw_sha256': hashes.get(fx['code'], ''),
                        'n_bars': fx.get('n_bars'), 'src_date': fx.get('src_date', ''),
                        'source': 'tdx:snapshot+ifzq.minute', 'fetched_at': fx['fetched_at'],
                        'git_sha': git_sha(), 'ok': True})
    for fx in rows_f:                       # 平均值替代行：无 raw，标记来源与原始错误
        if not fx.get('imputed'):
            continue
        man.append({'day': a.day, 'code': fx['code'], 'stage': a.stage, 'base_day': base_day,
                    'raw_path': '', 'raw_sha256': '', 'n_bars': fx.get('n_bars'),
                    'src_date': fx.get('src_date', ''),
                    'source': f'imputed:{fx.get("impute_src")}',
                    'impute_err': fx.get('impute_err', ''), 'impute_days': fx.get('impute_days'),
                    'fetched_at': fx['fetched_at'], 'git_sha': git_sha(), 'ok': True})
    if rows_f:
        upsert_parquet(EI5 / 'features' / f'day={a.day}.parquet', rows_f)
    append_manifest(EI5 / 'manifest.jsonl', man)

    cov = {'day': a.day, 'base_day': base_day, 'stage': a.stage, 'cohort': len(codes),
           'ok': ok, 'fail': len(fails), 'coverage': round(ok / max(len(codes), 1), 4),
           'imputed': len(imp), 'kept_live': kept, 'impute_src': {}, 'fail_reasons': {}, 'raw_file': raw_path,
           'raw_bytes': raw_bytes, 'elapsed_s': round(time.time() - t0, 1),
           'git_sha': git_sha(), 'run_at': now_cst()}
    for f in imp:
        k = f.get('impute_src', 'none')
        cov['impute_src'][k] = cov['impute_src'].get(k, 0) + 1
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