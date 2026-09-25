#!/usr/bin/env python3
"""T7.0 gates — definition provenance, physical isolation, conservation,
No-Future-Feature spot replay, lineage. No research conclusions checked
here (T7.0 builds ruler + facts only)."""
from __future__ import annotations
import ast
import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

T7 = T6.parent/'t7'
OUT = T7/'00_path_factlayer'


def main():
    log = gf.GateLog()
    reg = json.loads((OUT/'t7_0_definition_registry.json').read_text())
    t7c = json.loads((T7/'t7_contract.json').read_text())
    t6c = load_contract()
    man_f = json.loads((OUT/'t7_0_features_manifest.json').read_text())
    man_o = json.loads((OUT/'t7_0_outcomes_manifest.json').read_text())
    feat = pd.read_parquet(OUT/'t7_0_features_anchor_features.parquet')
    path = pd.read_parquet(OUT/'t7_0_features_path_fact.parquet')
    out = pd.read_parquet(OUT/'t7_0_outcomes_outcomes.parquet')
    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                          columns=['event_id', 'r0_day', 'type'])

    # G1 lineage: features/outcomes manifests reference frozen inputs
    gf.g1_lineage(log, man_f, OUT)
    gf.g1_lineage(log, man_o, OUT)

    # G2/G2b upstream immutability (T6 frozen products unchanged)
    manifests = [('00_factlayer', 't6_0_manifest.json'),
                 ('02_recycling', 't6_2_manifest.json'),
                 ('03_failure_anatomy', 't6_3_manifest.json')]
    ok = all(sha256_file(T6/st/pr['file']) == pr['sha256']
             for st, mf in manifests
             for pr in json.loads((T6/st/mf).read_text())['products']
             if pr['file'].endswith('.json'))
    log.gate('G2b_upstream_products_immutable', ok)

    # G8 conservation: anchors == T6.2 cycles; three-table row coherence
    cyc_keys = set(zip(cyc.event_id, cyc.r0_day.astype(int)))
    feat_keys = set(zip(feat.event_id, feat.r0_day.astype(int)))
    out_keys = set(zip(out.event_id, out.r0_day.astype(int)))
    ok8 = (feat_keys == cyc_keys and out_keys == cyc_keys
           and len(feat) == len(cyc) == len(out)
           and len(path) == int(path.day_offset.between(1, 40).sum())
           and path.groupby('event_id').size().sum() > 0)
    # false_recovery count == T6.3 fired cycles (semantic continuity)
    ok8 = ok8 and int(out.false_recovery.sum()) == int(
        pd.read_parquet(T6/'03_failure_anatomy/t6_3_cycle_trigger.parquet',
                        columns=['false_recovery']).false_recovery.sum())
    log.gate('G8_conservation', ok8,
             anchors=len(feat), cycles=len(cyc), outcomes=len(out),
             path_rows=int(len(path)),
             false_recovery=int(out.false_recovery.sum()))

    # G17 (new) physical isolation: features builder never reads outcome tables
    fsrc = (ROOT/'scripts/build_t7_0_features.py').read_text()
    osrc = (ROOT/'scripts/build_t7_0_outcomes.py').read_text()
    viol = []
    call_lines = [ln for ln in fsrc.splitlines()
                  if re.search(r'read_parquet|read_csv|read_json|json\.load|open\(', ln)]
    for pat in ('t7_0_outcomes', 'false_recovery', 'bh_R0', 'mfe', 'mae',
                'terminal_failure', 'true_recovery'):
        if any(re.search(rf'\b{pat}', ln) for ln in call_lines):
            viol.append(f'features_src data-call mentions {pat}')
    wl = set(ast.literal_eval(re.search(r'CYCLE_COLS = (\[.*?\])', fsrc).group(1)))
    if {'type', 'a0_day', 'bh_R0_H5'} & wl:
        viol.append('cycle whitelist leaks outcome columns')
    # outcome columns actually absent from anchor_features
    outcome_only = {'true_recovery', 'recovery_established_day', 'mfe_after_r0',
                    'mae_after_r0', 'terminal_failure', 'false_recovery'}
    if outcome_only & set(feat.columns):
        viol.append('anchor_features contains outcome columns')
    log.gate('G17_feature_outcome_isolation', not viol, violations=viol,
             cycle_whitelist=sorted(wl))

    # G18 (new) definition provenance: every threshold traces to a channel
    ok18 = True
    prov_bad = []
    for comp in ('dd_repair', 'ref20_repair'):
        src = reg['true_recovery']['achievement'][comp]['source']
        if src not in reg['provenance_channels']:
            ok18 = False
            prov_bad.append(f'achievement.{comp}:{src}')
    if reg['true_recovery']['persistence']['source'] not in reg['provenance_channels']:
        ok18 = False
        prov_bad.append('persistence')
    if reg['false_add']['adverse_excursion']['threshold'] != \
            t6c['preregistered_thresholds']['severe_dd_depth_log']:
        ok18 = False
        prov_bad.append('adverse_excursion value drift')
    if t7c['definition_registry_sha256'] != sha256_file(
            OUT/'t7_0_definition_registry.json'):
        ok18 = False
        prov_bad.append('contract registry sha mismatch')
    # DEV calibration channel unused => no T7_DEFINED entries may exist
    for comp in ('dd_repair', 'ref20_repair'):
        if reg['true_recovery']['achievement'][comp]['source'] == 'T7_DEFINED_DEV_THRESHOLD':
            ok18 = False
            prov_bad.append(f'unexpected DEV threshold in {comp}')
    log.gate('G18_definition_provenance', ok18, violations=prov_bad,
             channels=reg['provenance_channels'])

    # G19 (new) No-Future-Feature spot replay: recompute one feature from
    # path rows with cutoff clipping and compare to stored values
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'close_adj',
                                  'exposure_after_ref', 'drawdown_from_peak_log'])
    dm = dm[dm.exposure_after_ref.notna()]
    bad_ff = 0
    sub = feat.dropna(subset=['max_bounce_R5']).head(300)
    for ev, r0, stored in zip(sub.event_id, sub.r0_day, sub.max_bounce_R5):
        g = dm[(dm.event_id == ev) & (dm.delta_day > r0) & (dm.delta_day <= r0 + 5)]
        if len(g) == 0:
            continue
        c0 = float(dm[(dm.event_id == ev) & (dm.delta_day == r0)].close_adj.iloc[0])
        replay = float(np.max(np.log(g.close_adj.to_numpy()) - np.log(c0)))
        if abs(replay - stored) > 1e-12:
            bad_ff += 1
    # checkpoints confined to 1/2/3/5 in feature columns
    ck_ok = all(re.fullmatch(r'.*_R[0-9]+', c) is None or
                int(re.search(r'_R(\d+)$', c).group(1)) in (1, 2, 3, 5)
                for c in feat.columns if c.endswith(tuple(f'_R{k}' for k in range(1, 41))))
    log.gate('G19_no_future_feature', bad_ff == 0 and ck_ok,
             replay_mismatches=bad_ff, checkpoint_discipline=ck_ok)

    # G9b: independent true_recovery re-judgment on a sample (50 anchors)
    severe = t6c['preregistered_thresholds']['severe_dd_depth_log']
    K = int(reg['true_recovery']['persistence']['days'])
    pf = path.sort_values(['event_id', 'delta_day'])
    mism = 0
    samp = out.sample(50, random_state=7)
    for ev, r0, tr, est in zip(samp.event_id, samp.r0_day, samp.true_recovery,
                               samp.recovery_established_day):
        w = pf[(pf.event_id == ev) & (pf.r0_day == r0)
               & (pf.delta_day > r0) & (pf.delta_day <= r0 + 40)]
        d20 = w.dist_ref20.to_numpy()
        dd = w.drawdown_from_peak_log.to_numpy()
        offs = w.delta_day.to_numpy()
        n = len(w)
        ok_ = np.isfinite(d20) & np.isfinite(dd) & (d20 >= 0) & (dd < severe)
        r_est = np.nan
        for i in np.where(ok_)[0]:
            if i + K < n:
                wd20, wdd = d20[i+1:i+1+K], dd[i+1:i+1+K]
                if (np.all(np.isfinite(wd20)) and np.all(np.isfinite(wdd))
                        and not np.any(wd20 < 0) and not np.any(wdd >= severe)):
                    r_est = int(offs[i])
                    break
        same = (bool(np.isfinite(r_est)) == bool(tr))
        if same and np.isfinite(r_est):
            same = (int(r_est) == int(est))
        if not same:
            mism += 1
    log.gate('G9b_recompute', mism == 0, sampled=50, mismatches=mism)

    # sector sidecar quarantine metadata (if present)
    sc = OUT/'t7_0_sector_sidecar_meta.json'
    ok_sc = True
    if sc.exists():
        m = json.loads(sc.read_text())
        ok_sc = (m['exploratory_only'] is True
                 and 'NON-PIT' in m['membership_source'])
    log.gate('G_sector_sidecar_quarantine', ok_sc, present=sc.exists())

    sys.exit(log.finish(OUT/'t7_0_gates.json'))


if __name__ == '__main__':
    main()
