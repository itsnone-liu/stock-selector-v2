#!/usr/bin/env python3
"""CSR round-1 self-check (v2, post CSR-R1-AUDIT-FIX).

Structure checks + research-semantics checks:
  - YAML parseable, cross-references complete (actors/states/hypotheses)
  - evidence_id uniqueness, per-layer counts, key coverage vs schema
  - audit-order cleanliness: audit-owned fields never pre-filled
  - semantics: E-STK-10 stays C; two-tier confirmation present; no
    allow-list naming; D3 ONTOLOGY_ONLY; gate three-state, no checkmarks
"""
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

# --- CSR-1 actors ---
actors = {x['actor_id'] for x in a1['actors']}
assert actors == {f'A{i}' for i in range(1, 8)}
for x in a1['actors']:
    for f in ('scale', 'horizon', 'entry_constraint', 'exit_constraint',
              'objective', 'observable_footprint'):
        if not x.get(f): errs.append(f'actor {x["actor_id"]} missing {f}')

# --- CSR-2 lifecycle ---
states = {x['id'] for x in a2['states']}
assert states == {f'D{i}' for i in range(0, 9)}
if 'allow' in yaml.dump(a2['transitions']).lower().replace('allowed', ''):
    errs.append('transitions still named allow-list (semantics fix regressed)')
tr = a2['transitions'].get('registered_candidate_transitions')
if not tr or len(tr) != 17:
    errs.append('registered_candidate_transitions missing or != 17')
else:
    for s_, t in tr:
        if s_ not in states or t not in states: errs.append(f'bad transition {s_}->{t}')
sar = a2.get('state_assignment_rules', {})
tt = sar.get('two_tier_confirmation', {})
for k in ('candidate_state', 'actor_confirmed_state'):
    if k not in tt: errs.append(f'two-tier confirmation missing {k}')
d3 = [x for x in a2['states'] if x['id'] == 'D3'][0]
if 'ONTOLOGY_ONLY' not in str(d3.get('status', '')):
    errs.append('D3 not marked ONTOLOGY_ONLY/UNMODELED_STATE')

# --- CSR-3 hypotheses ---
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
if 'D3' in [ls for h in hyps.values() for ls in h['lifecycle_states']]:
    errs.append('some hypothesis claims D3 (unmodeled state) — forbidden pre-CSR-8')
gates = a3.get('gate_self_check', {})
GATE_STATES = {'DESIGN_PASS', 'AUDIT_PENDING', 'PASS'}
if not gates: errs.append('no gate_self_check')
for g, v in gates.items():
    if str(v).strip() not in GATE_STATES:
        errs.append(f'gate {g} not a three-state value: {v}')
if any('✓' in str(v) for v in gates.values()):
    errs.append('checkmarks remain in gate_self_check')

# --- CSR-4 evidence map ---
cols = {c['name'] for c in a4['schema']['columns']}
need = {'evidence_id', 'actor_id', 'hypothesis_id', 'capital_layer',
        'evidence_name', 'economic_mechanism', 'evidence_level', 'data_source',
        'raw_field', 'frequency', 'publication_delay', 'historical_depth',
        'point_in_time', 'revision_risk', 'coverage', 'expected_direction',
        'counter_evidence', 'alternative_explanations', 'confidence', 'status'}
assert cols == need, cols ^ need
AUDIT_OWNED = {'publication_delay', 'point_in_time', 'revision_risk',
               'coverage', 'confidence', 'historical_depth', 'raw_field'}
REQUIRED_NOW = need - AUDIT_OWNED
cands = a4['candidates']
ids = [e['evidence_id'] for e in cands]
if len(ids) != len(set(ids)): errs.append('duplicate evidence_id')
LAYERS = {'MARKET': 6, 'SECTOR': 4, 'STOCK': 10, 'MARGINAL': 5}
from collections import Counter
lc = Counter(e['capital_layer'] for e in cands)
if dict(lc) != LAYERS: errs.append(f'layer counts {dict(lc)} != {LAYERS}')
for e in cands:
    extra = set(e) - cols
    if extra: errs.append(f'{e["evidence_id"]} unknown keys {extra}')
    missing = REQUIRED_NOW - set(e)
    if missing: errs.append(f'{e["evidence_id"]} missing required {missing}')
    for f in AUDIT_OWNED:
        if e.get(f) not in (None, ''):
            errs.append(f'{e["evidence_id"]} pre-filled {f} (violates audit order)')
    if e['evidence_level'] not in {'A', 'B', 'C'}:
        errs.append(f'{e["evidence_id"]} bad evidence_level')
    if e['capital_layer'] not in LAYERS:
        errs.append(f'{e["evidence_id"]} bad layer')
    if e['status'] != 'CANDIDATE': errs.append(f'{e["evidence_id"]} status')
    v = e['actor_id']
    if v != 'MULTI' and v not in actors: errs.append(f'{e["evidence_id"]} bad actor')
    if v == 'MULTI' and not str(e.get('alternative_explanations', '')):
        errs.append(f'{e["evidence_id"]} MULTI without alternative_explanations')
    if e['hypothesis_id'] not in hyps: errs.append(f'{e["evidence_id"]} bad hyp')
stk10 = [e for e in cands if e['evidence_id'] == 'E-STK-10'][0]
if stk10['evidence_level'] != 'C':
    errs.append('E-STK-10 not C (constructed proxy must stay C)')
stk05 = [e for e in cands if e['evidence_id'] == 'E-STK-05'][0]
if stk05['actor_id'] != 'MULTI':
    errs.append('E-STK-05 actor_id must be MULTI (seat identity is evidence, not actor)')
all_text = (R/'01_actor_ontology/CAPITAL_ACTOR_ONTOLOGY.yaml').read_text() \
    + (R/'03_hypothesis_registry/CSR_3_HYPOTHESES.yaml').read_text() \
    + (R/'04_evidence_map/CSR_4_EVIDENCE_MAP.yaml').read_text()
if '散户端口径' in all_text:
    errs.append('residual 融资余额散户端口径 wording (margin attribution regression)')

if errs:
    print('FAIL'); [print(' -', e) for e in errs]; sys.exit(1)
print(f'PASS v2: 7 actors(6 fields) / 9 states+17 registered transitions+two-tier'
      f'+D3 ONTOLOGY_ONLY / 6 hypotheses(8 fields,gates 3-state no-checkmark)'
      f' / {len(cands)} evidence({LAYERS}) unique ids, 20-col coverage,'
      f' audit-order clean, E-STK-10=C')
