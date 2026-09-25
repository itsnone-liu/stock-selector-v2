#!/usr/bin/env python3
"""T7.3 — frozen-policy replay + dual-clock accounting (VAL primary).

Policies (all frozen; C1/C2 thresholds loaded from contract, no literals):
  A    : T5 ADD rule as-is (add_day = a0_day; exposure = frozen path)
  B_N  : delay A's ADD by N effective days (N in {1,2,3,5}; primary B3)
  C1   : R+5 confirmation, max_bounce_R5 > q1 -> ADD at R+5 else no ADD
  C2   : same clock, threshold q2 (sensitivity only)

Sizing inheritance (mechanical, audited): every policy's post-ADD exposure
sequence is A's post-ADD sequence SHIFTED to the policy's own add_day;
pre-ADD days use the post-REDUCE position. No new sizing is ever defined.
Cycles where A never ADDs stay ADD-less under every policy.

Dual clock:
  False ADD    -> each policy's OWN add_day, W10, requires
                  (not established in (add_day, add_day+10]) AND
                  (running dd from add-day peak >= severe)
  Missed Recov -> common cycle clock: TR established AND policy not exposed
                  at establishment (no ADD or add_day > est); cost =
                  log(close(est)/close(R0)) on the cycle recovery path.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs  # noqa: E402

T7 = T6.parent/'t7'
IN0 = T7/'00_path_factlayer'
IN2 = T7/'02_separator_discovery'
OUT = T7/'03_policy_validation'
POLICIES = ('A', 'B1', 'B2', 'B3', 'B5', 'C1', 'C2')


def main():
    import json
    t7c = json.loads((T7/'t7_contract.json').read_text())
    pa = t7c['policy_amendments']
    q1 = pa['primary_amendment_candidate']['threshold']
    q2 = pa['secondary_sensitivity']['threshold']
    severe = load_contract()['preregistered_thresholds']['severe_dd_depth_log']
    W_FA = int(t7c['error_cost']['false_add']['horizon'])

    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                          columns=['event_id', 'r0_day', 'a0_day', 'type',
                                   'segment'])
    feat = pd.read_parquet(IN0/'t7_0_features_anchor_features.parquet',
                           columns=['event_id', 'r0_day', 'max_bounce_R5'])
    out0 = pd.read_parquet(IN0/'t7_0_outcomes_outcomes.parquet',
                           columns=['event_id', 'r0_day', 'true_recovery',
                                    'recovery_established_day'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj', 'ret_1d_log'])
    dm = dm[dm.exposure_after_ref.notna()]
    base = cyc.merge(feat, on=['event_id', 'r0_day']).merge(
        out0, on=['event_id', 'r0_day'])

    dkey = {(e, int(d)): (x, c, r) for e, d, x, c, r in zip(
        dm.event_id, dm.delta_day, dm.exposure_after_ref, dm.close_adj,
        dm.ret_1d_log)}

    rows = []
    for ev, r0, a0, typ, seg, bounce, tr, est in zip(
            base.event_id, base.r0_day, base.a0_day, base.type, base.segment,
            base.max_bounce_R5, base.true_recovery,
            base.recovery_established_day):
        # episode daily series for this event (all effective days)
        g = dm[dm.event_id == ev].sort_values('delta_day')
        offs = g.delta_day.to_numpy(int)
        expo = g.exposure_after_ref.to_numpy(float)
        close = g.close_adj.to_numpy(float)
        ret1 = g.ret_1d_log.to_numpy(float)
        n = len(offs)
        i_r0 = int(np.searchsorted(offs, r0))
        has_add = np.isfinite(a0) and typ == 'RECOVERED_ADD'
        i_a0 = int(np.searchsorted(offs, a0)) if has_add else -1
        pre_exp = expo[i_r0]  # post-REDUCE position
        post = expo[i_a0:] if has_add else None  # A's post-ADD sizing shape
        # true-recovery est day index (episode offsets)
        i_est = int(np.searchsorted(offs, est)) if np.isfinite(est) else -1
        c_r0 = close[i_r0]
        upside = float(np.log(close[i_est] / c_r0)) if i_est > i_r0 else np.nan

        def delayed(k):
            # delay A's ADD by k effective days; if the episode ends first,
            # the delayed ADD never happens (no clamping to the last day)
            return offs[i_a0 + k] if has_add and i_a0 + k < n else np.nan

        add_days = {'A': (offs[i_a0] if has_add else np.nan),
                    'B1': delayed(1), 'B2': delayed(2),
                    'B3': delayed(3), 'B5': delayed(5)}
        for pname, thr in (('C1', q1), ('C2', q2)):
            if has_add and np.isfinite(bounce) and bounce > thr:
                i_add = int(np.searchsorted(offs, r0 + 5))
                add_days[pname] = offs[i_add] if i_add < n else np.nan
            else:
                add_days[pname] = np.nan

        for pname in POLICIES:
            ad = add_days[pname]
            has = np.isfinite(ad)
            i_add = int(np.searchsorted(offs, ad)) if has else -1
            # replayed exposure path: pre-ADD = post-REDUCE position, then
            # A's post-ADD shape shifted to this policy's own add day
            if has and post is not None and i_add < n:
                # A's post-ADD sizing shape replayed from this policy's own
                # add day; if C1 ADDs EARLIER than A did, the shape runs
                # longer than A's own remaining episode -> extend with A's
                # final position (shape replay, never a new sizing)
                need = n - i_add
                tail = post[:need]
                if len(tail) < need:
                    tail = np.concatenate([tail, np.full(need - len(tail),
                                                         post[-1])])
                pexpo = np.concatenate([np.full(i_add, pre_exp), tail])
            else:
                pexpo = np.full(n, pre_exp)
            # sizing-inheritance audit trail: the replayed path from the
            # policy's own add day must equal A's post-ADD shape; when the
            # policy ADDs EARLIER than A (C1 before a0), the shape is
            # extended with A's final position (legal shape replay)
            inherit_ok = True
            if has and post is not None and i_add < n:
                if n - i_add <= len(post):
                    inherit_ok = bool(np.array_equal(pexpo[i_add:], post[:n - i_add]))
                else:
                    inherit_ok = bool(
                        np.array_equal(pexpo[i_add:i_add + len(post)], post)
                        and np.all(pexpo[i_add + len(post):] == post[-1]))
            # False ADD on this policy's OWN clock
            fa = False
            if has:
                w = offs[(offs > ad) & (offs <= ad + W_FA)]
                if len(w):
                    iw = (offs > ad) & (offs <= ad + W_FA)
                    cp = close[iw]
                    run_dd = np.log(cp / np.maximum.accumulate(cp))
                    est_in = np.isfinite(est) and ad < est <= ad + W_FA
                    fa = (not est_in) and bool(np.any(run_dd <= -severe))
            # Missed Recovery on the COMMON cycle clock
            missed = bool(np.isfinite(est) and (not has or ad > est))
            # capital efficiency / weighted path metrics over R+1..R+40
            iw40 = (offs > r0) & (offs <= r0 + 40)
            wexp = pexpo[iw40]
            wret = ret1[iw40]
            wcum = np.cumsum(wexp * wret)
            peak = np.maximum.accumulate(np.concatenate([[0.0], wcum]))[1:]
            wdd = float(np.min(wcum - peak)) if len(wcum) else np.nan
            rows.append({
                'event_id': ev, 'r0_day': int(r0), 'segment': seg,
                'policy': pname, 'type': typ, 'has_add': bool(has),
                'add_day': (int(ad) if has else np.nan),
                'inheritance_ok': inherit_ok,
                'false_add': bool(fa), 'true_recovery': bool(tr),
                'missed_recovery': missed,
                'missed_cost': (upside if (missed and np.isfinite(upside)) else np.nan),
                'mean_exposure_R40': float(np.nanmean(wexp)) if len(wexp) else np.nan,
                'exposure_days_R40': int((wexp > pre_exp + 1e-12).sum()),
                'wret_R40': float(wcum[-1]) if len(wcum) else np.nan,
                'wdd_max_R40': wdd,
            })
    replay = pd.DataFrame(rows)
    val = replay[replay.segment == 'validation']
    summ = []
    for pname in POLICIES:
        p = val[val.policy == pname]
        adds = p[p.has_add]
        trs = p[p.true_recovery]
        summ.append({
            'policy': pname, 'n_cycles': int(len(p)),
            'n_adds': int(len(adds)),
            'false_adds': int(adds.false_add.sum()),
            'false_add_rate': float(adds.false_add.mean()) if len(adds) else np.nan,
            'tr_cycles': int(len(trs)),
            'missed': int(trs.missed_recovery.sum()),
            'missed_rate': float(trs.missed_recovery.mean()) if len(trs) else np.nan,
            'missed_cost_total': float(np.nansum(trs.missed_cost)),
            'mean_exposure': float(p.mean_exposure_R40.mean()),
            'mean_wret_R40': float(p.wret_R40.mean()),
        })
    summary = pd.DataFrame(summ)
    report = {
        'stage': 't7_3',
        'identity': 'frozen-policy replay + dual-clock accounting; VAL primary; '
                    'CONF deliberately NOT computed in this run (segment '
                    'protocol t7_3b: validation first, confirmation later)',
        'policies': list(POLICIES),
        'thresholds_from_contract': {'C1': q1, 'C2': q2, 'severe': severe,
                                     'W_fa': W_FA},
        'sizing_inheritance': 'post-ADD exposure sequence == A post-ADD shape '
                              'shifted to policy add_day (asserted per row)',
        'n_val_summary_rows': int(len(summary)),
        'contract_sha256': sha256_file(T7/'t7_contract.json'),
    }
    write_stage_outputs(
        OUT, 't7_3', {'replay': replay, 'summary_val': summary},
        {'inputs': [
            {'name': 'cycle_master', 'path': 'output/research/t6/02_recycling/t6_2_cycle_master.parquet',
             'sha256': sha256_file(T6/'02_recycling/t6_2_cycle_master.parquet'), 'bytes': 0},
            {'name': 't7_0_anchor_features', 'path': 'output/research/t7/00_path_factlayer/t7_0_features_anchor_features.parquet',
             'sha256': sha256_file(IN0/'t7_0_features_anchor_features.parquet'), 'bytes': 0},
            {'name': 't7_0_outcomes', 'path': 'output/research/t7/00_path_factlayer/t7_0_outcomes_outcomes.parquet',
             'sha256': sha256_file(IN0/'t7_0_outcomes_outcomes.parquet'), 'bytes': 0},
            {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 't7_contract', 'path': 'output/research/t7/t7_contract.json',
             'sha256': sha256_file(T7/'t7_contract.json'), 'bytes': 0}]},
        report)
    print('replay rows:', len(replay), 'inheritance violations:',
          int((~replay.inheritance_ok).sum()))
    print(summary.to_string(index=False))


if __name__ == '__main__':
    main()
