#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase A — sample selection engine (replay manifest generator).

Implements the FROZEN CSR-7 case_selection contract verbatim:
  5 groups x 20 cases, formula rules, per-stock uniqueness, multi-group
  membership allowed + registered, stratified redraw (<=1), seed=20260925.

Inputs (all existing local assets, no new channels):
  data/adjustment_baostock/per_stock/*.json.gz  (hfq close / unadj turn,pctChg)
  output/research/t6/01_eclass/t6_1_per_event.parquet  (T3 frozen breakout events)
  data/t4/sector_map/csrc_industry_snapshot.json        (industry map, snapshot caveat)

Output: output/research/csr/08_pilot_cases/phase_a/
  panel_meta.json          — universe/dates/counts audit trail
  g1_episodes.csv ... g5_episodes.csv — full candidate episode tables (replayable)
  sample_selection.json    — final 5x20 + substitutes + excluded + membership
  replay_manifest.json     — params, per-step filter counts, thresholds, code sha
"""
import gzip, json, hashlib, sys, time
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/research/csr/08_pilot_cases/phase_a'
OUT.mkdir(parents=True, exist_ok=True)
SEED = 20260925
N_PER_GROUP = 20
G1_WIN_MIN, G1_WIN_MAX = 375, 1250   # 18/60-month trading-day approx (erratum G1-E2)

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

# frozen-universe exact-set gate (erratum UNI-E1)
_uni = json.load(open(ROOT/'config/universe_frozen.json'))
_per = {f.name[:-len('.json.gz')] for f in (ROOT/'data/adjustment_baostock/per_stock').glob('*.json.gz')}
assert set(_uni['codes']) == _per, 'per_stock set != universe_frozen set'
UNIVERSE_SHA = sha256_file(ROOT/'config/universe_frozen.json')
EVENTS_SHA = sha256_file(ROOT/'output/research/t6/01_eclass/t6_1_per_event.parquet')
SNAP_SHA = sha256_file(ROOT/'data/t4/sector_map/csrc_industry_snapshot.json')
_h = hashlib.sha256()
for f in sorted((ROOT/'data/adjustment_baostock/per_stock').glob('*.json.gz')):
    _h.update(f.name[:-len('.json.gz')].encode()); _h.update(hashlib.sha256(f.read_bytes()).hexdigest().encode())
PERSTOCK_AGG_SHA = _h.hexdigest()
PROTO_SHA = sha256_file(ROOT/'output/research/csr/07_case_protocol/CSR_7_CASE_PROTOCOL.yaml')
ERRATA_SHA = sha256_file(ROOT/'output/research/csr/07_case_protocol/CSR_7_IMPLEMENTATION_ERRATUM.md')

t0 = time.time()
def log(msg):
    print(f'[{time.time()-t0:7.1f}s] {msg}', flush=True)

# ---------------- panel ----------------
def build_panel():
    per = ROOT / 'data/adjustment_baostock/per_stock'
    files = sorted(per.glob('*.json.gz'))
    closes, turns, names = {}, {}, []
    for f in files:
        with gzip.open(f, 'rt') as fh:
            d = json.load(fh)
        code = d['code']
        hfq = d['hfq']; unadj = d['unadj']
        # hfq rows: [date,o,h,l,c,v,amount,turn,pct] — verify shape via unadj fields
        closes[code] = {r[0]: float(r[4]) for r in hfq}
        turns[code] = {r[0]: float(r[7]) for r in unadj if r[7] not in (None, '')}
        names.append(code)
    all_dates = sorted({dt for c in closes.values() for dt in c})
    idx = {dt: i for i, dt in enumerate(all_dates)}
    n, m = len(all_dates), len(names)
    log(f'universe {m} stocks x {n} days ({all_dates[0]}..{all_dates[-1]})')
    C = np.full((n, m), np.nan, dtype=np.float32)
    T = np.full((n, m), np.nan, dtype=np.float32)
    for j, code in enumerate(names):
        cc = closes[code]
        for dt, v in cc.items():
            C[idx[dt], j] = v
        tt = turns[code]
        for dt, v in tt.items():
            T[idx[dt], j] = v
    return all_dates, idx, names, C, T

DATES, DIDX, NAMES, CLOSE, TURN = build_panel()
log('panel built (hfq close + turn)')
json.dump({'n_days': len(DATES), 'first': DATES[0], 'last': DATES[-1],
           'n_stocks': len(NAMES)}, open(OUT/'panel_meta.json','w'), ensure_ascii=False)

def count_recoveries(w, thrdd):
    peak = w[0]; dd_start_peak = None; recoveries = 0; unresolved = False
    for px in w[1:]:
        if dd_start_peak is None:
            if px > peak: peak = px
            elif px < peak * (1.0 - thrdd):
                dd_start_peak = peak; unresolved = True
        else:
            if px >= dd_start_peak:
                recoveries += 1; dd_start_peak = None; unresolved = False
                peak = max(peak, px)
    return recoveries, unresolved

def save(name, rows, cols):
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv(OUT/name, index=False)
    log(f'{name}: {len(df)} rows')
    return df

def year_of(i):
    return int(DATES[i][:4])

# ================= G1 complete bull =================
def g1():
    log('G1 scanning...')
    n = len(DATES)
    episodes = []
    for j, code in enumerate(NAMES):
        c = CLOSE[:, j]
        valid = np.where(np.isfinite(c))[0]
        if len(valid) < 375 + 126:   # 6 months listing + >=18M window
            continue
        first = valid[0]
        if first + 126 > n:
            continue
        # monthly starts across the stock's life
        starts = [i for i in range(first + 126, n - G1_WIN_MIN) if i == first + 126 or
                  (i > 0 and DATES[i][5:7] != DATES[i-1][5:7])]
        best_gain, best_win = -1.0, None
        for i in starts:
            seg = c[i:]
            if not np.isfinite(seg).any():
                continue
            runmin = np.minimum.accumulate(seg)
            g = seg / runmin                     # g[k] = best gain from window start to k
            j_hi = min(len(seg), G1_WIN_MAX + 1)
            g_win = g[:j_hi]
            if len(g_win) <= G1_WIN_MIN - 1:      # enforce >=18M length
                continue
            gg = np.where(np.isfinite(g_win), g_win, -np.inf)
            k = int(np.nanargmax(np.where(np.arange(len(g_win)) >= G1_WIN_MIN - 1, gg, -np.inf)))
            gain = float(g_win[k]) - 1.0
            if gain > best_gain + 1e-12:
                best_gain, best_win = gain, (i, i + k)
        if best_win is not None and best_gain > 0:
            w = c[best_win[0]:best_win[1]+1]
            w = w[np.isfinite(w)]
            rec20, unres = count_recoveries(w, 0.20)
            # sensitivity (registered, not selection): 15%/25% on same window
            widx = best_win
            ep = {'code': code, 'w_start': DATES[widx[0]], 'w_end': DATES[widx[1]],
                  'max_gain': best_gain, 'recoveries': rec20,
                  'unresolved_dd': bool(unres), 'rec15': count_recoveries(w, 0.15)[0],
                  'rec25': count_recoveries(w, 0.25)[0]}
            episodes.append(ep)
    df = pd.DataFrame(episodes)
    df3 = df[df['recoveries'] <= 3]
    thr = float(np.quantile(df3['max_gain'].values, 0.995))
    cand = df3[df3['max_gain'] >= thr].copy()
    # threshold sensitivity (audit transparency; NOT selection criteria)
    sens = {}
    for lbl, col in (('15%', 'rec15'), ('20%', 'recoveries'), ('25%', 'rec25')):
        ddx = df[df[col] <= 3]
        t2 = float(np.quantile(ddx['max_gain'].values, 0.995))
        sens[lbl] = {'n_episodes': int(len(ddx)), 'thr995': t2,
                     'n_candidates': int((ddx['max_gain'] >= t2).sum())}
    log(f'G1 episodes={len(df)} after-recovery<=3={len(df3)} thr(99.5%)={thr:.3f} '
        f'candidates={len(cand)} sens={sens}')
    df.to_csv(OUT/'g1_episodes.csv', index=False)
    return cand, thr, sens

# ================= G2 breakout fail (T3 frozen events) =================
def g2():
    log('G2 scanning (T3 frozen events)...')
    ev = pd.read_parquet(ROOT/'output/research/t6/01_eclass/t6_1_per_event.parquet',
                         columns=['event_id', 'stock_code', 'T0_date'])
    ev = ev.drop_duplicates('event_id')
    rows = []
    def full(code6):
        return ('sh.' if code6.startswith('6') else 'sz.') + code6
    ev = ev.assign(stock_code=ev['stock_code'].map(full))   # canonicalize at ingest
    code2col = {c: j for j, c in enumerate(NAMES)}
    for _, r in ev.iterrows():
        j = code2col.get(r['stock_code'])
        if j is None:
            continue
        t0s = r['T0_date']
        if t0s not in DIDX:
            continue
        i = DIDX[t0s]
        c = CLOSE[:, j]
        fwd = c[i:i+121]
        fwd = fwd[np.isfinite(fwd)]
        if len(fwd) < 121:      # right-censored: need full 120d path
            continue
        back = c[max(0, i-20):i+1]
        back = back[np.isfinite(back)]
        if len(back) < 10:
            continue
        t0_close, prior_high = float(fwd[0]), float(np.nanmax(back))
        if not (np.nanmin(fwd) < t0_close):          # must fall back below breakout level
            continue
        if np.nanmax(fwd[1:]) > prior_high:          # must NOT make a new high
            continue
        severity = (t0_close - float(np.nanmin(fwd))) / t0_close
        rows.append({'code': r['stock_code'], 'T0': t0s, 'severity': severity,
                     'event_id': r['event_id']})
    df = pd.DataFrame(rows)
    if df.empty:
        log('G2: no failing events found'); return df, None
    df = df.sort_values(['code', 'severity', 'T0'], ascending=[True, False, True])
    uniq = df.groupby('code', as_index=False).first()   # severity max, tie earliest
    log(f'G2 fail-events={len(df)} unique-stock episodes={len(uniq)}')
    df.to_csv(OUT/'g2_episodes.csv', index=False)
    uniq.to_csv(OUT/'g2_uniq.csv', index=False)
    return uniq, None

# ================= G3 high collapse =================
def g3():
    log('G3 scanning...')
    n, m = len(DATES), len(NAMES)
    C = CLOSE
    R = np.full_like(C, np.nan)
    R[252:] = C[252:] / C[:-252] - 1.0
    RP = pd.DataFrame(R).rank(axis=1, pct=True).values   # cross-sectional pct
    rows = []
    for j in range(m):
        rp = RP[:, j]
        cand = np.where(np.isfinite(rp) & (rp >= 0.90))[0]
        if len(cand) == 0:
            continue
        c = C[:, j]
        best_dd, best_i = -1.0, None
        for t in cand:
            if t + 180 >= n:            # right-censored: need full 180d fwd
                continue
            fwd = c[t:t+181]
            if not np.isfinite(fwd).all():
                continue
            if float(fwd[0]) < float(np.nanmax(fwd)):   # anchor must be the fwd peak
                continue
            dd = (float(fwd[0]) - float(np.nanmin(fwd))) / float(fwd[0])
            if dd >= 0.60 and dd > best_dd + 1e-12:
                best_dd, best_i = dd, t
        if best_i is not None:
            rows.append({'code': NAMES[j], 'anchor': DATES[best_i],
                         'dd': best_dd, 'w_start': DATES[max(0, best_i-252)],
                         'w_end': DATES[best_i+180]})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(['code', 'dd', 'anchor'], ascending=[True, False, True])
        uniq = df.groupby('code', as_index=False).first()
    else:
        uniq = df
    log(f'G3 anchors={len(df)} unique-stock episodes={len(uniq)}')
    df.to_csv(OUT/'g3_episodes.csv', index=False)
    return uniq

# ================= G4 quiet then go =================
def g4():
    log('G4 scanning...')
    n, m = len(DATES), len(NAMES)
    C = CLOSE
    ret = np.full_like(C, np.nan)
    ret[1:] = C[1:] / C[:-1] - 1.0
    dfr = pd.DataFrame(ret)
    vol = (dfr.rolling(60, min_periods=40).std() * np.sqrt(252)).values
    t60 = pd.DataFrame(TURN).rolling(60, min_periods=40).mean().values
    volp = pd.DataFrame(vol).rank(axis=1, pct=True).values
    trnp = pd.DataFrame(t60).rank(axis=1, pct=True).values
    B = (volp <= 0.20) & (trnp <= 0.30)
    ret20 = np.full_like(C, np.nan)
    ret20[20:] = C[20:] / C[:-20] - 1.0
    r20p = pd.DataFrame(ret20).rank(axis=1, pct=True).values
    rows = []
    for j in range(m):
        b = B[:, j]
        if b.sum() < 504:
            continue
        # find True-runs >= 504
        d = np.diff(np.concatenate(([0], b.view(np.int8), [0])))
        starts = np.where(d == 1)[0]; ends = np.where(d == -1)[0] - 1
        c = C[:, j]
        best_12m, best_seg = -np.inf, None
        for s, e in zip(starts, ends):
            if e - s + 1 < 504:
                continue
            w = range(e + 1, min(e + 1 + 252, n - 252))    # launch search + need +252
            launch = None
            for t in w:
                if np.isfinite(r20p[t, j]) and r20p[t, j] >= 0.85:
                    launch = t; break
            if launch is None:
                continue
            if launch + 252 >= n or not np.isfinite(c[launch]) or not np.isfinite(c[launch+252]):
                continue                                  # right-censored episode
            g12 = float(c[launch+252] / c[launch] - 1.0)
            if g12 > best_12m + 1e-12:
                best_12m, best_seg = g12, (s, launch)
        if best_seg is not None:
            rows.append({'code': NAMES[j], 'seg_start': DATES[best_seg[0]],
                         'launch': DATES[best_seg[1]], 'gain_12m': best_12m,
                         'w_start': DATES[best_seg[0]], 'w_end': DATES[best_seg[1]+252]})
    df = pd.DataFrame(rows)
    log(f'G4 episodes={len(df)}')
    df.to_csv(OUT/'g4_episodes.csv', index=False)
    return df

# ================= G5 sector follower =================
def g5():
    log('G5 scanning...')
    snap = json.load(open(ROOT/'data/t4/sector_map/csrc_industry_snapshot.json'))
    ind2code = {}
    col = {c: j for j, c in enumerate(NAMES)}
    for r in snap:
        if r[3]:
            j = col.get(r[1])
            if j is not None:
                ind2code.setdefault(r[3], []).append(j)
    n = len(DATES)
    C = CLOSE
    ret = np.full_like(C, np.nan)
    ret[1:] = C[1:] / C[:-1] - 1.0     # equal-weight daily return from hfq closes
    rows = []
    industry_eps = []
    for ind, js in sorted(ind2code.items()):
        if len(js) < 5:                # industry needs >=5 members
            continue
        r_ind = np.nanmean(ret[:, js], axis=1)
        ok = np.isfinite(r_ind)
        if ok.sum() < 300:
            continue
        lvl = np.full(n, np.nan)
        k = np.where(ok)[0]
        lvl[k] = np.cumprod(1.0 + r_ind[k])
        r120 = np.full(n, np.nan)
        for t in k:
            if t >= 120 and np.isfinite(lvl[t]) and np.isfinite(lvl[t-120]):
                r120[t] = lvl[t] / lvl[t-120] - 1.0
        rr = r120[np.isfinite(r120)]
        if len(rr) < 100:
            continue
        thr = float(np.quantile(rr, 0.95))
        qual = np.where(np.isfinite(r120) & (r120 >= thr))[0]
        if len(qual) == 0:
            continue
        # merge consecutive qualifying days into segments
        segs = []
        s = qual[0]; prev = qual[0]
        for t in qual[1:]:
            if t == prev + 1:
                prev = t
            else:
                segs.append((s, prev)); s = t; prev = t
        segs.append((s, prev))
        best = max(segs, key=lambda sg: (float(np.nanmax(r120[sg[0]:sg[1]+1])), -sg[0]))
        peak = float(np.nanmax(r120[best[0]:best[1]+1]))
        industry_eps.append({'industry': ind, 'seg_start': DATES[best[0]],
                             'seg_end': DATES[best[1]], 'peak_r120': peak})
        # member stocks with in-segment gain percentile 40..60
        a, b = best[0], best[1]
        gains = []
        for j in js:
            ca, cb = C[a, j], C[b, j]
            if np.isfinite(ca) and np.isfinite(cb) and ca > 0:
                gains.append((j, float(cb / ca - 1.0)))
        if len(gains) < 10:
            continue
        gs = sorted(g for _, g in gains)
        for j, g in gains:
            pos = np.searchsorted(gs, g) / len(gs)
            if 0.40 <= pos <= 0.60:
                rows.append({'code': NAMES[j], 'industry': ind,
                             'seg_gain': g, 'pos_in_ind': pos,
                             'w_start': DATES[a], 'w_end': DATES[b]})
    df = pd.DataFrame(rows)
    if not df.empty:
        # uniqueness: per stock, industry strength (peak_r120) highest, tie earliest seg
        im = {e['industry']: e['peak_r120'] for e in industry_eps}
        df['ind_str'] = df['industry'].map(im)
        df = df.sort_values(['code', 'ind_str', 'w_start'], ascending=[True, False, True])
        uniq = df.groupby('code', as_index=False).first()
    else:
        uniq = df
    pd.DataFrame(industry_eps).to_csv(OUT/'g5_industry_episodes.csv', index=False)
    log(f'G5 member-candidates={len(df)} unique-stock episodes={len(uniq)}')
    df.to_csv(OUT/'g5_episodes.csv', index=False)
    return uniq

G1C, G1THR, G1SENS = g1()
G2C, _ = g2()
G3C = g3()
G4C = g4()
G5C = g5()

# ================= sampling + stratified redraw + manifest =================
class RngFlow:
    """single seeded rng stream reused across groups in fixed order (replayable)."""
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
    def perm(self, n):
        return self.rng.permutation(n)

FLOW = RngFlow(SEED)

def stratified_redraw_random(cands, metric_col, year_fn, flow):
    """erratum SAM-E1: seeded stratified RANDOM (not metric top-N).
    year buckets -> seeded shuffle within bucket -> first quota each;
    remainder名额 = global metric-desc (skip chosen), no bucket cap;
    at most 1 redraw."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in cands:
        buckets[year_fn(r)].append(r)
    nb = max(len(buckets), 1)
    quota = N_PER_GROUP // nb
    chosen = []
    for y in sorted(buckets):
        lst = list(buckets[y])
        idx = flow.perm(len(lst))
        shuffled = [lst[i] for i in idx]
        chosen.extend(shuffled[:quota])
    remainder = N_PER_GROUP - len(chosen)
    if remainder > 0:
        rest = sorted(cands, key=lambda r: -float(r[metric_col]))
        for r in rest:
            if remainder <= 0:
                break
            if r not in chosen:
                chosen.append(r); remainder -= 1
    return chosen[:N_PER_GROUP]

GROUPS = {}
def pick(name, cand_df, metric_col, year_col):
    recs = cand_df.to_dict('records')
    assert all(str(r['code']).startswith(('sh.', 'sz.')) for r in recs), f'{name}: non-canonical code'
    idx = FLOW.perm(len(recs))
    order = [recs[i] for i in idx]
    chosen = order[:N_PER_GROUP]
    years = Counter(str(r[year_col])[:4] for r in chosen)
    redrawn = False
    if years and max(years.values()) / N_PER_GROUP > 0.5 and len(recs) > N_PER_GROUP:
        chosen = stratified_redraw_random(recs, metric_col,
                                          lambda r: str(r[year_col])[:4], FLOW)
        redrawn = True
    # erratum SAM-E2: conservation — substitutes/excluded derived AFTER final chosen
    chosen_ids = {id(r) for r in chosen}
    rest = [r for r in order if id(r) not in chosen_ids]
    subs, excl = rest[:N_PER_GROUP], rest[N_PER_GROUP:]
    chk = set(map(id, chosen)) | set(map(id, subs)) | set(map(id, excl))
    assert len(chk) == len(recs) and not (set(map(id, chosen)) & set(map(id, subs)))         and not (set(map(id, chosen)) & set(map(id, excl))) and not (set(map(id, subs)) & set(map(id, excl))),         f'{name}: conservation violation'
    GROUPS[name] = {'chosen': chosen, 'substitutes': subs, 'excluded': excl,
                    'n_candidates': len(recs), 'redrawn': redrawn,
                    'year_dist': dict(Counter(str(r[year_col])[:4] for r in chosen))}
    log(f'{name}: cand={len(recs)} chosen={len(chosen)} subs={len(subs)} excl={len(excl)} '
        f'redrawn={redrawn} years={GROUPS[name]["year_dist"]}')

pick('G1_complete_bull', G1C, 'max_gain', 'w_start')
pick('G2_breakout_fail', G2C, 'severity', 'T0')
pick('G3_high_collapse', G3C, 'dd', 'anchor')
pick('G4_quiet_then_go', G4C, 'gain_12m', 'launch')
pick('G5_sector_follower', G5C, 'seg_gain', 'w_start')

# multi-group membership register (canonical codes; erratum CODE-E1 + conservation gate)
mem = defaultdict(list)
for g, d in GROUPS.items():
    for r in d['chosen']:
        mem[r['code']].append(g)
multi = {c: sorted(g) for c, g in mem.items() if len(g) > 1}
# gate: reverse lookup consistency
for c, gs in multi.items():
    for g in gs:
        assert any(r['code'] == c for r in GROUPS[g]['chosen']), f'membership gate fail {c}/{g}'
log(f'multi-group memberships: {len(multi)} -> {multi}')

sample = {
    'seed': SEED, 'n_per_group': N_PER_GROUP, 'rng_flow': 'single default_rng(20260925) stream, groups processed in G1..G5 order',
    'groups': {g: {'chosen': [{k: str(v) for k, v in r.items()} for r in d['chosen']],
                   'substitutes': [{k: str(v) for k, v in r.items()} for r in d['substitutes']],
                   'n_substitutes': len(d['substitutes']),
                   'n_excluded': len(d['excluded']),
                   'excluded_codes_only': [r['code'] for r in d['excluded']],
                   'n_candidates': d['n_candidates'], 'redrawn': d['redrawn'],
                   'year_dist': d['year_dist']} for g, d in GROUPS.items()},
    'multi_group_membership': multi,
    'conservation_note': 'chosen ∪ substitutes ∪ excluded == candidates, pairwise disjoint (script gate)',
}
json.dump(sample, open(OUT/'sample_selection.json', 'w'), ensure_ascii=False, indent=1)

code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def out_sha(name):
    return sha256_file(OUT/name)

manifest = {
    'stage': 'csr_8_phase_a_sample_selection',
    'protocol': 'CSR-7 FROZEN @ 8f4b1f2 + IMPLEMENTATION_ERRATUM (this rerun)',
    'seed': SEED, 'n_per_group': N_PER_GROUP,
    'g1_start_grid': 'calendar_month_first_trading_day',
    'g1_window_min_days': G1_WIN_MIN, 'g1_window_max_days': G1_WIN_MAX,
    'g1_recovery_definition': 'erratum G1-E1: 20% drawdown from running peak; '
                              'recovery=close returns to dd-start peak; <=3; '
                              'sensitivity 15/20/25 registered (main=20%)',
    'g1_threshold_995': G1THR,
    'g1_threshold_sensitivity': G1SENS,
    'g4_authoritative_rule': 'erratum G4-E1: anchor_generation detailed rule; '
                             'group-rule phrase is shorthand; gain_12m only for uniqueness',
    'universe': {'authoritative': 'config/universe_frozen.json',
                 'count': _uni['count'],
                 'erratum': 'CSR-7 text said 5,241; frozen source says 5,240 (UNI-E1)',
                 'exact_set_gate': 'assert set equality passed'},
    'data_window': {'first': DATES[0], 'last': DATES[-1], 'n_days': len(DATES),
                    'n_stocks': len(NAMES),
                    'caveat': '研究窗 2021 起（本地资产边界）；G1 窗口 18-60 月可行；'
                              'G3/G4 右删失排除如实登记；G2 事件表覆盖 2024-01..2026-09；'
                              'G5 provisional（现时行业快照，G5-E1：Phase B PIT 行业表落地后 '
                              'revalidation+同规则整体重放）'},
    'sampling': {'algorithm': 'single seeded rng flow; random 20; if single-year>50% then '
                              'seeded stratified RANDOM redraw (bucket shuffle, not metric top-N); '
                              'remainder by global metric desc; <=1 redraw (erratum SAM-E1)',
                 'conservation': 'chosen/substitutes/excluded pairwise disjoint, union=candidates '
                                 '(script gate, erratum SAM-E2)'},
    'rules_implemented': [
        'G1 calendar-month-start rolling window best-gain per stock (375..1250d); '
        'recovery<=3 (20% machine); pool 99.5% quantile threshold on filtered set',
        'G2 T3 frozen events (canonicalized at ingest); <breakout close & no new high vs '
        'prior 20d; severity=max dd; per-stock severity max tie earliest',
        'G3 ret252 cross-sec pct>=90; anchor=fwd 180d peak; dd>=60%; per-stock dd max tie earliest',
        'G4 vol60 ann. pct<=20 & turn60 pct<=30 run>=504d; launch=first ret20 pct>=85 within '
        '252d; episode needs launch+252; uniqueness by gain_12m desc (G4-E1)',
        'G5 industry equal-weight (hfq-derived, snapshot caveat, provisional G5-E1); r120 >= '
        'own-history 95pct (sampling rule, not realtime); consecutive merge; member 40-60 pct; '
        'ind strength tie earliest'],
    'per_group_counts': {g: {'candidates': d['n_candidates'], 'chosen': len(d['chosen']),
                             'substitutes': len(d['substitutes']),
                             'excluded': len(d['excluded']),
                             'redrawn': d['redrawn']} for g, d in GROUPS.items()},
    'multi_group_count': len(multi),
    'multi_group_detail': multi,
    'input_hashes': {
        'universe_frozen.json': UNIVERSE_SHA,
        't6_1_per_event.parquet': EVENTS_SHA,
        'csrc_industry_snapshot.json': SNAP_SHA,
        'per_stock_aggregate': PERSTOCK_AGG_SHA,
        'csr8_sample.py': code_sha,
        'CSR_7_CASE_PROTOCOL.yaml': PROTO_SHA,
        'CSR_7_IMPLEMENTATION_ERRATUM.md': ERRATA_SHA,
    },
    'output_hashes': {n: out_sha(n) for n in
                      ['g1_episodes.csv', 'g2_episodes.csv', 'g2_uniq.csv', 'g3_episodes.csv',
                       'g4_episodes.csv', 'g5_episodes.csv', 'g5_industry_episodes.csv',
                       'sample_selection.json']},
    'versions': {'numpy': np.__version__, 'pandas': pd.__version__},
}
json.dump(manifest, open(OUT/'replay_manifest.json', 'w'), ensure_ascii=False, indent=1)
log(f'MANIFEST + SAMPLE written to {OUT}')
log(f'phase A complete: 5 groups, membership multi={len(multi)}')
