#!/usr/bin/env python3
"""T7.0 Step 1 — Definition Audit + Contract assembly.

Produces output/research/t7/t7_contract.json and
output/research/t7/00_path_factlayer/t7_0_definition_registry.json.

Threshold provenance channels (exactly three, per T7 plan v2 §14):
  T6_FROZEN            value inherited verbatim from t6_contract
  T6_FROZEN_SEMANTIC   semantic inherited from a frozen T6 definition
  T7_DEFINED_DEV_THRESHOLD  deterministic DEV-only one-shot calibration
                       (rule preregistered HERE, before any VAL/CONF read)

This script reads ONLY frozen T6 products + the DEV segment. It computes
the single DEV-calibrated constant (X_dd) via a fixed unconditional rule
and records its provenance. No research conclusions are drawn.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file  # noqa: E402

T7 = T6.parent/'t7'
OUT = T7/'00_path_factlayer'


def main():
    t6c = load_contract()
    t6t = t6c['preregistered_thresholds']

    # ---- Calibration audit trace (why NO T7-defined threshold exists) ---
    # Rule v1 considered: X_dd = DEV unconditional median of dd_repair_ratio
    # at R+5. Diagnosed degenerate: >50% of DEV anchors never repair at all
    # (max repair over the whole R+1..R+40 window = 0 for the median cycle),
    # so ANY unconditional quantile at/below the median collapses to 0.0 and
    # the achievement condition degenerates. Resolution: inherit the T6
    # severe boundary instead -> achievement-dd = dd(t) < severe_dd_depth_log,
    # equivalent to the per-anchor dynamic ratio threshold
    #   ratio >= 1 - severe_dd_depth_log / det_dd_R0 (floored at 0)
    # which is exact for deep-deterioration cycles and correctly trivial for
    # shallow ones (they were never inside the severe region). Zero new
    # thresholds; the DEV calibration channel is left UNUSED and documented.
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'segment',
                                  'exposure_after_ref', 'drawdown_from_peak_log'])
    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                          columns=['event_id', 'segment', 'r0_day',
                                   'det_drawdown_from_peak_log'])
    dev = dm[dm.exposure_after_ref.notna() & (dm.segment == 'development')]
    dev = dev.sort_values(['event_id', 'delta_day'])
    n_calib, maxrep_nonzero = 0, 0
    for e, r0, det in zip(cyc[cyc.segment == 'development'].event_id,
                          cyc[cyc.segment == 'development'].r0_day,
                          cyc[cyc.segment == 'development'].det_drawdown_from_peak_log):
        g = dev[dev.event_id == e]
        if len(g) == 0 or not np.isfinite(det) or det <= 0:
            continue
        dd = g.set_index('delta_day').drawdown_from_peak_log
        fut = dd[dd.index > r0]
        if len(fut) == 0:
            continue
        n_calib += 1
        if ((det - fut) / det).clip(0, 1).max() > 0:
            maxrep_nonzero += 1
    calib_trace = {
        'rule_v1': 'DEV unconditional median of dd_repair_ratio@R+5',
        'diagnosis': ('degenerate: median cycle never repairs within the window '
                      f'(n={n_calib} DEV anchors, only {maxrep_nonzero} reach any '
                      f'positive repair; share={maxrep_nonzero/max(1,n_calib):.3f})'),
        'resolution': 'achievement-DD restated as a NON-SEVERE-REGION condition (dd(t) < severe_dd_depth_log); for shallow cycles already non-severe at R0 the condition is trivially satisfied and achievement rests on ref20+persistence; T7_DEFINED_DEV_THRESHOLD channel left unused',
        'n_calib': n_calib, 'n_any_repair': maxrep_nonzero,
    }

    registry = {
        'registry_version': 't7_0_v1',
        'semantic_doc': {
            'true_recovery': (
                'Cycle-level property. recovery_established_day = first effective day t in '
                '(R0, R+40-K] with achievement AND persistence. Achievement(t): dist_ref20(t) >= 0 '
                '(structure position repaired) AND drawdown_from_peak_log(t) < severe_dd_depth_log '
                '(in / maintaining the non-severe drawdown region). Persistence(t): within the '
                'next K effective trading days the T6.3-R1 F3 failure condition (dist_ref20 < 0 OR '
                'drawdown_from_peak_log >= severe_dd_depth_log) does NOT fire. HONEST SCOPING: for '
                'shallow-deterioration cycles already inside the non-severe region at R0, the DD '
                'condition does NOT require any further repair relative to R0 — achievement then '
                'rests on ref20 repair + persistence. The DD condition is a REGION condition '
                '(non-severe), not a relative-repair claim.'),
            'false_add': (
                'Policy-level (T7.5). Anchor = policy_add_day (the counterfactual policy\'s OWN '
                'ADD day — NOT the T5 A0). Within W_fa=10 effective days after policy_add_day: '
                'True-Recovery-not-established-in-window AND adverse excursion '
                '(drawdown_from_peak_log from the add >= severe_dd_depth_log). Re-REDUCE/EXIT '
                'are SECONDARY diagnostics only (action-based, self-referential).'),
            'missed_recovery': (
                'Policy-level (T7.5). Anchor = the cycle/recovery-opportunity clock (R0), NOT '
                'any policy add day. Requires: policy not exposed (veto/delayed past the '
                'opportunity) AND the cycle reaches True Recovery. Cost = recovery upside not '
                'captured, measured on the cycle recovery path.'),
            'dd_repair_ratio': (
                'dd_repair_ratio(t) = clip((det_dd_R0 - drawdown_from_peak_log(t)) / det_dd_R0, '
                '0, 1) where det_dd_R0 = drawdown_from_peak_log at R0 (>0 by cycle definition). '
                'Variables inherited from frozen T6 fact layer.'),
            'clock_separation': (
                'False ADD clock: policy-ADD-anchored. Missed Recovery clock: '
                'cycle/opportunity-anchored. Mixing them is a gate violation '
                '(G-Counterfactual Conservation: policy-specific outcome clock audit).'),
        },
        'calibration_trace': calib_trace,
        'true_recovery': {
            'achievement': {
                'dd_nonsevere_region': {'threshold': 'drawdown_from_peak_log(t) < severe_dd_depth_log',
                              'source': 'T6_FROZEN',
                              'rule': ('REGION condition: drawdown is in (or maintains) the non-severe '
                                       'region; NOT a relative-repair claim — for shallow cycles already '
                                       'non-severe at R0 the condition is trivially satisfied and achievement '
                                       'rests on ref20 repair + persistence; both the value and the region '
                                       'semantics are inherited from t6_contract')},
                'ref20_repair': {'threshold': 'dist_ref20 >= 0',
                                 'source': 'T6_FROZEN_SEMANTIC',
                                 'rule': 'complement of the T6.3-R1 F3 failure condition (dist_ref20 < 0); zero-literal exemption applies'},
            },
            'persistence': {
                'days': 5,
                'source': 'T6_FROZEN',
                'rule': 'K=5 effective trading days inherited from the frozen T6.3-R1 false-recovery trigger window; the persistence condition is the mirror of the frozen F3 trigger (same 5-day window, same failure conditions, must NOT fire)'},
        },
        'false_add': {
            'anchor': 'policy_add_day',
            'horizon': 10,
            'requires': ['not_true_recovery_in_window',
                         'adverse_excursion'],
            'adverse_excursion': {'threshold': t6t['severe_dd_depth_log'],
                                  'source': 'T6_FROZEN',
                                  'rule': 'severe_dd_depth_log inherited verbatim from t6_contract preregistered_thresholds'},
            'action_diagnostics': {'re_reduce': 'secondary', 'exit': 'secondary'},
        },
        'missed_recovery': {
            'anchor': 'recovery_opportunity',
            'requires': ['policy_not_exposed', 'true_recovery'],
            'cost': 'recovery_upside_not_captured',
        },
        'provenance_channels': ['T6_FROZEN', 'T6_FROZEN_SEMANTIC',
                                'T7_DEFINED_DEV_THRESHOLD'],
    }

    contract = {
        'stage_order': ['T7.0 fact layer + definitions', 'T7.1 path anatomy',
                        'T7.2 hot-bounce structure (DEV only)',
                        'T7.3a separator discovery (DEV only) + Policy Amendment Freeze',
                        'T7.3b VAL->CONF validation of frozen candidates',
                        'T7.4 F6 preregistered decomposition',
                        'T7.5 ADD policy counterfactual', 'T7.6 synthesis'],
        'baseline_t6': '69a5bfd',
        'planning_baseline': '40e6268',
        'policy_lock': ('T7 MUST NOT modify E0-E3 / C-states / operators / P1-P3; T7.0-T7.4 '
                        'operator source diff must stay empty; T7.5 counterfactual only; '
                        'T7A=timing only (P2_balanced fixed), sizing deferred to T7B.'),
        'segment_protocol': {
            't7_1': 'all segments, descriptive only, no candidate selection',
            't7_2': 'development only (discovery)',
            't7_3a': 'development only (discovery); output = frozen candidate list',
            'policy_amendment_freeze': 'contract amendment commit BEFORE any VAL/CONF validation product exists',
            't7_3b': 'validation then confirmation (validate frozen candidates; failures recorded NOT_VALIDATED, no DEV re-selection)',
            't7_4': 'all segments (independent preregistration, no policy derivation)',
            't7_5': 'development reported, validation+confirmation primary',
        },
        'anchors': {
            'R0': 'identical to frozen T6.2 recycling R0 definition (consecutive-REDUCE fold-forward); anchor set must equal T6.2 cycle set (G8)',
            'observation_horizon': 40,
            'primary_decision_checkpoints': [1, 2, 3, 5],
            'rule': 'trajectory information at R+10 and beyond is outcome/description only and may not enter primary ADD decision-rule derivation',
            'windows': {'W_fa': 10, 'W_fa_secondary': [5, 20], 'delay_primary_N': 3,
                        'delay_curve': [1, 2, 3, 5]},
        },
        'factlayer_isolation': {
            'tables': ['t7_0_path_fact.parquet (pure PIT daily facts)',
                       't7_0_anchor_features.parquet (decision-time trajectory features only)',
                       't7_0_outcomes.parquet (outcomes incl. true_recovery judgment)'],
            'rule': 'the features builder never imports/reads the outcomes table (dependency-graph scan in gate); outcome builder may read path_fact',
            'sector_sidecar': 't7_0_sector_sidecar.parquet — QUASI-PIT (2026-09-21 membership backfill), EXPLORATORY ONLY, physically separate file, forbidden in C/D policy families and in any primary claim',
        },
        'trajectory_features': {
            'variable_semantics': {
                'max_bounce_Rk': 'max close-to-close log bounce within R+1..R+k vs R0 close (close_adj)',
                'consec_up_days_Rk': 'consecutive ret_1d_log>0 days as of R+k',
                'vol_load@maxbounce_R5': 'volume_load_vs_prebreak on the max-bounce day within R+1..R+5 (T6 frozen volume semantics)',
                'turnover@maxbounce_R5': 'turnover_load_3d_mean on the same max-bounce day (T6.3 signature source)',
                'vol_decay_Rk': 'volume_load_vs_prebreak(R+k) / volume_load_vs_prebreak(R+1) (continuous, no internal threshold)',
                'consec_shrink_days_Rk': 'consecutive volume_load_vs_prebreak<1 days as of R+k',
                'turnover_level_Rk': 'turnover_load_3d_mean at R+k',
                'turnover_traj_slope': 'turnover_load_3d_mean(R+5) - turnover_load_3d_mean(R+1) (continuous)',
                'eff_pos_share_Rk': 'share of efficiency_signed_3>0 days within R+1..R+k',
                'dd_repair_ratio_Rk': 'as defined in definition registry',
                'ref20_repair_Rk': 'dist_ref20 at R+k',
                'new_high_after_R0_Rk': '1 if drawdown_from_peak_log==0 on any day in R+1..R+k (at prior peak)',
            },
            'decision_checkpoints': [1, 2, 3, 5],
            'threshold_free': 'continuous features carry no internal thresholds (0/1 literals exempt)',
        },
        'hotbounce_strata': {
            'dimensions': {
                'bounce': 'max_bounce_R5',
                'volume': 'vol_load@maxbounce_R5',
                'turnover': 'turnover@maxbounce_R5',
            },
            'clock': 'all three share the same decision clock: the max-bounce day within R+1..R+5',
            'bins': 'development-segment tertiles, frozen in this contract before any VAL/CONF application; no grid search',
        },
        'f6_taxonomy': {
            'classes': ['slow_persistent_deterioration', 'reduce_add_oscillation',
                        'hot_bounce_failure', 'sudden_break_no_signal', 'long_high_exposure_drift'],
            'mandatory_residual': 'F6p (unclassified share accepted at any level; no post-hoc residual splitting)',
            'lock': 'taxonomy frozen before reading any F6 outcome distribution (sha+time-order gate)',
        },
        'policy_families': {
            'A_current': 'frozen T5 ADD rule as-is (benchmark)',
            'B_delay': 'delay ADD by N=3 effective trading days (primary); N in {1,2,3,5} reported as curve',
            'C_repair_confirmation': 'derived policy: DEV-only discovery -> Policy Amendment Freeze -> VAL/CONF validation; FORBIDDEN to reference sector variables',
            'D_hotbounce_veto': 'veto/delay ADD when hot-bounce stratum (bounce x volume x turnover tertiles) hits the preregistered cell; FORBIDDEN to reference sector variables',
            'matched_diff_wording': ('paired counterfactual difference of complete policy paths '
                                     'within the same cycle — NOT a local treatment effect of a '
                                     'single ADD (exposure paths diverge after the first '
                                     'differing ADD decision)'),
        },
        'error_cost': {
            'false_add': registry['false_add'],
            'missed_recovery': registry['missed_recovery'],
            'secondary_windows': [5, 20],
        },
        'statistics_prereg': {
            'bootstrap_B': t6c['statistics_prereg']['bootstrap_B'],
            'bootstrap_seed': t6c['statistics_prereg']['bootstrap_seed'],
            'ci': 'percentile 2.5/97.5',
            'cluster_units': t6c['statistics_prereg']['cluster_units'],
            'holm': 'Holm within each preregistered family',
            'rng': 'SeedSequence substreams; each T7 stage registers its enums in its stage gate before first run',
            'paired_counterfactual': 'matched within-cycle diff (cluster {stock_code, T0_date})',
        },
        'claim_rules': {
            'enum': t6c['claim_registry_enum'],
            'association_not_prediction': 'separator claims must read "associated with subsequent path", never "predicts/identifies"',
            'policy_two_axis': 'policy claims must report both false-ADD axis and missed-recovery axis; single-axis statements forbidden',
            'derived_policy_label': 'C-family claims must carry "derived policy (DEV-only derivation, Policy Amendment Freeze <sha>)"',
            'sector_quasi_pit': 'sector claims forced EXPLORATORY with backfill-bias annotation; unavailability is not evidence of absence',
            'counterfactual_bound': 'T7.5 conclusions must carry the same-price-clock/same-cost qualifier',
        },
        'hard_gates': ['G-Policy Lock', 'G-No Threshold Search', 'G-No Future Feature',
                       'G-F6 Lock', 'G-Counterfactual Conservation',
                       'G-Policy Derivation Isolation'],
        'counterfactual_conservation': {
            'same': ['universe', 'T0', 'entry', 'price clock', 'transaction cost'],
            'only_difference': 'ADD trigger decision',
            'pre_add_bitwise': 'pre-ADD daily state sequences of all policy variants must be bitwise identical (divergence only after differing ADD decisions)',
            'policy_specific_outcome_clock_audit': ('False-ADD W10 runs from each policy\'s own '
                                                    'add day; Missed Recovery runs from the '
                                                    'cycle/opportunity clock; mixing them is a '
                                                    'gate failure'),
        },
        't6_contract_sha256': sha256_file(T6/'t6_contract.json'),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'t7_0_definition_registry.json').write_text(
        json.dumps(registry, ensure_ascii=False, indent=2))
    contract['definition_registry_sha256'] = sha256_file(
        OUT/'t7_0_definition_registry.json')
    T7.mkdir(parents=True, exist_ok=True)
    (T7/'t7_contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2))
    print('calibration:', calib_trace['diagnosis'])
    print('contract + definition registry written')


if __name__ == '__main__':
    main()
