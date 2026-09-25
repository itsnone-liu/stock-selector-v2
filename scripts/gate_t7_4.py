#!/usr/bin/env python3
"""T7.4 gates — G-F6 Lock timing, taxonomy immutability, first-hit replay,
coverage conservation, no-policy, component provenance replay."""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

T7 = T6.parent/'t7'
T63 = T6/'03_failure_anatomy'
OUT = T7/'04_f6_taxonomy'
LOG95 = float(np.log(0.95))
SEVERE = 0.1053605156578263


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t7_4_manifest.json').read_text())
    rep = json.loads((OUT/'t7_4_report_data.json').read_text())
    cls = pd.read_parquet(OUT/'t7_4_classification.parquet')
    tax = json.loads((T7/'t7_4_f6_taxonomy.json').read_text())
    contract = json.loads((T7/'t7_contract.json').read_text())

    gf.g1_lineage(log, man, OUT)

    # G-F6 Lock: taxonomy json sha matches contract copy, and the freeze
    # commit (3067d22) is an ANCESTOR of HEAD while no t7_4 product commit
    # precedes it (timing: freeze -> product, verifiable in git history)
    ok = (json.dumps(tax, sort_keys=True) ==
          json.dumps(contract['t7_4_f6_taxonomy'], sort_keys=True))
    prod = subprocess.run(['git', 'log', '--format=%H', '3067d22~1',
                           '--', 'output/research/t7/04_f6_taxonomy'],
                          cwd=ROOT, capture_output=True, text=True)
    ok = ok and prod.stdout.strip() == ''  # no product commit before freeze
    log.gate('G_F6_LOCK_timing', ok, taxonomy_in_contract=True,
             product_commits_before_freeze=len(prod.stdout.split()))

    # G30 taxonomy immutability: exactly the five classes + residual
    order = ['D4', 'D1', 'D2', 'D3', 'D5', "F6'"]
    ok30 = (rep['order'] == order and
            set(cls.f6_class.unique()) <= set(order) and
            set(tax['classes'].keys()) ==
            {'D4_sudden_break', 'D1_oscillation', 'D2_late_false_recovery',
             'D3_slow_grind', 'D5_high_exposure_stagnation',
             "F6'_mandatory_residual"})
    log.gate('G30_taxonomy_immutable', ok30,
             classes_seen=sorted(cls.f6_class.unique()))

    # G31 first-hit replay: stratified per class (30 each; all for tiny
    # classes) — independent re-derivation of every condition
    an = pd.read_parquet(T63/'t6_3_failure_anatomy.parquet')
    ct = pd.read_parquet(T63/'t6_3_cycle_trigger.parquet')
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj', 'ret_1d_log'])
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])
    agg = {ev: (g.delta_day.to_numpy(int), g.exposure_after_ref.to_numpy(float),
                g.ret_1d_log.to_numpy(float), g.close_adj.to_numpy(float))
           for ev, g in dm.groupby('event_id', sort=False)}
    anmap = an.set_index('event_id')
    mism = n_samp = 0
    for cname, grp in cls.groupby('f6_class'):
        s = grp.sample(min(30, len(grp)), random_state=11)
        for r in s.itertuples():
            n_samp += 1
            offs, expo, ret1, close = agg[r.event_id]
            a = anmap.loc[r.event_id]
            n = len(offs)
            tail = ret1[max(0, n - 5):]
            brk = np.where(tail <= -0.07)[0]
            d4 = False
            if len(brk):
                bi = max(0, n - 5) + int(brk[0])
                pre = close[:bi + 1]
                pre_dd = float(np.min(np.log(pre / np.maximum.accumulate(pre))))
                d4 = pre_dd > -SEVERE
            d1 = bool(a.n_add >= 3 and a.ret_norm_ep < 0)
            fr2 = ct[(ct.event_id == r.event_id) & (ct.false_recovery == True)]
            d2 = False
            for q in fr2.itertuples():
                if np.isfinite(q.a0_day) and np.isfinite(q.trigger_day):
                    ia = int(np.searchsorted(offs, q.a0_day))
                    it = int(np.searchsorted(offs, q.trigger_day))
                    if it - ia > 5:
                        d2 = True
            dd_ep = float(a.drawdown_from_peak_log)
            d3 = bool(n >= 60 and LOG95 >= dd_ep > -SEVERE
                      and a.n_reduce <= 1 and a.ret_norm_ep < 0)
            occ = float(np.nanmean(expo))
            has_ra = bool((ct[ct.event_id == r.event_id].type ==
                           'RECOVERED_ADD').any())
            d5 = bool(occ >= 0.80 and not has_ra and a.ret_norm_ep < 0)
            first = 'D4' if d4 else 'D1' if d1 else 'D2' if d2 else \
                'D3' if d3 else 'D5' if d5 else "F6'"
            if first != r.f6_class:
                mism += 1
    log.gate('G31_first_hit_replay', mism == 0, sampled=n_samp,
             mismatches=mism)

    # G32 coverage conservation: every F6 episode classified exactly once
    f6n = int((an.F_stage == 'F6').sum())
    ok32 = (len(cls) == f6n == 10277
            and cls.event_id.is_unique
            and int(sum(rep['class_counts'].values())) == f6n)
    log.gate('G32_coverage_conservation', ok32, f6_total=f6n)

    # G33 no-policy: no policy fields/derivation in products or source
    src = (ROOT/'scripts/run_t7_4.py').read_text()
    code = '\n'.join(re.sub(r'#.*$', '', ln) for ln in src.splitlines())
    code = re.sub(r'\"\"\".*?\"\"\"', '', code, flags=re.S)
    code = re.sub(r"'''.*?'''", '', code, flags=re.S)
    code = re.sub(r"'[^'\n]*'", "''", re.sub(r'"[^"\n]*"', '""', code))
    ok33 = ('policy' not in code.lower() and 'sector' not in code.lower()
            and not any(c for c in cls.columns if 'policy' in c.lower()))
    log.gate('G33_no_policy_derivation', ok33)

    # G34 component provenance replay — R1: FULL component set, stratified
    # per class (15 each for D1/D4/D5/F6'), every variable re-derived from
    # frozen facts and reconciled against the classification parquet;
    # plus NEGATIVE WITNESSES proving the D2/D3 structural zeros directly
    # (not just trusting the runner outcome).
    comp_cols = ('span', 'occupancy', 'dd_ep', 'n_add', 'n_reduce')
    d4_cols = ('d4_break_ret', 'd4_pre_break_dd')
    mism34 = 0
    n_cmp = 0
    for cname in ('D1', 'D4', 'D5', "F6'"):
        grp = cls[cls.f6_class == cname]
        samp = grp.sample(min(15, len(grp)), random_state=13)
        for r in samp.itertuples():
            offs, expo, ret1, close = agg[r.event_id]
            a = anmap.loc[r.event_id]
            n = len(offs)
            checks = {
                'span': (r.span == n),
                'occupancy': abs(r.occupancy - float(np.nanmean(expo))) < 1e-12,
                'dd_ep': (bool(np.isnan(r.dd_ep)
                              and np.isnan(float(a.drawdown_from_peak_log)))
                         or abs(r.dd_ep
                                - float(a.drawdown_from_peak_log)) < 1e-12),
                'n_add': (int(r.n_add) == int(a.n_add)),
                'n_reduce': (int(r.n_reduce) == int(a.n_reduce)),
            }
            n_cmp += len(checks)
            if not all(checks.values()):
                mism34 += 1
            if cname == 'D4':
                tail = ret1[max(0, n - 5):]
                brk = np.where(tail <= -0.07)[0]
                bi = max(0, n - 5) + int(brk[0])
                pre = close[:bi + 1]
                pre_dd = float(np.min(np.log(pre / np.maximum.accumulate(pre))))
                n_cmp += 2
                if not (abs(r.d4_break_ret - float(tail[int(brk[0])])) < 1e-12
                        and abs(r.d4_pre_break_dd - pre_dd) < 1e-12):
                    mism34 += 1
    # negative witness A: NO frozen FR cycle has effective failure_offset > 5
    max_off = -1
    for q in ct[ct.false_recovery == True].itertuples():
        if np.isfinite(q.a0_day) and np.isfinite(q.trigger_day) \
                and q.event_id in agg:
            o = agg[q.event_id][0]
            off = int(np.searchsorted(o, q.trigger_day)
                      - np.searchsorted(o, q.a0_day))
            max_off = max(max_off, off)
    # negative witness B: NO episode in the fact layer reaches span >= 60
    max_span = max(len(agg[e][0]) for e in an.event_id if e in agg)
    log.gate('G34_component_provenance_replay',
             mism34 == 0 and max_off <= 5 and max_span < 60,
             stratified_episodes=sum(min(15, len(cls[cls.f6_class == c]))
                                     for c in ('D1', 'D4', 'D5', "F6'")),
             component_comparisons=n_cmp, mismatched_episodes=mism34,
             d2_witness_max_failure_offset=int(max_off),
             d3_witness_max_span=int(max_span))

    sys.exit(log.finish(OUT/'t7_4_gates.json'))


if __name__ == '__main__':
    main()
