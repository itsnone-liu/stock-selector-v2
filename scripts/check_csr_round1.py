#!/usr/bin/env python3
"""CSR round-1 self-check: YAML parseable + cross-references complete."""
import json, sys
from pathlib import Path
import yaml

R = Path('output/research/csr')
errs = []
c0 = json.loads((R/'00_research_contract/csr_0_contract.json').read_text())
a1 = yaml.safe_load((R/'01_actor_ontology/CAPITAL_ACTOR_ONTOLOGY.yaml').read_text())
a2 = yaml.safe_load((R/'02_lifecycle_ontology/CAPITAL_LIFECYCLE_ONTOLOGY.yaml').read_text())
a3 = yaml.safe_load((R/'03_hypothesis_registry/CSR_3_HYPOTHESES.yaml').read_text())
a4 = yaml.safe_load((R/'04_evidence_map/CSR_4_EVIDENCE_MAP.yaml').read_text())

actors = {x['actor_id'] for x in a1['actors']}
assert len(actors) == 7 and actors == {f'A{i}' for i in range(1, 8)}
for x in a1['actors']:
    for f in ('scale', 'horizon', 'entry_constraint', 'exit_constraint',
              'objective', 'observable_footprint'):
        if not x.get(f): errs.append(f'actor {x["actor_id"]} missing {f}')

states = {x['id'] for x in a2['states']}
assert states == {f'D{i}' for i in range(0, 9)}
for s, t in a2['transitions']['allowed']:
    assert s in states and t in states, (s, t)

hyps = {h['id']: h for h in a3['hypotheses']}
assert set(hyps) == {f'H0{i}' for i in range(1, 7)}
for hid, h in hyps.items():
    for f in ('economic_mechanism', 'expected_observations', 'direct_evidence',
              'proxy_evidence', 'counter_evidence', 'alternative_explanations',
              'historical_test', 'pit_requirements'):
        if not h.get(f): errs.append(f'{hid} missing {f}')
    for ar in h['actor_refs']:
        if ar not in actors: errs.append(f'{hid} bad actor {ar}')
    for ls in h['lifecycle_states']:
        if ls not in states: errs.append(f'{hid} bad state {ls}')

cols = {c['name'] for c in a4['schema']['columns']}
need = {'evidence_id', 'actor_id', 'hypothesis_id', 'capital_layer',
        'evidence_name', 'economic_mechanism', 'evidence_level', 'data_source',
        'raw_field', 'frequency', 'publication_delay', 'historical_depth',
        'point_in_time', 'revision_risk', 'coverage', 'expected_direction',
        'counter_evidence', 'alternative_explanations', 'confidence', 'status'}
assert cols == need, cols ^ need
for e in a4['candidates']:
    for f in ('actor_id', 'hypothesis_id'):
        v = e[f]
        if v != 'MULTI':
            pool = actors if f == 'actor_id' else set(hyps)
            if v not in pool: errs.append(f'{e["evidence_id"]} bad {f}={v}')
    if e['evidence_level'] not in 'ABC': errs.append(f'{e["evidence_id"]} level')
    if e['capital_layer'] not in ('MARKET', 'SECTOR', 'STOCK', 'MARGINAL'):
        errs.append(f'{e["evidence_id"]} layer')
    if e['status'] != 'CANDIDATE': errs.append(f'{e["evidence_id"]} status')
    for f in ('publication_delay', 'point_in_time', 'revision_risk',
              'coverage', 'confidence'):
        if e.get(f) not in (None, ''):
            errs.append(f'{e["evidence_id"]} pre-filled {f} (violates audit order)')

if errs:
    print('FAIL'); [print(' -', e) for e in errs]; sys.exit(1)
n_ev = len(a4['candidates'])
print(f'PASS: 7 actors (6 fields each), 9 states + {len(a2["transitions"]["allowed"])} '
      f'transitions, 6 hypotheses (8 fields each), {n_ev} evidence candidates '
      f'(20-col schema, audit-order clean)')
