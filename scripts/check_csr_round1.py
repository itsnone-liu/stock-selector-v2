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

# --- CSR-5 data feasibility (optional stage: present once directory exists) ---
f5p = R/'05_data_feasibility/CSR_5_DATA_FEASIBILITY.yaml'
if f5p.exists():
    f5 = yaml.safe_load(f5p.read_text())
    v = f5['verdicts']
    ids5 = [x['evidence_id'] for x in v]
    if len(ids5) != len(set(ids5)): errs.append('CSR-5 duplicate evidence_id')
    if set(ids5) != set(ids): errs.append('CSR-5 ids != CSR-4 candidate ids')
    RATING = {'OBTAINABLE', 'BROKEN_SERIES', 'UNAVAILABLE'}
    TRUST = {'official', 'thirdparty_free', 'thirdparty_paid', 'constructed', 'frozen_product'}
    for x in v:
        for f in ('rating', 'channel', 'historical_depth', 'coverage', 'cost', 'trust'):
            if not x.get(f): errs.append(f'CSR-5 {x["evidence_id"]} missing {f}')
        if x['rating'] not in RATING: errs.append(f'CSR-5 {x["evidence_id"]} bad rating')
        if x['trust'] not in TRUST: errs.append(f'CSR-5 {x["evidence_id"]} bad trust')
        for g in ('publication_delay', 'point_in_time', 'revision_risk', 'confidence'):
            if x.get(g) not in (None, ''):
                errs.append(f'CSR-5 {x["evidence_id"]} pre-fills CSR-6/9 field {g}')
    mkt05 = [x for x in v if x['evidence_id'] == 'E-MKT-05'][0]
    if mkt05['rating'] != 'BROKEN_SERIES':
        errs.append('E-MKT-05 must be BROKEN_SERIES (2024-08 disclosure regime break)')
    BCLS = {'EXISTING_ASSET_CONSTRUCTIBLE', 'NEW_EXTERNAL_CHANNEL', 'BROKEN_OR_STRUCTURAL_LIMIT'}
    bc = {}
    for x in v:
        if x.get('build_class') not in BCLS:
            errs.append(f'CSR-5 {x["evidence_id"]} bad build_class')
        else:
            bc[x['build_class']] = bc.get(x['build_class'], 0) + 1
    if bc != {'EXISTING_ASSET_CONSTRUCTIBLE': 9, 'NEW_EXTERNAL_CHANNEL': 15,
              'BROKEN_OR_STRUCTURAL_LIMIT': 1}:
        errs.append(f'CSR-5 build_class counts {bc} != 9/15/1')
    rb = ' '.join(mkt05.get('regime_breaks', []))
    for d_ in ('2016-12-05', '2024-08-19'):
        if d_ not in rb:
            errs.append(f'E-MKT-05 regime_breaks missing {d_}')
    if '2014-11-17' in rb:
        errs.append('E-MKT-05: 2014-11-17 is series_start, must not sit in regime_breaks')
    if '2014-11-17' not in str(mkt05.get('series_start', '')):
        errs.append('E-MKT-05 missing series_start 2014-11-17')
    env = str(f5.get('environment_finding', {}).get('installed_state', ''))
    if '未安装' in env:
        errs.append('CSR-5 installed_state stale (akshare/tushare now installed)')
    if '积分 0' not in env:
        errs.append('CSR-5 installed_state must state tushare credit=0 fact')
    off = [x for x in v if x['build_class'] == 'NEW_EXTERNAL_CHANNEL'
           and x['trust'] == 'official' and x['rating'] != 'BROKEN_SERIES']
    if len(off) != 12:
        errs.append(f'headline arithmetic: NEW_EXTERNAL∩official count {len(off)} != 12')
    for e in ('E-MKT-04', 'E-SEC-04'):
        x = [y for y in v if y['evidence_id'] == e][0]
        if x['build_class'] != 'NEW_EXTERNAL_CHANNEL' or 'reference' not in str(x.get('note', '')):
            errs.append(f'{e} must be NEW_EXTERNAL_CHANNEL with market-cap reference note')
    import re as _re
    if 'H0' in ''.join(f5.get('headline_findings', {}).values()) and '支持' in ''.join(f5.get('headline_findings', {}).values()):
        errs.append('CSR-5 must not judge hypotheses')

# --- CSR-6 PIT/availability (optional stage) ---
f6p = R/'06_pit_availability/CSR_6_PIT_AVAILABILITY.yaml'
if f6p.exists():
    f6 = yaml.safe_load(f6p.read_text())
    v6 = f6['verdicts']
    ids6 = [x['evidence_id'] for x in v6]
    if len(ids6) != len(set(ids6)): errs.append('CSR-6 duplicate evidence_id')
    if set(ids6) != set(ids): errs.append('CSR-6 ids != CSR-4 candidate ids')
    AV = {'A_DIRECT_PIT', 'B_DIRECT_DELAYED', 'C_RELIABLE_PROXY', 'D_WEAK_PROXY', 'E_UNAVAILABLE'}
    RT = {'REALTIME_T1', 'EVENT_ADVANCE', 'LAGGED_VERIFICATION', 'BACKTEST_ONLY'}
    for x in v6:
        for f in ('availability_rating', 'realtime', 'observation_date_rule',
                  'publication_date_rule', 'available_date_rule', 'latency',
                  'revision_risk', 'selection_coverage_note'):
            if not x.get(f): errs.append(f'CSR-6 {x["evidence_id"]} missing {f}')
        if x['availability_rating'] not in AV: errs.append(f'CSR-6 {x["evidence_id"]} bad rating')
        if x['realtime'] not in RT: errs.append(f'CSR-6 {x["evidence_id"]} bad realtime')
    r6 = {y['evidence_id']: y for y in v6}
    if r6['E-MKT-05']['availability_rating'] != 'D_WEAK_PROXY':
        errs.append('E-MKT-05 rating must be D_WEAK_PROXY (current regime)')
    if r6['E-MKT-05']['realtime'] != 'BACKTEST_ONLY':
        errs.append('E-MKT-05 realtime must be BACKTEST_ONLY')
    for e in ('E-STK-01', 'E-STK-02', 'E-STK-03'):
        if r6[e]['realtime'] != 'LAGGED_VERIFICATION':
            errs.append(f'{e} (ownership quarterly) must be LAGGED_VERIFICATION')
    for e in ('E-MKT-04', 'E-SEC-04'):
        if r6[e]['realtime'] != 'BACKTEST_ONLY':
            errs.append(f'{e} must be BACKTEST_ONLY until market-cap reference lands')
    if '两套字母必须严格区分' not in yaml.dump(f6.get('meta', {}), allow_unicode=True):
        errs.append('CSR-6 must declare evidence_level vs availability_rating distinction')
    if not f6.get('contract_items_for_ingestion'):
        errs.append('CSR-6 contract items missing')
    from collections import Counter as _C
    arc = _C(x['availability_rating'] for x in v6)

# --- CSR-7 case protocol (optional stage) ---
f7p = R/'07_case_protocol/CSR_7_CASE_PROTOCOL.yaml'
if f7p.exists():
    f7 = yaml.safe_load(f7p.read_text())
    dvd = f7.get('dual_view_discipline', {})
    for k in ('real_time_view', 'ex_post_view', 'legal_direction',
              'annotation_order', 'physical_separation'):
        if not dvd.get(k): errs.append(f'CSR-7 dual_view_discipline missing {k}')
    if 'rt_' not in str(dvd.get('physical_separation', '')) or 'xp_' not in str(dvd.get('physical_separation', '')):
        errs.append('CSR-7 physical_separation must declare rt_/xp_ prefixes')
    if 'LAGGED_VERIFICATION' not in str(dvd.get('real_time_view', {}).get('forbidden', '')):
        errs.append('CSR-7 rt view must forbid LAGGED_VERIFICATION evidence')
    if '倒灌' not in str(dvd.get('ex_post_view', {}).get('forbidden', '')):
        errs.append('CSR-7 xp view must declare no-reverse-contamination')
    if '先完成案例 real_time_view 再打开 ex_post_view' not in str(dvd.get('annotation_order', '')):
        errs.append('CSR-7 annotation order (rt before xp) must be enforced')
    bp = str(dvd.get('rt_blind_packet', ''))
    for kw in ('group', 'window_end', 'opaque_case_id', 'hidden_block', 'as-of-T'):
        if kw not in bp: errs.append(f'CSR-7 rt_blind_packet missing {kw}')
    xpv = str(dvd.get('ex_post_view', {}))
    if 'novel_transition' not in xpv or '白名单' not in xpv:
        errs.append('CSR-7 xp view must allow novel_transition (registered=reference set, not allow-list)')
    raw7 = f7p.read_text()
    if 'registered transitions 内' in raw7 or 'registered transitions）内' in raw7:
        errs.append('CSR-7 whole-file: no transition allow-list phrasing anywhere')
    ps = str(dvd.get('progressive_sealing', ''))
    for kw in ('packet(T)', 'sealed_at(T) < revealed_at(T+1)', '永久只读'):
        if kw not in ps: errs.append(f'CSR-7 progressive_sealing missing {kw}')
    g3 = str(f7.get('gates', {}).get('G-CS-3_no_reverse_contamination', ''))
    if 'sealed_at(T) < revealed_at(T+1)' not in g3:
        errs.append('G-CS-3 must check per-T sealing total order')
    hb2 = f7.get('case_sheet_schema', {}).get('hypothesis_block', {})
    if 'rt_observability' not in str(hb2.get('fields', '')) or 'xp_observability' not in str(hb2.get('fields', '')):
        errs.append('CSR-7 needs orthogonal observability fields (rt_/xp_)')
    if 'NOT_OBSERVED 档' not in str(hb2.get('scale', '')) and '≠ UNOBSERVABLE' not in str(hb2.get('scale', '')):
        errs.append('NOT_OBSERVED must be distinguished from UNOBSERVABLE in scale')
    pq2 = str(f7.get('analysis_plan', {}).get('primary_question', ''))
    if 'rt_observability = UNOBSERVABLE' not in pq2:
        errs.append('confusion matrix rt_unobservable must come from observability field')
    if 'agreement_mapping' not in pq2 or 'excluded_from_binary_agreement' not in pq2:
        errs.append('agreement mapping must be frozen inline (no deferred mapping)')
    ag = f7.get('case_selection', {}).get('anchor_generation', '')
    if isinstance(ag, str):
        ag = {'anchor_generation': ag}
    for kw in ('failure severity 最大', '段后 12 个月涨幅最高', '连续重叠 qualifying 窗口合并'):
        if kw not in str(f7.get('case_selection', {}).get('anchor_generation', '')):
            errs.append(f'G2/G4/G5 uniqueness rule missing: {kw}')
    g5c = str(f7.get('gates', {}).get('G-CS-5_annotation_consistency', ''))
    if 'xp 层第二标注者' not in g5c or 'rt / xp inter-rater' not in g5c:
        errs.append('G-CS-5 must extend to xp second annotation')
    groups = f7.get('case_selection', {}).get('groups', [])
    if len(groups) != 5 or not all(g.get('n') == 20 for g in groups):
        errs.append('CSR-7 must have 5 groups x 20 cases')
    gnames = [g['group'] for g in groups]
    if len(set(gnames)) != 5: errs.append('CSR-7 duplicate group names')
    if not all(g.get('rule') for g in groups):
        errs.append('CSR-7 every group needs a preregistered formula rule')
    tb = str(f7.get('case_selection', {}).get('tie_break', ''))
    if '20260925' not in tb:
        errs.append('CSR-7 tie_break seed must be preregistered')
    scale = str(f7.get('case_sheet_schema', {}).get('hypothesis_block', {}))
    for need in ('SUPPORTED_STRONG', 'SUPPORTED_PARTIAL', 'MIXED', 'NOT_OBSERVED', 'CONTRADICTED'):
        if need not in scale: errs.append(f'CSR-7 h-support scale missing {need}')
    if 'rt_h_support' not in scale or 'xp_h_support' not in scale:
        errs.append('CSR-7 hypothesis scoring must be rt/xp dual columns')
    la = str(f7.get('case_sheet_schema', {}).get('lifecycle_annotation', {}))
    if 'candidate_state' not in la or 'ONTOLOGY_ONLY' not in la:
        errs.append('CSR-7 lifecycle annotation must keep two-tier + D3 ONTOLOGY_ONLY')
    if '不进入 H 支持度' not in la:
        errs.append('D3 must be excluded from H-support and concordance stats')
    gates7 = set(f7.get('gates', {}))
    for g in ('G-CS-1_dual_view_separation', 'G-CS-2_selection_replayable',
              'G-CS-3_no_reverse_contamination', 'G-CS-4_group_balance',
              'G-CS-5_annotation_consistency'):
        if g not in gates7: errs.append(f'CSR-7 gate missing: {g}')
    ap = f7.get('analysis_plan', {})
    forb = str(ap.get('forbidden', ''))
    for kw in ('ML', 'return_optimization', 'threshold_search', 'policy_backtest'):
        if kw not in forb: errs.append(f'CSR-7 forbidden list missing {kw}')
    pq = str(ap.get('primary_question', ''))
    for kw in ('rt_candidate_positive', 'xp_confirmed_positive', 'xp_unobservable',
               'agreement_rate', 'conditional agreement', '全市场'):
        if kw not in pq: errs.append(f'CSR-7 confusion-matrix contract missing {kw}')
    if 'outcome-conditioned' not in pq:
        errs.append('CSR-7 must declare outcome-conditioned sampling interpretation limit')
    g5 = [g for g in groups if g['group'] == 'G5_sector_follower']
    if g5 and g5[0].get('role') != 'sector_follower_comparator':
        errs.append('G5 must be sector_follower_comparator (no preset latent-actor claim)')
    if '无 A5' in str(ap.get('secondary', '')) and '只能是' not in str(ap.get('secondary', '')):
        errs.append('G5 wording: 无 A5 may appear only as forbidden-preset declaration')
    cs = f7.get('case_selection', {})
    for k in ('anchor_generation', 'overlap_policy', 'stratified_redraw'):
        if not cs.get(k): errs.append(f'CSR-7 case_selection missing frozen {k}')
    if 'multi-group membership' not in str(cs.get('overlap_policy', '')):
        errs.append('CSR-7 overlap policy must declare multi-group membership handling')
    hb = str(f7.get('case_sheet_schema', {}).get('hypothesis_block', {}))
    if 'rt_h_support' not in hb or 'xp_h_support' not in hb or 'h_support=xp' in hb.replace('rt_h_support','').replace('xp_h_support',''):
        errs.append('CSR-7 hypothesis fields must be rt_/xp_ dual columns, no overriding field')
    idn = f7.get('case_sheet_schema', {}).get('identity', [])
    if 'opaque_case_id' not in idn or 'group' in idn or 'window_end' in idn:
        errs.append('CSR-7 rt-visible identity must hide group/window_end')
    if not f7.get('case_sheet_schema', {}).get('identity_hidden'):
        errs.append('CSR-7 needs identity_hidden block')
    rtc = _C(x['realtime'] for x in v6)
    if arc != _C({'A_DIRECT_PIT': 10, 'B_DIRECT_DELAYED': 3,
                  'C_RELIABLE_PROXY': 11, 'D_WEAK_PROXY': 1}):
        errs.append(f'CSR-6 rating counts drifted: {dict(arc)}')
    if rtc != _C({'REALTIME_T1': 15, 'EVENT_ADVANCE': 3,
                  'LAGGED_VERIFICATION': 3, 'BACKTEST_ONLY': 4}):
        errs.append(f'CSR-6 realtime counts drifted: {dict(rtc)}')
    stk10_6 = r6['E-STK-10']
    if stk10_6['availability_rating'] != 'C_RELIABLE_PROXY' or stk10_6['realtime'] != 'REALTIME_T1':
        errs.append('E-STK-10 must be C_RELIABLE_PROXY + REALTIME_T1 (proxy stays C however fast)')
    if '本地构造=代理性质' not in str(f6.get('meta', {}).get('two_scales_declaration', '')):
        errs.append('two-scales declaration must forbid proxy promoting to A/B by speed')
    raw6_hl = '\n'.join(str(x) for x in f6.get('headline_findings', {}).values())
    if '1~4' in raw6_hl:
        errs.append('CSR-6 headline stale delay wording (must be 15 working days ~ 4 months)')
    ROLE_STRUCT = {'E-MKT-06': ('REALTIME_T1', 'EVENT_ADVANCE'),
                   'E-STK-06': ('EVENT_ADVANCE', '事后确认'),
                   'E-STK-07': ('EVENT_ADVANCE', '事后确认')}
    for e, need in ROLE_STRUCT.items():
        comps = r6[e].get('realtime_components', [])
        if not comps or not all(
                c.get('component') and c.get('role') and c.get('latency') for c in comps):
            errs.append(f'{e} mixed-event evidence needs realtime_components contract')
        roles = ' | '.join(str(c['role']) for c in comps)
        for n in need:
            if n not in roles:
                errs.append(f'{e} realtime_components missing role structure: {n}')
        if 'E-STK-06' == e and '短期' not in roles:
            errs.append('E-STK-06 post-event role must be 短期事后确认 (2 trading days)')
        if 'E-STK-07' == e and '阶段性' not in roles:
            errs.append('E-STK-07 post-event role must be 阶段性事后确认 (monthly flow)')

if errs:
    print('FAIL'); [print(' -', e) for e in errs]; sys.exit(1)
print(f'PASS v2.5: 7 actors(6 fields) / 9 states+17 registered transitions+two-tier'
      f'+D3 ONTOLOGY_ONLY / 6 hypotheses(8 fields,gates 3-state no-checkmark)'
      f' / {len(cands)} evidence({LAYERS}) unique ids, 20-col coverage,'
      f' audit-order clean, E-STK-10=C'
      + ('' if not f5p.exists() else
         f' / CSR-5: 25 ids reconciled, build_class 9/15/1, series_start+2 breaks, official==12, trust+rating enums'
         + ('' if not f6p.exists() else
            f' / CSR-6: 25 ids, ratings ' + str(dict(arc)) + ', realtime ' + str(dict(rtc))
            + ('' if not f7p.exists() else
               ' / CSR-7: dual-view discipline, 5x20 cases, gates G-CS-1..5'))))
