#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NC-ERRATUM-1.1 support-contract test (H2-CANARY-FIX1 item 4 + 1.1).

Proves, on blinded outputs only (enums/counts/hashes — never identity):

1. v1e1 equivalence: for ordinals 1-4 the erratum-1.1 builder emits
   record arrays identical to the frozen v1 builder; the summary table
   is unchanged for the real campaign candidates.
2. DISAPPEARANCE regression (NC-ERRATUM-1.1 core): full-path fixture —
   previous complete report discloses a tracked actor, LATEST complete
   report discloses none.  Must yield
   stock_layer_summary == NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10
   (explicitly != NATIONAL_ACTORS_PRESENT), a stock record for the
   actor, and record state == NOT_DISCLOSED_IN_TOP10.
3. SOURCE_UNAVAILABLE full-path fixture: latest cell not
   SUCCESS_NONEMPTY -> summary SOURCE_UNAVAILABLE + single S-000000
   UNKNOWN record.
4. POSITIVE stock>0 case (real ordinal-3 data): cross-hypothesis
   support-map reuse passes the per-hypothesis validator.
5. Negative control: within-hypothesis duplicate fails closed.
6. Annotation review envelope reference values.

Writes docs/audit/evidence/support_contract_test_report_v2_1.json
(v2 report of erratum 1 stays byte-frozen as history).
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_national_capital_context_v1e1 as v1e1_mod  # noqa: E402
from csr8_phase_h_review_envelope import (  # noqa: E402
    annotation_envelope_sha256, ANNOTATION_REVIEW_ENVELOPE_VERSION)

REPORT = (ROOT / 'docs/audit/evidence'
          / 'support_contract_test_report_v2_1.json')
ORDINAL4_ENVELOPE = ('233c0900c4dae5784893c5d3dcaa471ff99edfbaa109b7'
                     '3ca369f354a370f1f5')


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run_builder(script, ordinal, out):
    subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / script),
         '--ordinal', str(ordinal), '--out', str(out)],
        check=True, capture_output=True, text=True, cwd=str(ROOT))


def validator(map_path, sidecar_path, packet_path):
    return subprocess.run(
        [sys.executable,
         str(ROOT / 'scripts/validate_context_support_map.py'),
         str(map_path), '--sidecar', str(sidecar_path),
         '--packet', str(packet_path)],
        capture_output=True, text=True, cwd=str(ROOT))


def resolve_stock_code(ordinal):
    import csr8_phase_c_annotation_seal as c4d
    cand = c4d.candidate_for_ordinal(ordinal)
    salt = c4d.c1.load_salt()
    plan = json.loads(c4d.c1.PLAN_FILE.read_text())
    matches = [e for e in plan['entries']
               if c4d.c1.opaque_case_id(salt, e['case_key'])
               == cand['opaque_case_id'] and e['T'] == cand['T']]
    assert len(matches) == 1
    return matches[0]['case_key'].split('|')[1], cand['T']


def main():
    td = Path(tempfile.mkdtemp(prefix='nc-erratum11-test-'))
    results = {'test': 'NC-ERRATUM-1.1 support contract '
                       '(H2-CANARY-FIX1 + erratum 1.1)'}

    # -- 1. v1e1 equivalence + summary table (real candidates) ---------
    summaries = {}
    equiv = {}
    for n in (1, 2, 3, 4):
        v1_out = td / f'v1_o{n}.json'
        v1e1_out = td / f'v1e1_o{n}.json'
        run_builder('build_national_capital_context.py', n, v1_out)
        run_builder('build_national_capital_context_v1e1.py', n,
                    v1e1_out)
        v1 = json.loads(v1_out.read_bytes())
        v1e1 = json.loads(v1e1_out.read_bytes())
        strip = lambda d: {  # noqa: E731
            k: v for k, v in d.items() if k not in (
                'context_version', 'stock_layer_summary',
                'stock_layer_summary_report_period',
                'context_commitment_sha256')}
        equiv[n] = strip(v1) == strip(v1e1)
        summaries[n] = v1e1['stock_layer_summary']
        assert v1e1['context_version'] == 'csr8-national-capital-v1e1'
    assert all(equiv.values()), equiv
    assert summaries == {
        1: 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10',
        2: 'NO_PIT_VISIBLE_REPORT',
        3: 'NATIONAL_ACTORS_PRESENT',
        4: 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'}, summaries
    assert set(summaries.values()) <= set(v1e1_mod.STOCK_LAYER_SUMMARIES)
    results['v1e1_records_equivalence'] = equiv
    results['summary_table_ordinals_1_4'] = summaries

    # -- 2. DISAPPEARANCE regression (full path, injected data) --------
    sc, T = resolve_stock_code(4)
    assert T == '2021-08-02'
    fixture = {
        'pit': [
            {'stock_code': sc, 'report_period': '2020-12-31',
             'actor_id': 'A-TEST-FIXTURE', 'holding_ratio': '1.23',
             'available_date': '2021-03-30',
             'publication_date': '20210329',
             'source_grade': 'GRADE_A'},
            # latest complete report (2021-03-31, avail 2021-05-06 <= T):
            # NO tracked-actor row at all — the disclosure shows none.
        ],
        'ledger': [
            {'stock_code': sc, 'report_period': '2020-12-31',
             'source_status': 'SUCCESS_NONEMPTY'},
            {'stock_code': sc, 'report_period': '2021-03-31',
             'source_status': 'SUCCESS_NONEMPTY'},
        ],
        'pub': [],
        'calendar': ['2021-03-30', '2021-05-06'],
        'etf': [],
    }
    ctx = v1e1_mod.build(4, data=fixture)
    assert ctx['stock_layer_summary'] == \
        'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10', ctx[
            'stock_layer_summary']
    assert ctx['stock_layer_summary'] != 'NATIONAL_ACTORS_PRESENT'
    recs = ctx['stock_capital_records']
    assert len(recs) == 1, len(recs)
    assert recs[0]['actor_id'] == 'A-TEST-FIXTURE'
    assert recs[0]['state'] == 'NOT_DISCLOSED_IN_TOP10', recs[0][
        'state']
    assert recs[0]['previous_report_period'] == '2020-12-31'
    assert recs[0]['current_holding_ratio'] == ''
    # pure decision function spot checks (current-disclosure-only rule)
    assert v1e1_mod.stock_layer_summary_of(None, {}) == \
        'NO_PIT_VISIBLE_REPORT'
    assert v1e1_mod.stock_layer_summary_of(
        {'source_status': 'FAILED'}, {}) == 'SOURCE_UNAVAILABLE'
    assert v1e1_mod.stock_layer_summary_of(
        {'source_status': 'SUCCESS_NONEMPTY'}, {'a': {}}) == \
        'NATIONAL_ACTORS_PRESENT'
    assert v1e1_mod.stock_layer_summary_of(
        {'source_status': 'SUCCESS_NONEMPTY'}, {}) == \
        'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'
    results['disappearance_regression'] = {
        'fixture': 'previous complete top-10 discloses actor; latest '
                   'complete top-10 discloses none',
        'stock_layer_summary': ctx['stock_layer_summary'],
        'not_national_actors_present': True,
        'stock_records': len(recs),
        'record_state': recs[0]['state'],
        'pre_erratum_1_1_rule_would_say':
            'NATIONAL_ACTORS_PRESENT (the bug erratum 1.1 fixes)',
    }

    # -- 3. SOURCE_UNAVAILABLE full-path fixture ------------------------
    fixture_unav = {
        'pit': [{'stock_code': sc, 'report_period': '2020-12-31',
                 'actor_id': 'A-TEST-FIXTURE', 'holding_ratio': '1.23',
                 'available_date': '2021-03-30',
                 'publication_date': '20210329',
                 'source_grade': 'GRADE_A'}],
        'ledger': [
            {'stock_code': sc, 'report_period': '2020-12-31',
             'source_status': 'SUCCESS_NONEMPTY'},
            {'stock_code': sc, 'report_period': '2021-03-31',
             'source_status': 'FETCH_FAILED'},
        ],
        'pub': [], 'calendar': ['2021-03-30'], 'etf': [],
    }
    ctx_u = v1e1_mod.build(4, data=fixture_unav)
    assert ctx_u['stock_layer_summary'] == 'SOURCE_UNAVAILABLE'
    assert len(ctx_u['stock_capital_records']) == 1
    assert ctx_u['stock_capital_records'][0]['state'] == 'UNKNOWN'
    assert ctx_u['stock_capital_records'][0]['source_status'] == \
        'UNAVAILABLE'
    results['source_unavailable_full_path'] = 'PASS'

    # -- 4. POSITIVE stock>0 case (real ordinal-3) ----------------------
    import csr8_phase_c_annotation_seal as c4d
    sidecar = json.loads((td / 'v1e1_o3.json').read_bytes())
    stock_ids = [r['context_record_id'] for r in
                 sidecar['stock_capital_records']]
    market_ids = [r['context_record_id'] for r in
                  sidecar['market_etf_records']]
    assert sidecar['stock_layer_summary'] == 'NATIONAL_ACTORS_PRESENT'
    assert len(stock_ids) > 0
    cand = c4d.candidate_for_ordinal(3)
    pid = hashlib.sha256(
        f"{cand['opaque_case_id']}|{cand['T']}".encode()).hexdigest()
    packet = (c4d.c4ab.C3_STATE / 'packets' / f'{pid}.json')
    smap = {'version': 'csr8-national-context-support-v1',
            'ordinal': 3,
            'packet_sha256': sha_file(packet),
            'context_sha256': sidecar['context_commitment_sha256'],
            'judgments': {
                'rt_H01': list(stock_ids),
                'rt_H02': list(stock_ids),
                'rt_H03': [],
                'rt_H04': list(market_ids),
                'rt_H05': list(stock_ids),
                'rt_H06': list(stock_ids)}}
    smap_path = td / 'smap_positive.json'
    smap_path.write_text(json.dumps(smap, ensure_ascii=False,
                                    indent=2) + '\n')
    r = validator(smap_path, td / 'v1e1_o3.json', packet)
    assert r.returncode == 0, r.stderr
    results['positive_case'] = {
        'ordinal': 3, 'stock_records': len(stock_ids),
        'market_records': len(market_ids),
        'stock_layer_summary': sidecar['stock_layer_summary'],
        'cross_hypothesis_reuse': 'PASS'}

    # -- 5. negative control: within-hypothesis duplicate ---------------
    bad = json.loads(smap_path.read_bytes())
    bad['judgments']['rt_H01'] = list(stock_ids) + [stock_ids[0]]
    bad_path = td / 'smap_negative.json'
    bad_path.write_text(json.dumps(bad, ensure_ascii=False,
                                   indent=2) + '\n')
    r = validator(bad_path, td / 'v1e1_o3.json', packet)
    assert r.returncode != 0, 'validator accepted a ' \
                              'within-hypothesis duplicate'
    results['negative_control_within_hypothesis_dup'] = 'FAIL_CLOSED_OK'

    # -- 6. annotation review envelope ----------------------------------
    od = (ROOT / 'data/csr8_phase_c/c4d_receipts/c4-prod-0002'
          '/ordinal-0004')
    env = annotation_envelope_sha256(
        sha_file(od / 'packet.json'),
        json.loads((od / 'national_ctx_v1.json').read_bytes())[
            'context_commitment_sha256'],
        sha_file(od / 'context_support_map.json'),
        sha_file(od / 'annotation_draft.json'))
    assert env == ORDINAL4_ENVELOPE, env
    results['annotation_envelope'] = {
        'version': ANNOTATION_REVIEW_ENVELOPE_VERSION,
        'ordinal4_reference': env}

    report = {
        'test': results['test'],
        'status': 'PASS',
        'results': results,
        'scripts_sha256': {
            'build_national_capital_context_v1e1.py': sha_file(
                ROOT / 'scripts/build_national_capital_context_v1e1.py'),
            'validate_context_support_map.py': sha_file(
                ROOT / 'scripts/validate_context_support_map.py'),
            'csr8_phase_h_review_envelope.py': sha_file(
                ROOT / 'scripts/csr8_phase_h_review_envelope.py')},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False,
                                 indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
