#!/usr/bin/env python3
"""T7.4 — F6 taxonomy decomposition (all segments, first-hit by frozen
ORDER D4->D1->D2->D3->D5->F6'). Runs strictly AFTER the taxonomy freeze
commit; every condition variable comes from frozen T6/T7 facts:

  cycle count / endpoint return / episode DD / episode_class / REDUCE count
      -> t6_3_failure_anatomy.parquet (frozen)
  D2 failure clock (a0_day, trigger_day, effective spacing)
      -> t6_3_cycle_trigger.parquet (frozen) + daily master offsets
  span / exposure occupancy / tail single-day return / pre-break DD
      -> T6.0 daily master (frozen close_adj / exposure_after_ref)

No policy derivation; no sector variables; no distribution peeking before
classification (the taxonomy is already frozen in contract).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file, write_stage_outputs  # noqa: E402

T7 = T6.parent/'t7'
T63 = T6/'03_failure_anatomy'
IN0 = T7/'00_path_factlayer'
OUT = T7/'04_f6_taxonomy'
SEVERE = 0.1053605156578263
LOG95 = float(np.log(0.95))


def main():
    tax = json.loads((T7/'t7_4_f6_taxonomy.json').read_text())
    an = pd.read_parquet(T63/'t6_3_failure_anatomy.parquet')
    ct = pd.read_parquet(T63/'t6_3_cycle_trigger.parquet')
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj', 'ret_1d_log'])
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])

    f6 = an[an.F_stage == 'F6'].copy()
    f6['end_mark_loss'] = f6.ret_norm_ep < 0
    f6['endpoint_status'] = np.where(f6.terminal_reason == 'MAX_HORIZON',
                                     'censored', 'terminal')

    # per-episode daily aggregates from the frozen fact layer
    agg = {}
    for ev, g in dm.groupby('event_id', sort=False):
        offs = g.delta_day.to_numpy(int)
        expo = g.exposure_after_ref.to_numpy(float)
        ret1 = g.ret_1d_log.to_numpy(float)
        close = g.close_adj.to_numpy(float)
        agg[ev] = (offs, expo, ret1, close)

    # D2 clock: effective-observation offset of trigger_day relative to a0_day
    d2_hit = {}
    for ev, gg in ct.groupby('event_id'):
        recs = gg[(gg.type == 'RECOVERED_ADD') & (gg.false_recovery == True)]
        if ev in agg:
            offs = agg[ev][0]
            for r in recs.itertuples():
                if not (np.isfinite(r.a0_day) and np.isfinite(r.trigger_day)):
                    continue  # not observed -> not D2
                ia = int(np.searchsorted(offs, r.a0_day))
                it = int(np.searchsorted(offs, r.trigger_day))
                off = it - ia  # effective observations after A0
                if off > 5:
                    d2_hit[ev] = True

    rows = []
    for r in f6.itertuples():
        ev = r.event_id
        offs, expo, ret1, close = agg.get(ev, (None, None, None, None))
        cls = "F6'"
        var = {}
        if offs is not None:
            n = len(offs)
            # D4 sudden_break: tail 5 effective obs with single-day <= -7%
            # and pre-break episode max DD non-severe
            tail = ret1[max(0, n - 5):]
            brk = np.where(tail <= -0.07)[0]
            d4 = False
            if len(brk):
                bi = max(0, n - 5) + int(brk[0])
                pre = close[:bi + 1]
                pre_dd = float(np.min(np.log(pre / np.maximum.accumulate(pre)))) \
                    if len(pre) else 0.0
                d4 = pre_dd > -SEVERE
                var['d4_break_ret'] = float(tail[int(brk[0])])
                var['d4_pre_break_dd'] = pre_dd
            # D1 oscillation: >=3 REDUCE->ADD cycles + end_mark_loss
            d1 = bool(r.n_add >= 3 and r.end_mark_loss)
            # D2 late false recovery (strict clock, observed)
            d2 = bool(d2_hit.get(ev, False))
            # D3 slow grind: span>=60 effective days, DD in (log0.95, -severe],
            # REDUCE count <=1, end_mark_loss
            dd_ep = float(r.drawdown_from_peak_log) \
                if np.isfinite(r.drawdown_from_peak_log) else np.nan
            d3 = bool(n >= 60 and LOG95 >= dd_ep > -SEVERE
                      and r.n_reduce <= 1 and r.end_mark_loss)
            # D5 high exposure stagnation: occupancy>=80%, no RECOVERED_ADD
            occ = float(np.nanmean(expo))
            has_ra = bool((ct[ct.event_id == ev].type == 'RECOVERED_ADD').any())
            d5 = bool(occ >= 0.80 and not has_ra and r.end_mark_loss)
            var.update(span=n, occupancy=occ, dd_ep=dd_ep,
                       n_add=int(r.n_add), n_reduce=int(r.n_reduce))
            if d4:
                cls = 'D4'
            elif d1:
                cls = 'D1'
            elif d2:
                cls = 'D2'
            elif d3:
                cls = 'D3'
            elif d5:
                cls = 'D5'
        rows.append({'event_id': ev, 'segment': r.segment,
                     'episode_class': r.episode_class,
                     'end_mark_loss': bool(r.end_mark_loss),
                     'endpoint_status': r.endpoint_status,
                     'f6_class': cls,
                     'span': var.get('span'), 'occupancy': var.get('occupancy'),
                     'dd_ep': var.get('dd_ep'), 'n_add': var.get('n_add'),
                     'n_reduce': var.get('n_reduce'),
                     'd4_break_ret': var.get('d4_break_ret'),
                     'd4_pre_break_dd': var.get('d4_pre_break_dd')})
    cls_df = pd.DataFrame(rows)

    # cross-tabs: class x segment x endpoint_status x episode_class
    ct1 = cls_df.groupby(['f6_class', 'segment']).size().unstack(fill_value=0)
    ct2 = cls_df.groupby(['f6_class', 'endpoint_status']).size().unstack(fill_value=0)
    ct3 = cls_df.groupby(['f6_class', 'episode_class']).size().unstack(fill_value=0)
    report = {
        'stage': 't7_4',
        'identity': 'F6 taxonomy decomposition, all segments, first-hit '
                    'ORDER D4->D1->D2->D3->D5->F6-prime (frozen '
                    't7_4_f6_taxonomy.json); no policy derivation; F6-prime '
                    'large is NOT failure',
        'order': tax['order'],
        'n_f6_total': int(len(cls_df)),
        'class_counts': cls_df.f6_class.value_counts().to_dict(),
        'by_segment': {c: ct1[c].to_dict() for c in ct1.columns},
        'by_endpoint_status': {c: ct2[c].to_dict() for c in ct2.columns},
        'by_episode_class': {c: ct3[c].to_dict() for c in ct3.columns},
        'taxonomy_sha256': sha256_file(T7/'t7_4_f6_taxonomy.json'),
        'taxonomy_freeze_commit': '3067d22',
        'inputs': [
            {'name': 't6_3_failure_anatomy', 'sha256':
             sha256_file(T63/'t6_3_failure_anatomy.parquet')},
            {'name': 't6_3_cycle_trigger', 'sha256':
             sha256_file(T63/'t6_3_cycle_trigger.parquet')},
            {'name': 't6_0_daily_master', 'sha256':
             sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet')},
        ],
    }
    inputs = [
        {'name': 't6_3_failure_anatomy',
         'path': 'output/research/t6/03_failure_anatomy/t6_3_failure_anatomy.parquet',
         'sha256': sha256_file(T63/'t6_3_failure_anatomy.parquet'), 'bytes': 0},
        {'name': 't6_3_cycle_trigger',
         'path': 'output/research/t6/03_failure_anatomy/t6_3_cycle_trigger.parquet',
         'sha256': sha256_file(T63/'t6_3_cycle_trigger.parquet'), 'bytes': 0},
        {'name': 't6_0_daily_master',
         'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
         'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
        {'name': 't7_4_f6_taxonomy',
         'path': 'output/research/t7/t7_4_f6_taxonomy.json',
         'sha256': sha256_file(T7/'t7_4_f6_taxonomy.json'), 'bytes': 0},
    ]
    write_stage_outputs(OUT, 't7_4', {'classification': cls_df},
                        {'inputs': inputs}, report)
    print(cls_df.f6_class.value_counts().to_string())
    print('total', len(cls_df))
    print(ct1.to_string())
    print(ct2.to_string())


if __name__ == '__main__':
    main()
