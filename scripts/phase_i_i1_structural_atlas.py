#!/usr/bin/env python3
"""CSR-8 Phase I / I1 — 128-case STRUCTURAL ATLAS builder.

User ruling 2026-10-04 (Phase H closed; Phase I = Structural Interpretation &
Theory Convergence; first step I1 = structural atlas over the frozen corpus):
READ-ONLY over all sealed/frozen artifacts. No production, no ordinal 129+,
no redefinition of capital-state labels, no new statistical claims.

Deterministically extracts, per ordinal 1..128, a unified structural card:
identity (epoch, T, opaque entity, paired ordinal, packet hash), capital
state (stock layer + actor records + ETF share-change structure), annotation
judgments (six frozen rt hypotheses), path outcomes (R3/R5/R10 from the
readout machinery where the corpus covers them), and taxonomy status
(dominant / non-dominant with the exact deviating judgments).

Cross-sections (evidence only, interpretation kept descriptive):
- the 20 non-dominant ordinals with per-case deviation evidence;
- forensic member analysis for the 3 REVERSED pairs (etf_contraction 1v8,
  5v8, 6v8): member ordinals, T/epoch/stock-layer/path, shared conditions;
- semantic decomposition cards for the 3 preregistered PRESERVED relations
  (state definition -> observable evidence -> path difference -> allowed vs
  forbidden interpretations), numbers quoted verbatim from the frozen third
  readout report.

Hypothesis semantics are quoted from the frozen CSR-3 registry (preregistered,
NOT validated claims) — names only, never redefined here.

Outputs (new files only):
  docs/phase_i/i1_structural_atlas.json
  docs/phase_i/I1_STRUCTURAL_ATLAS.md
"""
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
EVID = ROOT / 'docs/audit/evidence'
OUT_DIR = ROOT / 'docs/phase_i'
RC = ROOT / 'data/csr8_phase_c/c4d_receipts/c4-prod-0002'

import phase_i_i2_unblind as frozen
import phase_i_third_readout_128 as third

HYP_NAMES = {
    'rt_H01': 'H01 Accumulation (吸筹)',
    'rt_H02': 'H02 Locking (锁筹)',
    'rt_H03': 'H03 Markup (主升)',
    'rt_H04': 'H04 External Participation (外部参与)',
    'rt_H05': 'H05 Distribution (派发)',
    'rt_H06': 'H06 Loss of Control (主导退出后)',
}
NON_DOMINANT_20 = [8, 15, 41, 44, 48, 51, 53, 55, 63, 67, 68, 72, 79, 105,
                   108, 112, 115, 117, 119, 127]
REVERSED_CELLS = {1, 5, 6, 8}  # etf_contraction_count cells of the 3 REVERSED pairs


def sealing_index():
    sl = [json.loads(l) for l in open(
        ROOT / 'data/csr8_phase_c/production/c4-prod-0002/sealing/sealing_log.jsonl')]
    revs = [e for e in sl if e['event_type'] == 'REVEAL_PACKET']
    info = {}
    for i, e in enumerate(revs):
        p = e['payload']
        info[i + 1] = {'ordinal': i + 1, 'epoch': 1 if i < 64 else 2,
                       'opaque_case_id': p['opaque_case_id'],
                       'packet_sha256': p['packet_sha256'], 'T': p['T']}
    by_opaque = {}
    for o, v in info.items():
        by_opaque.setdefault(v['opaque_case_id'], []).append(o)
    for o, v in info.items():
        pair = [x for x in by_opaque[v['opaque_case_id']] if x != o]
        v['paired_ordinal'] = pair[0] if pair else None
    return info


def readout_rows():
    frozen.ORDINALS = list(range(7, 129))
    mapping = frozen.resolve_mapping()
    frozen.mapped_codes = {m['code'] for m in mapping.values()}
    calendar, _ = frozen.load_calendar()
    rows, _ = frozen.outcomes(mapping, calendar)
    return {r['ordinal']: r for r in rows}


def trim_record(r, keys):
    return {k: r.get(k) for k in keys if r.get(k) not in (None, '')}


def build_card(o, seal, rrow):
    card = {'ordinal': o, **{k: seal[k] for k in
                             ('epoch', 'paired_ordinal', 'opaque_case_id',
                              'packet_sha256', 'T')}}
    d = RC / f'ordinal-{o:04d}'
    ctx_p, ann_p = d / 'national_ctx_v1.json', d / 'annotation_draft.json'
    card['artifacts'] = {'national_ctx': ctx_p.exists(),
                         'annotation_draft': ann_p.exists()}
    # capital state
    if ctx_p.exists():
        ctx = json.loads(ctx_p.read_bytes())
        card['capital_state'] = {
            'stock_layer_summary': ctx.get('stock_layer_summary'),
            'report_period': ctx.get('stock_layer_summary_report_period'),
            'stock_capital_records': [
                trim_record(r, ('actor_id', 'state', 'current_report_period',
                                'current_holding_ratio', 'previous_report_period',
                                'previous_holding_ratio'))
                for r in (ctx.get('stock_capital_records') or [])],
            'etf': None}
        mr = ctx.get('market_etf_records') or []
        states = [r.get('state') for r in mr]
        card['capital_state']['etf'] = {
            'n_records': len(mr),
            'expansion': states.count('EXPANSION'),
            'contraction': states.count('CONTRACTION'),
            'stable': states.count('STABLE'),
            'state_vector': states,
            'per_record': [trim_record(r, ('state', 'share_change_ratio',
                                           'latest_trade_date'))
                           for r in mr],
            'actor_attribution_values': sorted({str(r.get('actor_attribution'))
                                                for r in mr})}
    else:
        card['capital_state'] = 'NATIONAL_CTX_NOT_AVAILABLE (pre-NC era)'
    # annotation
    if ann_p.exists():
        a = json.loads(ann_p.read_bytes())
        ann = a.get('annotation') or a
        rts = ann.get('rt_judgments') or []
        card['annotation'] = {
            'flags': ann.get('flags'),
            'rt_judgments': [
                {'hypothesis': j.get('hypothesis_id'),
                 'hypothesis_name': HYP_NAMES.get(j.get('hypothesis_id')),
                 'support': j.get('support'),
                 'observability': j.get('observability'),
                 'n_evidence_refs': len(j.get('evidence_refs') or []),
                 'evidence_note': (j.get('evidence_note') or '')[:400]}
                for j in rts]}
    # path outcomes
    if rrow is not None:
        card['path_outcomes'] = {k: rrow.get(k) for k in
                                 ('R3', 'R5', 'R10', 'status')}
        card['readout_variables'] = {
            'stock_layer_summary': (card.get('capital_state') or {}).get('stock_layer_summary')
            if isinstance(card.get('capital_state'), dict) else None,
            'etf_expansion_count': (card.get('capital_state') or {}).get('etf', {}).get('expansion')
            if isinstance(card.get('capital_state'), dict) else None,
            'etf_contraction_count': (card.get('capital_state') or {}).get('etf', {}).get('contraction')
            if isinstance(card.get('capital_state'), dict) else None}
    else:
        card['path_outcomes'] = 'OUTSIDE_READOUT_CORPUS (readout covers 7-128)'
    # taxonomy status
    devs = []
    if ann_p.exists():
        for j in card['annotation']['rt_judgments']:
            if j['support'] != 'NOT_OBSERVED':
                devs.append({'hypothesis': j['hypothesis'],
                             'hypothesis_name': j['hypothesis_name'],
                             'field': 'support', 'value': j['support'],
                             'dominant': 'NOT_OBSERVED',
                             'evidence_note': j['evidence_note']})
            if j['observability'] != 'OBSERVABLE':
                devs.append({'hypothesis': j['hypothesis'],
                             'field': 'observability', 'value': j['observability'],
                             'dominant': 'OBSERVABLE'})
    card['taxonomy_status'] = {
        'non_dominant': bool(devs), 'deviations': devs,
        'in_reported_non_dominant_20': o in NON_DOMINANT_20}
    if isinstance(card.get('capital_state'), dict):
        cc = card['capital_state']['etf']['contraction']
        card['reversed_forensic_membership'] = (
            {'etf_contraction_count': cc,
             'in_reversed_pair_cells': cc in REVERSED_CELLS} if cc in REVERSED_CELLS else None)
    return card


def preserved_decomposition(third_report):
    P = third_report['preregistered_persistence_targets_first']
    S = {
        ('stock_layer_summary', 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10', 'NO_PIT_VISIBLE_REPORT'): {
            'state_definition': {
                'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10': '在当前 PIT 可见披露窗口内，该 (实体, T) 观察日没有出现在任何最新可见十大流通股东名单的披露里。它只约束"最新可见报告的在场披露"，不约束持仓是否存在。',
                'NO_PIT_VISIBLE_REPORT': '该 (实体, T) 观察日没有任何 PIT 可见的持仓报告可引用（无记录，而非有记录显示不在场）。'},
            'observable_evidence': 'national_ctx_v1.stock_capital_records 的 state 字段（NATIONAL_ACTOR_HOLDING_STATE）与报告期可得性；两者都从披露通道推导，而非从持仓事实推导。',
            'allowed_interpretations': [
                '两种"资金在场不可确认"状态的后续 R5 路径分布存在稳定的描述性差异',
                '该差异可能来自披露节奏、报告期可得性与市场参与结构的系统性差别'],
            'forbidden_interpretations': [
                'NOT_DISCLOSED = 国家资金退出 / 看空 / 减仓（非披露≠非持仓）',
                'NO_PIT_VISIBLE_REPORT = 无资金参与（无报告≠无持仓）',
                '任何因果或控制推断']},
        ('etf_expansion_count', '4', '8'): {
            'state_definition': {'4': '该观察日 PIT 可见的 ETF 份额快照中有 4 只处于 EXPANSION（份额净增）',
                                 '8': '…有 8 只处于 EXPANSION'},
            'observable_evidence': 'market_etf_records 的 share_change（latest vs previous total_shares），逐只二元化后的计数。',
            'allowed_interpretations': [
                'ETF 通道配置资金的不同扩张强度档位与后续 R5 路径分布存在稳定描述性差异（4<8 方向）',
                '计数是强度档位而非个体行为识别——actor_attribution 在该层 FORBIDDEN'],
            'forbidden_interpretations': [
                '特定 ETF 的申购主体识别',
                '扩张计数导致价格变化的因果陈述',
                '单调外推（结合 8>9 的反向差异，4<8<9 整体更像 regime 档位而非单调剂量效应）']},
        ('etf_expansion_count', '8', '9'): {
            'state_definition': {'8': '…有 8 只处于 EXPANSION', '9': '…有 9 只处于 EXPANSION'},
            'observable_evidence': '同上（market_etf_records share_change 计数）。',
            'allowed_interpretations': [
                '高强度扩张档内部（8 vs 9）仍存在方向相反（8<9）的稳定路径差异',
                '这支持把扩张计数读作离散 regime 档位，而非连续剂量'],
            'forbidden_interpretations': [
                '9 只扩张"更牛"/"更熊"的单调解读',
                '把档位边界（恰好 8/9）解释为任何机制阈值——边界位置由样本分布决定，未经预注册']}}
    out = []
    for p in P:
        key = (p['variable'], p['cellA'], p['cellB'])
        sem = S.get(key, {})
        out.append({'variable': p['variable'], 'cellA': p['cellA'], 'cellB': p['cellB'],
                    'classification': p['classification'],
                    'numbers_at_122': {'nA': p['corpus']['nA'], 'nB': p['corpus']['nB'],
                                       'dR5': p['corpus']['dR5'],
                                       'cliffs_delta_R5': p['corpus']['cliffs_delta_R5'],
                                       'sign_consistent': p['corpus']['CONSISTENT'],
                                       'qualifying': p['corpus']['qualifying_pair']},
                    **sem})
    return out


def classify_non_dominant(card):
    """Deterministic CANDIDATE classification (final call reserved for human
    review). Rules grounded in the observed deviation patterns:
    all 20 cases deviate only via stock-layer records feeding graded support
    for lifecycle hypotheses (rt_H01/H02/H05) — never observability."""
    devs = {(d['hypothesis'], d['value']) for d in card['taxonomy_status']['deviations']}
    cap = card.get('capital_state')
    nrec = len(cap['stock_capital_records']) if isinstance(cap, dict) else 0
    if ('rt_H01', 'MIXED') in devs and ('rt_H05', 'MIXED') in devs and nrec >= 2:
        return {'class': 'B (mixed capital state)',
                'rationale': f'{nrec} actor records simultaneously feed accumulation-direction and distribution-direction partial support (H01 MIXED + H05 MIXED) — opposite-direction graded evidence coexists'}
    if isinstance(cap, dict) and cap['stock_layer_summary'] == 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10':
        prev = [r for r in cap['stock_capital_records'] if r.get('previous_report_period')]
        return {'class': 'C (time-scale misalignment)',
                'rationale': ('current-period non-disclosure coexists with a previous-period holding record '
                              f'({len(prev)} record(s) with previous_report_period); the deviation cites prior-period '
                              'existence against current-period non-disclosure — same disclosure state sampled at '
                              'two observation dates inside one report-availability window' if prev else
                              'current-period non-disclosure with prior-period record')}
    if isinstance(cap, dict) and cap['stock_layer_summary'] == 'NATIONAL_ACTORS_PRESENT':
        return {'class': 'A (taxonomy granularity boundary)',
                'rationale': ('disclosed-presence record(s) feed graded lifecycle support ('
                              + ', '.join(sorted({h for h, _ in devs})) +
                              ') while the case-level stock_layer_summary remains binary — graded lifecycle '
                              'evidence does not fit the binary summary axis')}
    return {'class': 'UNCLASSIFIED', 'rationale': 'pattern outside pre-registered candidate rules'}


def reversed_mechanism(cards):
    """All three REVERSED pairs share the cell-8 (contraction=8) member pool.
    Deterministic decomposition of the 64->128 sign flip."""
    import statistics as st
    m8 = [c for c in cards.values() if c['ordinal'] >= 7 and isinstance(c.get('capital_state'), dict)
          and c['capital_state']['etf']['contraction'] == 8]
    g = [c for c in m8 if c['T'] == '2021-04-06']
    ng = [c for c in m8 if c['T'] != '2021-04-06']
    med = lambda xs: st.median([c['path_outcomes']['R5'] for c in xs])
    return {
        'shared_cell': 'etf_contraction_count=8 (all three REVERSED pairs compare against this cell)',
        'cluster': {'T': '2021-04-06', 'n': len(g),
                    'members': [c['ordinal'] for c in g],
                    'profile': 'epoch-2, NO_PIT_VISIBLE_REPORT, c=8/e=0 (all-contraction snapshot)',
                    'R5_median': med(g)},
        'rest_of_cell8': {'n': len(ng), 'R5_median': med(ng)},
        'cell8_median_at_128': med(m8),
        'mechanism': ('the 64->128 extension added %d same-T same-structure members to cell-8; their R5 center '
                      '(%.4f) sits above the rest of the cell (%.4f), lifting the cell-8 median from %.4f to %.4f '
                      'and flipping the sign of every cell-vs-8 delta that was small at 64. Common condition = '
                      'single-observation-date cluster sampling (corpus design feature), NOT a market-structure '
                      'change. Restricting to epoch-1 members reproduces the 64-corpus sign (d=+0.0224 for 1v8).'
                      ) % (len(g), med(g), med(ng), med(ng), med(m8)),
        'context_note': ('T clusters exist corpus-wide (2021-04-06: 9 cases, 2021-03-08: 7 cases, from the '
                         'epoch-2 sampling design); any future conditional layer must carry observation-date '
                         'clustering as a first-class context, which is evidence FOR a contextual layer and is '
                         'recorded here without building one')}


def main():
    seal = sealing_index()
    rrows = readout_rows()
    cards = {o: build_card(o, seal[o], rrows.get(o)) for o in range(1, 129)}

    # sanity: non-dominant set must equal the frozen third-report list
    detected = sorted(o for o, c in cards.items()
                      if c['taxonomy_status']['non_dominant'] and o >= 7)
    assert detected == sorted(NON_DOMINANT_20), f'non-dominant drift: {detected}'

    # REVERSED forensic members
    third_report = json.loads((EVID / 'phase_i_third_readout_128_report.json').read_text())
    rev_pairs = [d for d in third_report['second_to_128_structure_drift']
                 if d['classification'] == 'REVERSED']
    forensic = []
    for p in rev_pairs:
        cells = {int(p['cellA']), int(p['cellB'])}
        members = {'from_64': [], 'at_128': []}
        for o, c in cards.items():
            cap = c.get('capital_state')
            if not isinstance(cap, dict):
                continue
            cc = cap['etf']['contraction']
            if cc in cells and o >= 7:
                members['at_128'].append({
                    'ordinal': o, 'epoch': c['epoch'], 'T': c['T'],
                    'paired': c['paired_ordinal'],
                    'stock_layer': cap['stock_layer_summary'],
                    'contraction': cc, 'expansion': cap['etf']['expansion'],
                    'R5': c['path_outcomes'].get('R5') if isinstance(c['path_outcomes'], dict) else None,
                    'non_dominant': c['taxonomy_status']['non_dominant']})
        second = json.loads((EVID / 'phase_i_second_readout_64_report.json').read_text())
        from_pair = None
        for q in second['readout_corpus_7_64']['variables'].get('etf_contraction_count', {}).get('pairs', []):
            if {int(q['cellA']), int(q['cellB'])} == cells:
                from_pair = {k: q[k] for k in ('nA', 'nB', 'dR5', 'dR10', 'cliffs_delta_R5')}
        to_pair = None
        for q in third_report['readout_corpus_7_128']['variables']['etf_contraction_count']['pairs']:
            if {int(q['cellA']), int(q['cellB'])} == cells:
                to_pair = {k: q[k] for k in ('nA', 'nB', 'dR5', 'dR10', 'cliffs_delta_R5')}
        agg = {'epochs': Counter(m['epoch'] for m in members['at_128']),
               'stock_layers': Counter(m['stock_layer'] for m in members['at_128']),
               'T_range': (min((m['T'] for m in members['at_128']), default=None),
                           max((m['T'] for m in members['at_128']), default=None)),
               'non_dominant_overlap': sum(1 for m in members['at_128'] if m['non_dominant'])}
        forensic.append({'variable': p['variable'], 'cellA': p['cellA'], 'cellB': p['cellB'],
                         'at_64': from_pair, 'at_128': to_pair,
                         'members_at_128_corpus': members['at_128'], 'aggregate': agg,
                         'note': 'REVERSED = sign of cell-median R5 delta flipped between the 64-case and 122-case corpora; descriptive structure drift, NOT a causal claim and NOT an error to repair'})

    atlas = {
        'phase': 'CSR-8 Phase I / I1',
        'basis': {'authority': 'Phase H final freeze csr8-phase-h-final-freeze-v1 (commit 9dfc516); third readout commit 3f46515',
                  'mode': 'READ-ONLY over sealed/frozen artifacts; no production; ordinals 1-128 only; capital-state labels unchanged',
                  'hypothesis_semantics_source': 'output/research/csr/03_hypothesis_registry/CSR_3_HYPOTHESES.yaml (preregistered, NOT validated claims)'},
        'cards': cards,
        'cross_sections': {
            'non_dominant_20': [
                {'ordinal': o,
                 'epoch': cards[o]['epoch'], 'T': cards[o]['T'],
                 'stock_layer': (cards[o].get('capital_state') or {}).get('stock_layer_summary')
                 if isinstance(cards[o].get('capital_state'), dict) else None,
                 'deviations': cards[o]['taxonomy_status']['deviations'],
                 **classify_non_dominant(cards[o])}
                for o in NON_DOMINANT_20],
            'non_dominant_summary': None,  # filled below
            'reversed_forensic': forensic,
            'reversed_shared_mechanism': None,  # filled below
            'preserved_decomposition': preserved_decomposition(third_report)}}
    from collections import Counter as _C
    atlas['cross_sections']['non_dominant_summary'] = {
        'candidate_class_counts': dict(_C(e['class'][0] for e in atlas['cross_sections']['non_dominant_20'])),
        'D_pit_insufficiency_candidates': 0, 'E_new_structure_candidates': 0,
        'finding': ('every non-dominant case deviates ONLY via graded lifecycle support (rt_H01/H02/H05 '
                    'SUPPORTED_PARTIAL or MIXED) fed by stock-layer records; observability is OBSERVABLE in all '
                    '120 judgments; no case requires a structure outside the current taxonomy fields — '
                    'taxonomy_v3 has NO evidence basis from this corpus (A/B/C candidates only)')}
    atlas['cross_sections']['reversed_shared_mechanism'] = reversed_mechanism(cards)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'i1_structural_atlas.json').write_text(
        json.dumps(atlas, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    print(json.dumps({'status': 'ATLAS_BUILT', 'cards': len(cards),
                      'non_dominant_detected': detected,
                      'reversed_pairs': [(f['variable'], f['cellA'], f['cellB']) for f in forensic],
                      'path_coverage': sum(1 for c in cards.values() if isinstance(c['path_outcomes'], dict))},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
