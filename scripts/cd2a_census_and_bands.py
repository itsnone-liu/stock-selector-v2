#!/usr/bin/env python3
"""CD-2A axis census (Support-First) + threshold refit + band table build.
Preregistered: docs/cd/cd2a_preregistration.json (v2, 2026-10-21 user ruling).

TWO MODES (user ruling 2026-10-21: refit fires on the slow-frequency update event, not daily):
  * daily chain step C1A, no flag  = CARRY. Rebuilds the band table for EVERY row using the
    thresholds + stratum map carried in docs/cd/cd2a_thresholds.json. No refit happens.
  * --refit                        = re-derive thresholds from the dev window (2021-01..2023-12).
    Run ONLY when a slow-frequency data update event occurred (e5 weekly / holders on the 1st
    / institutional quarterly / universe refresh). The user updates slow data by hand and then
    calls for the refit, so the cadence is the slow-data cadence, never the daily cadence.
Thresholds are NOT frozen constants and there is no 'freeze once' event. EVERY run (carry or
refit) appends a drift record to docs/cd/cd2a_threshold_history.jsonl with mode=refit|carry,
so a carried-but-drifting basis is never silent. No holdout date ever enters the fit, so every
refit stays PIT-clean."""
import json, gzip, hashlib, time, sys, argparse
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz'
OUT_T = ROOT/'docs'/'cd'/'cd2a_thresholds.json'
OUT_B = ROOT/'data'/'cd'/'sector_axes'/'l2_axis_bands.json.gz'
DEV_END = '2023-12-31'
AXES = ['rp','part','breadth','conc','disp']

def q(sorted_v, p):
    if not sorted_v: return None
    k = (len(sorted_v)-1)*p; f = int(k); c = min(f+1, len(sorted_v)-1)
    return sorted_v[f] + (sorted_v[c]-sorted_v[f])*(k-f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refit', action='store_true',
                    help='re-derive thresholds from the dev window (slow-frequency update event only)')
    ap.add_argument('--trigger', default='', help='free-text reason recorded with the refit')
    args = ap.parse_args()
    rec = json.loads(gzip.decompress(SRC.read_bytes()))
    rows = rec['rows']
    dev = [r for r in rows if r['status']=='OK' and r['date'] <= DEV_END]
    print(f'OK rows total={sum(1 for r in rows if r["status"]=="OK")} dev-window={len(dev)}')
    # ---- mode gate (user ruling 2026-10-21): thresholds are refit ONLY on a slow-frequency
    # data update event; the daily chain CARRYs them and only rebuilds the band table. ----
    prev_doc = None
    if OUT_T.exists():
        try: prev_doc = json.load(open(OUT_T))
        except Exception: prev_doc = None
    carried_thr = (prev_doc or {}).get('thresholds')
    carried_stratum = (prev_doc or {}).get('stratum_map')
    need_refit = bool(args.refit)
    if not need_refit and (not carried_thr or not carried_stratum):
        print('MODE=refit (forced)  no usable carried thresholds/stratum_map in', OUT_T.name)
        need_refit = True
    if not need_refit:
        new_sec = sorted({r['l2'] for r in rows if r['status'] == 'OK'} - set(carried_stratum))
        if new_sec:
            print('MODE=refit (forced)  sector(s) absent from carried stratum_map:', new_sec)
            need_refit = True
    def _canon(r):
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in sorted(r.items())}
    fit_basis_sha = hashlib.sha256(json.dumps([_canon(r) for r in dev], separators=(',', ':'),
                                             sort_keys=True).encode()).hexdigest()
    carried_basis_sha = (prev_doc or {}).get('fit_basis_sha')
    basis_changed = bool(carried_basis_sha) and carried_basis_sha != fit_basis_sha
    # derived variables per row
    def vars_of(r):
        return {'rp': r['rel_eq_mkt'],
                'part': (r['vol_share'] - r['vol_share_20d']) if (r['vol_share'] is not None and r['vol_share_20d'] is not None) else None,
                'breadth': r['advance_frac'],
                'conc': r['ret_contrib_top5'],
                'disp': (r['top5_mean_ret'] - r['rest_mean_ret']) if (r['top5_mean_ret'] is not None and r['rest_mean_ret'] is not None) else None}
    if not need_refit:
        stratum, thr = carried_stratum, carried_thr
        print(f'MODE=carry  thresholds + stratum_map carried from {OUT_T.name} (no refit; '
              f'slow-data cadence policy)')
    else:
        print(f'MODE=refit  trigger={args.trigger or "(unspecified)"}  thresholds re-derived from dev window')
        # size strata by median participating n per sector over dev window
        med_n = {}
        by_sec = defaultdict(list)
        for r in dev: by_sec[r['l2']].append(r['n'])
        for s, ns in by_sec.items():
            ns = sorted(ns); med_n[s] = ns[len(ns)//2]
        stratum = {s: ('SMALL' if m < 15 else 'MID' if m < 50 else 'LARGE') for s, m in med_n.items()}
        from collections import Counter
        print('strata:', Counter(stratum.values()))
        # per-axis pooled + stratum quantiles (dev window)
        thr = {}
        for ax in AXES:
            pooled = sorted(v[ax] for v in (vars_of(r) for r in dev) if v[ax] is not None)
            by_str = defaultdict(list)
            for r in dev:
                v = vars_of(r)[ax]
                if v is not None: by_str[stratum[r['l2']]].append(v)
            t_pooled = (q(pooled, 1/3), q(pooled, 2/3))
            t_str = {k: (q(sorted(v), 1/3), q(sorted(v), 2/3)) for k, v in by_str.items()}
            # drift measure: fraction of stratum rows falling in pooled MID band vs stratum-MID band
            drift = {}
            for k, v in by_str.items():
                def midfrac(rows, thr_):
                    lo, hi = thr_
                    return sum(1 for x in rows if lo <= x < hi)/len(rows)
                drift[k] = round(abs(midfrac(v, t_pooled) - midfrac(v, t_str[k])), 4)
            adopt_stratified = any(d > 0.10 for d in drift.values())
            # annual stability (pooled dev years)
            ann = {}
            for yr in ('2021','2022','2023'):
                sv = sorted(x for r in dev if r['date'].startswith(yr) for x in [vars_of(r)[ax]] if x is not None)
                ann[yr] = [round(q(sv, 1/3), 6), round(q(sv, 2/3), 6)]
            thr[ax] = {'variable': {'rp':'rel_eq_mkt','part':'vol_share - vol_share_20d','breadth':'advance_frac','conc':'ret_contrib_top5','disp':'top5_mean_ret - rest_mean_ret'}[ax],
                       'n_dev_nonnull': len(pooled), 'pooled_q33_q67': [round(t_pooled[0], 8), round(t_pooled[1], 8)],
                       'stratum_q33_q67': {k: [round(a, 8), round(b, 8)] for k, (a, b) in t_str.items()},
                       'stratum_midband_drift_abs': drift, 'annual_pooled_q33_q67': ann,
                       'adopted': 'SIZE_STRATIFIED' if adopt_stratified else 'POOLED'}
            print(ax, thr[ax]['adopted'], 'pooled=', thr[ax]['pooled_q33_q67'], 'drift=', drift)
    if not need_refit and basis_changed:
        print(f'WARN  fit basis DRIFTED vs last refit ({carried_basis_sha[:12]} -> {fit_basis_sha[:12]}): '
              f'thresholds stay carried per policy (refit pending next slow-data update); band drift logged below')
    # build band table over ALL OK rows (carried or freshly fitted thresholds alike)
    def band(ax, val, l2):
        if val is None: return None
        lo, hi = thr[ax]['stratum_q33_q67'][stratum[l2]] if thr[ax]['adopted']=='SIZE_STRATIFIED' else thr[ax]['pooled_q33_q67']
        lab = 'LOW' if val < lo else 'HIGH' if val >= hi else 'MID'
        # ERRATUM-CD2A-1 (2026-10-21, made idempotent): preregistration names the participation
        # axis FALLING/FLAT/EXPANDING. The original fix rewrote the OUTPUT file in place, so every
        # cd2a re-run silently reverted part to LOW/MID/HIGH -> cd2bc dropped all PARTICIPATION_*
        # modifiers and EXPANSION/FADING/BUILDING path labels went to 0.
        if ax == 'part': lab = {'LOW': 'FALLING', 'MID': 'FLAT', 'HIGH': 'EXPANDING'}[lab]
        return lab
    bands = []
    for r in rows:
        if r['status'] != 'OK':
            bands.append({'l2': r['l2'], 'date': r['date'], 'state': 'INSUFFICIENT_SUPPORT', 'n': r.get('n', 0)})
            continue
        v = vars_of(r)
        bands.append({'l2': r['l2'], 'date': r['date'], 'n': r['n'],
            'rp': band('rp', v['rp'], r['l2']), 'part': band('part', v['part'], r['l2']),
            'breadth': band('breadth', v['breadth'], r['l2']), 'conc': band('conc', v['conc'], r['l2']),
            'disp': band('disp', v['disp'], r['l2'])})
    # --- refit audit: capture previous threshold + band table BEFORE overwrite ---
    prev_thr, prev_band_sha, prev_bands = None, None, {}
    if OUT_T.exists():
        try:
            _pd = json.load(open(OUT_T)); prev_thr = _pd.get('thresholds'); prev_band_sha = _pd.get('band_table_sha256')
        except Exception: pass
    if OUT_B.exists():
        try:
            prev_bands = {(b['l2'], b['date']): b for b in json.loads(gzip.decompress(OUT_B.read_bytes()))['bands']}
        except Exception: prev_bands = {}
    sha = hashlib.sha256(json.dumps(bands, separators=(',',':')).encode()).hexdigest()
    OUT_B.write_bytes(gzip.compress(json.dumps({'n': len(bands), 'bands': bands}, separators=(',',':')).encode(), 6))
    # refit_at / refit_trigger / fit_basis_sha only move on a REFIT. A carried run stamps
    # carried_at and re-asserts thresholds + stratum map byte-for-byte: no silent threshold rewrite.
    _p = prev_doc or {}
    _now = time.strftime('%Y-%m-%dT%H:%M:%S')
    json.dump({'refit_at': _now if need_refit else _p.get('refit_at'),
               'refit_trigger': (args.trigger or '') if need_refit else _p.get('refit_trigger', ''),
               'carried_at': None if need_refit else _now,
               'carry_count': 0 if need_refit else int(_p.get('carry_count') or 0) + 1,
               'refit_cadence': 'slow-frequency data update event (manual, user-triggered)',
               'fit_basis_sha': fit_basis_sha if need_refit else _p.get('fit_basis_sha'),
               'fit_basis_sha_now': fit_basis_sha,
               'fit_basis_changed_since_refit': bool(basis_changed and not need_refit),
               'dev_window_end': DEV_END, 'thresholds': thr, 'stratum_map': stratum,
               'band_table_sha256': sha, 'n_rows': len(bands),
               'null_counts': {ax: sum(1 for b in bands if b.get(ax) is None) for ax in AXES}},
              open(OUT_T, 'w'), indent=1)
    # --- drift log: no freeze, but never silent (user ruling 2026-10-21) ---
    def _flat(d, pre=''):
        out = {}
        if isinstance(d, dict):
            for k, v in d.items(): out.update(_flat(v, f'{pre}{k}.'))
        elif isinstance(d, (int, float)) and not isinstance(d, bool):
            out[pre.rstrip('.')] = float(d)
        return out
    flips = {ax: 0 for ax in AXES}; changed = 0; cmp_rows = 0
    for b in bands:
        p = prev_bands.get((b['l2'], b['date']))
        if p is None: continue
        cmp_rows += 1; row_diff = False
        for ax in AXES:
            if p.get(ax) != b.get(ax): flips[ax] += 1; row_diff = True
        if row_diff: changed += 1
    ft, pt = _flat(thr), _flat(prev_thr or {})
    deltas = {k: abs(ft[k]-pt[k]) for k in ft if k in pt}
    rec = {'at': _now, 'mode': 'refit' if need_refit else 'carry',
           'refit': bool(need_refit), 'trigger': args.trigger or '',
           'fit_basis_sha': fit_basis_sha,
           'fit_basis_changed_since_refit': bool(basis_changed and not need_refit),
           'band_table_sha256': sha,
           'prev_band_table_sha256': prev_band_sha, 'n_rows': len(bands),
           'compared_rows': cmp_rows, 'changed_rows': changed, 'flips_by_axis': flips,
           'max_threshold_delta': max(deltas.values()) if deltas else None,
           'threshold_deltas': {k: v for k, v in sorted(deltas.items(), key=lambda kv: -kv[1])[:12] if v},
           'band_sha_changed': (prev_band_sha != sha) if prev_band_sha else None}
    with open(ROOT/'docs'/'cd'/'cd2a_threshold_history.jsonl', 'a') as _fh:
        _fh.write(json.dumps(rec, separators=(',', ':'), sort_keys=True) + '\n')
    print(f"audit[mode={rec['mode']}]: band_sha", 'CHANGED' if rec['band_sha_changed'] else 'identical',
          '| changed_rows=', changed, '/', cmp_rows, '| max_thr_delta=', rec['max_threshold_delta'])
    print('band table rows=', len(bands), 'sha=', sha[:16])
    # dual-run determinism: recompute bands purely to compare
    bands2 = []
    for r in rows:
        if r['status'] != 'OK':
            bands2.append({'l2': r['l2'], 'date': r['date'], 'state': 'INSUFFICIENT_SUPPORT', 'n': r.get('n', 0)}); continue
        v = vars_of(r)
        bands2.append({'l2': r['l2'], 'date': r['date'], 'n': r['n'],
            'rp': band('rp', v['rp'], r['l2']), 'part': band('part', v['part'], r['l2']),
            'breadth': band('breadth', v['breadth'], r['l2']), 'conc': band('conc', v['conc'], r['l2']),
            'disp': band('disp', v['disp'], r['l2'])})
    sha2 = hashlib.sha256(json.dumps(bands2, separators=(',',':')).encode()).hexdigest()
    print('determinism recompute:', 'PASS' if sha2==sha else 'FAIL')

if __name__ == '__main__':
    main()
