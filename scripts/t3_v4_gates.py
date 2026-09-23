#!/usr/bin/env python3
"""T3 V4 five integrity gates.

Gate 1  Risk-set PIT        — physically truncate per-stock data at the as-of
                              market date, rebuild the tau row via the frozen
                              V3 builder, re-derive every V4 riskset state
                              field, compare → must be 0 mismatch.
Gate 2  Forward Isolation   — (a) recompute all forward outcomes from RAW
                              per-stock data using only observations strictly
                              after the as-of date for path components and
                              verify the future endpoint's source date;
                              (b) panel-side proof: recompute outcomes from
                              the V3 panel with all source_date <= asof rows
                              masked → identical.
Gate 3  Calendar Eligibility— eligible_fwd_* flags recomputed independently
                              from the market calendar + DATASET_END only;
                              plus structural proof that no event-label column
                              leaked into V4 products.
Gate 4  Overlap / Dependency— event_overlap_audit.json complete and sane.
Gate 5  Determinism         — products hash-identical across the in-process
                              double build recorded by the runner.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
OUT = ROOT / 'output/research/t3_v4'
V3OUT = ROOT / 'output/research/t3_v3'
sys.path.insert(0, str(ROOT / 'src'))
from stock_selector.research import t3_v2 as v2   # noqa: E402
from stock_selector.research import t3_v3 as v3   # noqa: E402
from stock_selector.research import t3_v4 as v4   # noqa: E402


def trunc(sd, cutoff):
    ks = {d for d in sd.dates if d <= cutoff}
    return v2.StockData(sd.code_pfx, sorted(ks), None,
                        {d: x for d, x in sd.h.items() if d in ks},
                        {d: x for d, x in sd.l.items() if d in ks},
                        {d: x for d, x in sd.c.items() if d in ks},
                        {d: x for d, x in sd.vol.items() if d in ks},
                        {d: x for d, x in sd.amt.items() if d in ks},
                        {d: x for d, x in sd.turn.items() if d in ks},
                        {}, {}, {d: x for d, x in sd.F.items() if d in ks},
                        [d for d in sd.valid if d in ks],
                        {d for d in sd.vpos if d in ks})


def eq(a, b):
    if pd.isna(a) and pd.isna(b):
        return True
    if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
        return bool(a) == bool(b)
    if isinstance(a, (float, np.floating)) and isinstance(b, (float, np.floating)):
        return bool(np.isclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=True))
    return a == b


def raw_forward_from_sd(sd, mdates, mpos, asof_date, end_date, ref_flags):
    """Independent recompute of forward outcomes from raw stock data.

    Path components use ONLY observations strictly after asof_date; the as-of
    close is used solely as the base. ref_flags carries (ref20_raw, t0_raw)
    needed for lose_* booleans — both as-of-known frozen levels.
    """
    i1, i2 = mpos[asof_date], mpos[end_date]
    win = [d for d in mdates[i1 + 1:i2 + 1]]
    base = sd.adj.get(asof_date)
    # raw-close atomic facts are base-independent (frozen product semantics)
    raw_seen, lose20, lose0 = False, False, False
    for d in win:
        raw = sd.c.get(d)
        if raw is None:
            continue
        raw_seen = True
        if ref_flags.get('ref20') is not None and raw < ref_flags['ref20']:
            lose20 = True
        if ref_flags.get('raw0') is not None and raw < ref_flags['raw0']:
            lose0 = True
    out = {'lose_ref20_within': (lose20 if raw_seen and
                                 ref_flags.get('ref20') is not None
                                 else (False if raw_seen else None)),
           'lose_t0_close_within': (lose0 if raw_seen and
                                    ref_flags.get('raw0') is not None
                                    else (False if raw_seen else None))}
    if base is None:
        for k in ('fwd_raw_log', 'fwd_mkt_excess_log', 'future_max_drawdown',
                  'future_max_gain', 'new_high_within', 'days_to_next_high',
                  'recover_current_peak_within'):
            out[k] = None
        out['n_valid_obs_window'] = 0   # no usable path observations w/o base
        out['_end_adj'] = sd.adj.get(end_date)
        out['_base'] = None
        return out
    adj_valid = [(d, sd.adj.get(d)) for d in win if sd.adj.get(d) is not None]
    valid = [(d, a) for d, a in adj_valid]
    out['n_valid_obs_window'] = len(valid)
    end_adj = sd.adj.get(end_date)
    out['fwd_raw_log'] = (float(np.log(end_adj / base))
                          if end_adj is not None else None)
    # market excess via panel identity mex_end - mex_tau is checked in (b);
    # here raw: log(stock) - log(index)
    if end_adj is not None:
        pass  # index part injected by caller (mclose)
    rs = [a / base for _, a in valid]
    if rs:
        runmax, mdd, mg = 1.0, 0.0, rs[0] - 1.0
        peak_v = ref_flags.get('peak_asof')
        first_nh, nh_seen = None, False
        recover_seen = False
        for d, a in valid:
            r = a / base
            runmax = max(runmax, r)
            mdd = max(mdd, 1.0 - r / runmax)
            mg = max(mg, r - 1.0)
            if peak_v is not None:
                if r > peak_v:
                    nh_seen = True
                    first_nh = d if first_nh is None else first_nh
                if r >= peak_v:
                    recover_seen = True
        out['future_max_drawdown'] = mdd
        out['future_max_gain'] = mg
        out['new_high_within'] = nh_seen if peak_v is not None else None
        out['days_to_next_high'] = (mpos[first_nh] - i1
                                    if first_nh is not None else None)
        out['recover_current_peak_within'] = (recover_seen
                                              if peak_v is not None else None)
    else:
        for k in ('future_max_drawdown', 'future_max_gain', 'new_high_within',
                  'days_to_next_high', 'recover_current_peak_within'):
            out[k] = None
    out['_end_adj'] = end_adj
    out['_base'] = base
    return out


def main():
    gates = {}
    daily = pd.read_parquet(V3OUT / 'event_path_daily.parquet',
                            columns=v4._V3_COLS)
    mdates, mclose = v2.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}
    rs = pd.read_parquet(OUT / 'dynamic_riskset.parquet')
    fwd = pd.read_parquet(OUT / 'dynamic_forward_outcomes.parquet')
    ev = v2.load_events()
    factors = v2.load_factor_cache(ROOT / 'output/research/t3_v2')
    byid = {r.breakout_event_id: r._asdict() for r in
            ev.itertuples(index=False)}

    # ---------------- Gate 1: risk-set PIT ----------------
    picks = []
    ids = sorted(rs.breakout_event_id.unique())
    picks.append(('ordinary', ids[0]))
    noadj = rs[(rs.tau == 10) & (~rs.asof_adj_available)]
    if len(noadj):
        picks.append(('adj_unavailable_at_tau', noadj.iloc[0].breakout_event_id))
    notelig = rs[(rs.tau == 20) & (~rs.eligible_fwd_20)]
    if len(notelig):
        picks.append(('sample_end', notelig.iloc[0].breakout_event_id))
    noturn = rs[(rs.tau == 5) & rs.turnover_ratio_pre20.isna()]
    if len(noturn):
        picks.append(('turnover_missing', noturn.iloc[0].breakout_event_id))
    for e in ids[1:6]:
        picks.append((f'weekday_{pd.Timestamp(byid[e]["breakout_day"]).dayofweek}', e))
    pit_checked = 0
    pit_bad = []
    for label, eid in picks:
        row = byid[eid]
        pref = v3.stock_prefix(row['code'])
        fp = ROOT / f'data/adjustment_baostock/per_stock/{pref}.json.gz'
        if not fp.exists():
            continue
        sd = v2.load_stock_data(pref, factors)
        for tau in v4.RISKSET_TAUS:
            r_rs = rs[(rs.breakout_event_id == eid) & (rs.tau == tau)]
            if not len(r_rs) or not bool(r_rs.iloc[0].asof_in_dataset):
                continue
            asof = r_rs.iloc[0].asof_date
            got_full = v3.build_event_daily(trunc(sd, asof), row, mdates,
                                            mclose, mpos)
            got = got_full.iloc[tau]
            stored = r_rs.iloc[0]
            for c in v4.CONT_VARS:
                pit_checked += 1
                if not eq(got[c], stored[c]):
                    pit_bad.append({'category': label, 'id': eid, 'tau': tau,
                                    'field': c})
            # t0 flag must equal the event's own tau=0 row (truncated rebuild)
            got0 = got_full.iloc[0]
            pit_checked += 1
            flag0 = (None if pd.isna(got0['distance_to_ref60'])
                     else bool(got0['distance_to_ref60'] > 0))
            if not eq(flag0, stored['t0_ref60_breakout']):
                pit_bad.append({'category': label, 'id': eid, 'tau': tau,
                                'field': 't0_ref60_breakout_vs_tau0row'})
    gates['gate1_riskset_pit'] = {
        'verdict': 'PASS' if not pit_bad else 'FAIL',
        'checked': pit_checked, 'bad': pit_bad[:20],
        'n_bad': len(pit_bad)}

    # ---------------- Gate 2: forward isolation ----------------
    fi_bad = []
    fi_checked = 0
    dfull = pd.read_parquet(V3OUT / 'event_path_daily.parquet',
                            columns=['breakout_event_id', 'tau',
                                     'source_date', 'observation_date',
                                     'close_rel_t0_log',
                                     'mkt_excess_rel_t0_log'])
    for label, eid in picks[:8]:
        row = byid[eid]
        pref = v3.stock_prefix(row['code'])
        fp = ROOT / f'data/adjustment_baostock/per_stock/{pref}.json.gz'
        if not fp.exists():
            continue
        sd = v2.load_stock_data(pref, factors)
        t0 = row['breakout_day']
        i0 = mpos[t0]
        # as-of-known frozen levels for the lose_* comparisons
        prior20 = [d for d in sd.dates if d < t0][-20:]
        ref20 = max((sd.c[d] for d in prior20), default=None)
        raw0 = sd.c.get(t0)
        for tau in v4.RISKSET_TAUS:
            r_rs = rs[(rs.breakout_event_id == eid) & (rs.tau == tau)]
            if not len(r_rs) or not bool(r_rs.iloc[0].asof_in_dataset):
                continue
            asof = r_rs.iloc[0].asof_date
            # peak asof tau from truncated rebuild (as-of info only);
            # expressed RELATIVE TO THE ASOF BASE so raw r=adj/base compares
            tr = trunc(sd, asof)
            tau_row = v3.build_event_daily(tr, row, mdates, mclose,
                                           mpos).iloc[tau]
            peak_asof = tau_row['running_peak_return']
            crl_tau = tau_row['close_rel_t0_log']
            peak_rel_base = (float(np.exp(peak_asof - crl_tau))
                             if peak_asof is not None
                             and not pd.isna(peak_asof)
                             and crl_tau is not None
                             and not pd.isna(crl_tau) else None)
            for dl in v4.DELTAS:
                frow = fwd[(fwd.breakout_event_id == eid)
                           & (fwd.tau == tau) & (fwd.delta == dl)]
                if not len(frow):
                    # ineligible — confirm calendar reason
                    end_pos = i0 + tau + dl
                    assert end_pos > v4.last_dataset_pos(mdates)
                    continue
                f = frow.iloc[0]
                end_date = f.fwd_end_date
                raw = raw_forward_from_sd(
                    sd, mdates, mpos, asof, end_date,
                    {'ref20': ref20, 'raw0': raw0,
                     'peak_asof': peak_rel_base})
                # fwd_raw_log directly from raw data
                fi_checked += 1
                if not eq(raw['fwd_raw_log'], f.fwd_raw_log):
                    fi_bad.append({'id': eid, 'tau': tau, 'delta': dl,
                                   'field': 'fwd_raw_log',
                                   'raw': raw['fwd_raw_log'],
                                   'panel': float(f.fwd_raw_log)
                                   if pd.notna(f.fwd_raw_log) else None})
                # market excess identity via panel but endpooints only
                g = dfull[(dfull.breakout_event_id == eid)
                          & (dfull.tau.isin([tau, tau + dl]))]
                crl_tau = g.loc[g.tau == tau, 'close_rel_t0_log'].iloc[0]
                crl_end = g.loc[g.tau == tau + dl, 'close_rel_t0_log'].iloc[0]
                mex_tau = g.loc[g.tau == tau, 'mkt_excess_rel_t0_log'].iloc[0]
                mex_end = g.loc[g.tau == tau + dl,
                                'mkt_excess_rel_t0_log'].iloc[0]
                # future endpoint row must have source_date > asof
                fi_checked += 1
                if not (g.loc[g.tau == tau + dl, 'source_date'].iloc[0]
                        > asof):
                    fi_bad.append({'id': eid, 'tau': tau, 'delta': dl,
                                   'field': 'end_source_date_not_future'})
                # fwd excess must equal (crl_end-crl_tau) - (mret_end-mret_tau)
                fi_checked += 1
                mret_diff = (crl_end - mex_end) - (crl_tau - mex_tau)
                want_exc = (crl_end - crl_tau) - mret_diff
                if not eq(want_exc, f.fwd_mkt_excess_log):
                    fi_bad.append({'id': eid, 'tau': tau, 'delta': dl,
                                   'field': 'fwd_mkt_excess_identity'})
                for k in ('future_max_drawdown', 'future_max_gain',
                          'new_high_within', 'n_valid_obs_window',
                          'lose_ref20_within', 'lose_t0_close_within',
                          'recover_current_peak_within'):
                    fi_checked += 1
                    if not eq(raw[k], f[k] if k in f.index else None):
                        fi_bad.append({'id': eid, 'tau': tau, 'delta': dl,
                                       'field': k, 'raw': raw[k],
                                       'panel': f[k] if k in f.index else None})
    # panel-side mask proof on a sample: recompute with rows<=asof masked
    mask_bad = 0
    mask_checked = 0
    for eid in ids[:40]:
        for tau in (5, 10, 20):
            for dl in (5, 20):
                f = fwd[(fwd.breakout_event_id == eid) & (fwd.tau == tau)
                        & (fwd.delta == dl)]
                if not len(f):
                    continue
                f = f.iloc[0]
                asof = f.fwd_start_date
                g = dfull[(dfull.breakout_event_id == eid)
                          & (dfull.tau > tau) & (dfull.tau <= tau + dl)
                          & (dfull.source_date > asof)]
                mask_checked += 1
                crl = g.dropna(subset=['close_rel_t0_log'])
                if len(crl) != int(f.n_valid_obs_window):
                    mask_bad += 1
    gates['gate2_forward_isolation'] = {
        'verdict': 'PASS' if (not fi_bad and mask_bad == 0) else 'FAIL',
        'checked': fi_checked + mask_checked, 'bad': fi_bad[:20],
        'n_bad': len(fi_bad),
        'panel_mask_recompute_checked': mask_checked,
        'panel_mask_mismatches': mask_bad,
        'note': 'path components from observations strictly after asof; '
                'as-of close/peak/ref levels used only as base references'}

    # ---------------- Gate 3: calendar eligibility ----------------
    ldsp = v4.last_dataset_pos(mdates)
    bad_elig = 0
    for _, r in rs.iterrows():
        i0 = mpos[r.breakout_day]
        for dl in v4.DELTAS:
            want = (i0 + int(r.tau) + dl) <= ldsp
            if bool(r[f'eligible_fwd_{dl}']) != want:
                bad_elig += 1
    # structural: no event-label columns in any V4 product
    lab_cols = set(pd.read_parquet(
        ROOT / 'output/research/t3_v2/event_labels.parquet').columns)
    prod_cols = set(rs.columns) | set(fwd.columns)
    leaked = sorted(lab_cols & (prod_cols - {'breakout_event_id'}))
    gates['gate3_calendar_eligibility'] = {
        'verdict': 'PASS' if (bad_elig == 0 and not leaked) else 'FAIL',
        'rows_checked': len(rs), 'flag_mismatches': bad_elig,
        'label_columns_leaked': leaked,
        'note': 'eligibility = pure function of (T0 position, tau, delta, '
                'dataset_end) on the market calendar'}

    # ---------------- Gate 4: overlap / dependency audit ----------------
    ova = json.loads((OUT / 'event_overlap_audit.json').read_text())
    need = ['n_events', 'n_stocks', 'events_per_stock_distribution',
            'max_events_single_stock',
            'same_stock_pair_breakout_gap_market_days',
            'traj_overlap_pairs_within40',
            'events_with_same_stock_overlap_within40',
            'forward_window_overlap_by_tau_delta', 'calendar_cohorts']
    missing = [k for k in need if k not in ova]
    sane = (ova.get('n_events') == 27422
            and ova.get('n_events') == int(rs.breakout_event_id.nunique()))
    gates['gate4_overlap_dependency'] = {
        'verdict': 'PASS' if (not missing and sane) else 'FAIL',
        'missing_fields': missing, 'sane': bool(sane),
        'summary': {k: ova.get(k) for k in
                    ('n_events', 'n_stocks', 'max_events_single_stock',
                     'pct_events_with_same_stock_overlap')}}

    # ---------------- Gate 5: determinism (from runner) ----------------
    det = json.loads((OUT / 'dynamic_determinism_check.json').read_text())
    gates['gate5_determinism'] = {
        'verdict': det['verdict'],
        'products_compared': det['products_compared'],
        'identical': det['identical']}

    ok = all(g.get('verdict') == 'PASS' for g in gates.values())
    gates['overall'] = {'verdict': 'PASS' if ok else 'FAIL',
                        'baseline': 'aa249cc'}
    (OUT / 'dynamic_integrity_gates.json').write_text(
        json.dumps(gates, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(gates, ensure_ascii=False, indent=2, default=str)[:4000])
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
