#!/usr/bin/env python3
"""T7.4 F6-taxonomy FREEZE — writes the ratified taxonomy into
t7_contract.json. Reads NO F6 outcome distribution of any kind.

Ratified by user this session (design doc v2): ORDER D4->D1->D2->D3->D5->F6';
end_mark_loss + endpoint_status; D2 = strict event clock (>5 effective
observations after A0, actually observed); D3 DD interval in negative-log
terms; G34 component-provenance replay; F6' large is NOT failure.
"""
from __future__ import annotations
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import sha256_file  # noqa: E402

T7 = ROOT/'output/research/t7'


def main():
    contract = json.loads((T7/'t7_contract.json').read_text())
    assert 't7_4_f6_taxonomy' not in contract, 'already frozen'
    severe = 0.1053605156578263  # T6_FROZEN severe_dd_depth_log
    tax = {
        'freeze_kind': 'f6_taxonomy_freeze',
        'order': ['D4', 'D1', 'D2', 'D3', 'D5', "F6'"],
        'order_semantics': 'classification precedence, NOT a risk ranking',
        'common_fields': {
            'end_mark_loss': 'observed_endpoint_return < 0',
            'endpoint_status': ['terminal', 'censored'],
            'censored_rule': 'censored mark loss counts for D1/D3/D5 '
                             'eligibility but is reported separately '
                             '(completed vs censored panels)',
        },
        'classes': {
            'D4_sudden_break': {
                'tail_observations': 5,
                'single_day_ret_log_max': -0.07,
                'pre_break_dd_rule': 'episode max DD before the break day '
                                     'remains non-severe '
                                     '(dd_log > -%r)' % severe,
            },
            'D1_oscillation': {
                'cycle_count_min': 3,
                'requires': ['end_mark_loss'],
            },
            'D2_late_false_recovery': {
                'clock': 'same frozen false-recovery failure condition as '
                         'T6.3 F3; FIRST occurs at effective-observation '
                         'offset > 5 after A0; MUST be actually observed '
                         'within the episode horizon (censoring is not late '
                         'failure)',
                'f3_boundary': 'failure_offset <= 5 -> already F3 (T6.3 '
                               'frozen); failure_offset > 5 -> D2-eligible '
                               'within F6 input set; not observed -> not D2',
                'clock_variables': ['a0_day', 'trigger_day', 'effective '
                                                  'observation spacing '
                                                  '(T6.2 frozen columns)'],
            },
            'D3_slow_grind': {
                'span_effective_days_min': 60,
                'dd_interval_log': {
                    'lower_strict': -severe,
                    'upper_inclusive': math.log(0.95),
                },
                'reduce_count_max': 1,
                'requires': ['end_mark_loss'],
            },
            'D5_high_exposure_stagnation': {
                'exposure_occupancy_min': 0.80,
                'requires': ['no RECOVERED_ADD cycle', 'end_mark_loss'],
            },
            "F6'_mandatory_residual": {
                'note': 'large residual is NOT failure; GOOD-heavy F6\' may '
                        'show the existing failure taxonomy has no reason '
                        'to call these episodes failures. T7.4 success is '
                        'NOT measured by a low residual rate. No threshold '
                        'retuning after seeing the distribution.',
            },
        },
        'gate_additions': {
            'G34_component_provenance_replay': 'every condition variable '
            '(cycle count, endpoint return, exposure occupancy, pre-break '
            'DD, single-day return, D2 failure clock) independently '
            'replayed from frozen T6/T7 facts; runner-side ad-hoc '
            'recomputation of near-equivalent versions is forbidden',
        },
        'provenance': {
            'design_doc_sha256': sha256_file(
                ROOT/'docs/plans/T7_4_F6_TAXONOMY_DESIGN.md'),
            'design_commit': 'b76d653 (v1) + ratified v2 in freeze commit',
            'severe_source': 't6_contract preregistered_thresholds '
                             'severe_dd_depth_log',
            'ancestry_assertion': 'this taxonomy freeze precedes any F6 '
                                  'outcome distribution read / t7_4 product; '
                                  'verifiable by git history order',
        },
    }
    contract['t7_4_f6_taxonomy'] = tax
    (T7/'t7_contract.json').write_text(
        json.dumps(contract, ensure_ascii=False, indent=2))
    (T7/'t7_4_f6_taxonomy.json').write_text(
        json.dumps(tax, ensure_ascii=False, indent=2))
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                          capture_output=True, text=True,
                          check=True).stdout.strip()
    print('taxonomy frozen at', head)
    print('contract sha256 now:', sha256_file(T7/'t7_contract.json'))


if __name__ == '__main__':
    main()
