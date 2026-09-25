#!/usr/bin/env python3
"""T7 Policy Amendment FREEZE — writes the preregistered amendment block
into t7_contract.json. No VAL/CONF computation of any kind happens here.

User-ratified decisions (this session, on top of frozen T7.2 c2795d7 and
design doc 1212c65):
  - A stays the frozen REFERENCE policy (no DEV-discovered replacement)
  - C1/q1 = the single PRIMARY amendment candidate (risk-reduction
    confirmation semantics)
  - C2/q2 = frozen SECONDARY sensitivity only; can NEVER be promoted to
    primary after seeing VAL
  - C expression adopted; D1 not registered (mathematically equivalent ADD
    set -> would create pseudo multiple comparisons)
  - D family EMPTY (DEV evidence points opposite to the original hot-bounce
    veto direction; an empty family is itself a research result)
  - NO scalar B+C utility weighting is frozen; evaluation stays on the 2D
    frontier (false-ADD risk reduction x recovery upside)
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import sha256_file  # noqa: E402

T7 = ROOT/'output/research/t7'
DISC = T7/'02_separator_discovery'


def main():
    bins = json.loads((DISC/'t7_2_bins.json').read_text())
    q1 = bins['max_bounce_R5']['q1']
    q2 = bins['max_bounce_R5']['q2']
    assert abs(q1 - (-0.018751312624643024)) < 1e-15
    assert abs(q2 - 0.01801067333046413) < 1e-15

    contract = json.loads((T7/'t7_contract.json').read_text())
    assert 'policy_amendments' not in contract, 'already frozen'

    t22_base = subprocess.run(
        ['git', 'rev-parse', 'c2795d7'], cwd=ROOT, capture_output=True,
        text=True, check=True).stdout.strip()

    block = {
        'freeze_kind': 'policy_amendment_freeze',
        'reference_policy': {
            'name': 'A',
            'role': 'frozen reference (current policy); NOT replaced by any '
                    'DEV-discovered rule',
        },
        'primary_amendment_candidate': {
            'name': 'C1',
            'feature': 'max_bounce_R5',
            'threshold': q1,
            'threshold_source': 'DEV tertile q1 (t7_2_bins.json, frozen at c2795d7)',
            'decision_clock': 'R+5 (max_bounce_R5 fully observable only at R+5)',
            'rule': 'After R0, no immediate re-ADD. Observe through R+5. If '
                    'max_bounce_R5 > threshold -> ADD eligible. If '
                    'max_bounce_R5 <= threshold -> no further ADD this cycle.',
            'interpretation': 'risk-reduction amendment candidate; NOT an '
                              'expected-return enhancement, NOT a new primary '
                              'winner',
        },
        'secondary_sensitivity': {
            'name': 'C2',
            'feature': 'max_bounce_R5',
            'threshold': q2,
            'threshold_source': 'DEV tertile q2 (same frozen bins)',
            'decision_clock': 'R+5',
            'rule': 'same semantics as C1 with threshold q2',
            'constraint': 'C2 may NEVER be promoted to primary after seeing '
                          'VAL/CONF results; sensitivity reporting only',
        },
        'd_family': {
            'name': 'D',
            'status': 'EMPTY',
            'reason': 'DEV discovery shows higher bounce -> LOWER FR rate '
                      '(hi tertile FR 32.3% vs lo 62.1%): the original '
                      'hot-bounce veto direction is unsupported. Registering '
                      'an evidence-free rule is forbidden; an empty family is '
                      'itself a research result.',
        },
        'utility': {
            'scalar_weighting_frozen': False,
            'evaluation': '2D frontier: x = false-ADD risk reduction, '
                          'y = recovery upside captured/missed; secondary '
                          'panels: capital efficiency / drawdown / exposure. '
                          'The A-vs-C1 trade-off is reported, not forced into '
                          'a single winner.',
        },
        'provenance': {
            't7_2_bins_sha256': sha256_file(DISC/'t7_2_bins.json'),
            'design_doc_sha256': sha256_file(
                ROOT/'docs/plans/T7_POLICY_AMENDMENT_DESIGN.md'),
            't7_2_frozen_commit': t22_base,
            'design_doc_commit': '1212c65',
            'ancestry_assertion': 'this Freeze precedes any VAL/CONF policy '
                                  'evaluation artifact; verified by git '
                                  'history order',
        },
    }
    contract['policy_amendments'] = block
    (T7/'t7_contract.json').write_text(
        json.dumps(contract, ensure_ascii=False, indent=2))
    (T7/'t7_policy_amendment_freeze.json').write_text(
        json.dumps(block, ensure_ascii=False, indent=2))
    print('frozen. C1 threshold', q1, '| C2 threshold', q2)
    print('contract sha256 now:', sha256_file(T7/'t7_contract.json'))


if __name__ == '__main__':
    main()
