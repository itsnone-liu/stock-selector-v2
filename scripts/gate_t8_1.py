#!/usr/bin/env python3
"""T8.1 gates — G41/G42/G43/G44 (frozen T8 Plan v2 §6)."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

T7 = T6.parent/'t7'
T8 = T6.parent/'t8'
OUT = T8/'01_order_anatomy'
W = 10


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t8_1_manifest.json').read_text())
    rep = json.loads((OUT/'t8_1_report_data.json').read_text())
    an = pd.read_parquet(OUT/'t8_1_order_anatomy.parquet')
    att = pd.read_parquet(T8/'00_sequence_factlayer/t8_0_cycle_attempt.parquet')
    out0 = pd.read_parquet(T7/'00_path_factlayer/t7_0_outcomes_outcomes.parquet',
                           columns=['event_id', 'r0_day', 'false_recovery',
                                    'true_recovery', 're_reduce_day'])

    gf.g1_lineage(log, man, OUT)

    # G41 segmentation discipline: full-population rows carry segment,
    # grouping fixed k1/k2/k3+, no freeze-era rule fields
    adds = att[att.has_add]
    ok41 = (len(an) == 15646
            and set(an.k_group.unique()) == {'k1', 'k2', 'k3+'}
            and an.k_group.isin(['k1', 'k2', 'k3+']).all()
            and ((an.k_add == 1) == (an.k_group == 'k1')).all()
            and ((an.k_add == 2) == (an.k_group == 'k2')).all()
            and ((an.k_add >= 3) == (an.k_group == 'k3+')).all()
            and set(an.segment.unique()) <= {'development', 'validation',
                                             'confirmation'})
    log.gate('G41_segmentation_fixed_grouping', ok41, rows=len(an))

    # G42 dual clock: W10 endpoint replay + frozen-flag passthrough
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj'])
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])
    agg = {ev: (g.delta_day.to_numpy(int), g.exposure_after_ref.to_numpy(float),
                g.close_adj.to_numpy(float))
           for ev, g in dm.groupby('event_id', sort=False)}
    m = adds.merge(out0, on=['event_id', 'r0_day'])
    key = {(r.event_id, int(r.a0_day)): (bool(r.false_recovery),
                                         bool(r.true_recovery))
           for r in m.itertuples()}
    # FULL-population deterministic replay (R1 hardening: 150 sample ->
    # all 15,646; added expo_days/contrib/cycle_life to the replay set)
    rr_map = {(r.event_id, int(r.a0_day)): float(r.re_reduce_day)
              for r in m.itertuples()}
    mism = 0
    for r in an.itertuples():
        offs, expo, close = agg[r.event_id]
        ia = int(np.searchsorted(offs, int(r.a0_day)))
        ie = min(ia + W, len(offs))
        win = np.log(close[ia:ie] / close[ia])
        ew = expo[ia:ie]
        fa, tr = key[(r.event_id, int(r.a0_day))]
        rrd = rr_map[(r.event_id, int(r.a0_day))]
        ok = (int(r.n_obs_w10) == ie - ia
              and abs(r.dd_w10 - win.min()) < 1e-12
              and abs(r.mfe_w10 - win.max()) < 1e-12
              and abs(r.ret_w10 - win[-1]) < 1e-12
              and abs(r.occ_w10 - ew.mean()) < 1e-12
              and abs(r.expo_days_w10 - ew.sum()) < 1e-9
              and abs(r.contrib_w10 - ew.mean() * win[-1]) < 1e-12
              and ((np.isnan(r.cycle_life) and not np.isfinite(rrd))
                   or abs(r.cycle_life - (rrd - int(r.a0_day))) < 1e-12)
              and r.false_add == fa and r.recovery == tr)
        if not ok:
            mism += 1
    log.gate('G42_dual_clock_replay', mism == 0,
             rows_checked=len(an), mismatches=mism,
             replay_fields='n_obs/dd/mfe/ret/occ/expo_days/contrib/'
                           'cycle_life/false_add/recovery')

    # G43/G44 discipline scans cover BOTH the machine JSON and the final
    # Markdown report (R1: the report is a research product too — the
    # wording overreach lived in the .md, not the json). Scanner hygiene:
    # (a) drop the report's own Gate section (self-referential mentions of
    #     the banned words inside the gate description are not overreach);
    # (b) drop negated quotations (≠ "…", 不是 "…") — prohibitions quote
    #     the banned phrasing to ban it;
    # (c) English tokens get \b so 'causes?' cannot match inside words.
    md = (ROOT/'docs/reports/T8_1_ORDER_ANATOMY.md').read_text()
    md_body = re.sub(r'## 5\. Gate.*?(?=## 6\.)', '', md, flags=re.S)
    md_body = re.sub(r'≠\s*"[^"]*"', '', md_body)
    md_body = re.sub(r'不是\s*\**\s*(?:>\s*)?"[^"]*"', '', md_body)
    md_body = re.sub(r'无因果词', '', md_body)
    nums = json.dumps({'by_k_group': rep['by_k_group'],
                       'by_segment': rep['by_segment'],
                       'appendix_per_k': rep['appendix_per_k']},
                      ensure_ascii=False)
    body_txt = nums + '\n@@@\n' + md_body
    ok43 = (not re.search(r'\bholm\b|\bsignifican|\bthreshold\b|'
                          r'\bcut[ _]?off\b|\brule\b', body_txt, re.I)
            and 'false_add_rate' in str(rep['by_k_group']['k1']))
    log.gate('G43_descriptive_only', ok43, scans=['report_data.json',
                                                  'T8_1_ORDER_ANATOMY.md'])
    ok44 = not re.search(r'导致|造成|因果|先验概率|\bcauses?\b|'
                         r'\bdue to\b|\beffect of k\b|'
                         r'\bprior probab', body_txt, re.I)
    log.gate('G44_estimand_naming', ok44, estimand=rep.get('estimand', ''),
             scans=['report_data.json', 'T8_1_ORDER_ANATOMY.md'],
             banned_extra='先验概率/prior probab (R1)',
             scanner='drops gate self-description + negated quotes; \\b on latin')

    sys.exit(log.finish(OUT/'t8_1_gates.json'))


if __name__ == '__main__':
    main()
