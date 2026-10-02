#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NC-ERRATUM-1 support-contract test (H2-CANARY-FIX1 item 4).

Proves, on blinded outputs only (enums/counts/hashes — never identity):

1. v1e equivalence: for ordinals 1-4 the erratum builder emits record
   arrays identical to the frozen v1 builder (only version/summary/
   commitment fields differ), and every stock_layer_summary branch
   reachable from the campaign candidates is exercised.
2. POSITIVE stock>0 case (real): ordinal-3 is NATIONAL_ACTORS_PRESENT
   with stock records > 0 — the exact future production shape.  A
   support map referencing the SAME stock records from rt_H01/rt_H02/
   rt_H05/rt_H06 (cross-hypothesis reuse) must PASS the revised
   validator and would have FAILED the pre-erratum global-uniqueness
   rule.
3. SOURCE_UNAVAILABLE fixture: synthesized v1e sidecar with the
   S-000000 UNAVAILABLE record; cross-hypothesis reuse passes.
4. Negative control: a within-hypothesis duplicate reference fails
   closed.
5. Annotation review envelope: frozen module reproduces the ordinal-4
   reference envelope and the reference vector.

Writes docs/audit/evidence/support_contract_test_report_v2.json.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from csr8_phase_h_review_envelope import (  # noqa: E402
    annotation_envelope_sha256, ANNOTATION_REVIEW_ENVELOPE_VERSION)

REPORT = ROOT / 'docs/audit/evidence/support_contract_test_report_v2.json'
HYPOTHESES = ['rt_H01', 'rt_H02', 'rt_H03', 'rt_H04', 'rt_H05', 'rt_H06']
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


def main():
    td = Path(tempfile.mkdtemp(prefix='nc-erratum-test-'))
    results = {}

    # -- 1. v1e equivalence + summary coverage --------------------------
    import build_national_capital_context_v1e as v1e_mod
    summaries = {}
    equiv = {}
    for n in (1, 2, 3, 4):
        v1_out = td / f'v1_o{n}.json'
        v1e_out = td / f'v1e_o{n}.json'
        run_builder('build_national_capital_context.py', n, v1_out)
        run_builder('build_national_capital_context_v1e.py', n, v1e_out)
        v1 = json.loads(v1_out.read_bytes())
        v1e = json.loads(v1e_out.read_bytes())
        strip = lambda d: {  # noqa: E731
            k: v for k, v in d.items() if k not in (
                'context_version', 'stock_layer_summary',
                'stock_layer_summary_report_period',
                'context_commitment_sha256')}
        equiv[n] = strip(v1) == strip(v1e)
        summaries[n] = v1e['stock_layer_summary']
    assert all(equiv.values()), equiv
    assert summaries == {
        1: 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10',
        2: 'NO_PIT_VISIBLE_REPORT',
        3: 'NATIONAL_ACTORS_PRESENT',
        4: 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'}, summaries
    assert set(summaries.values()) <= set(v1e_mod.STOCK_LAYER_SUMMARIES)
    results['v1e_records_equivalence'] = equiv
    results['summary_coverage_ordinals_1_4'] = summaries

    # -- 2. POSITIVE stock>0 case (real ordinal-3 data) ------------------
    import csr8_phase_c_annotation_seal as c4d
    sidecar = json.loads((td / 'v1e_o3.json').read_bytes())
    stock_ids = [r['context_record_id'] for r in
                 sidecar['stock_capital_records']]
    market_ids = [r['context_record_id'] for r in
                  sidecar['market_etf_records']]
    assert sidecar['stock_layer_summary'] == 'NATIONAL_ACTORS_PRESENT'
    assert len(stock_ids) > 0, 'ordinal-3 must carry stock records'
    cand = c4d.candidate_for_ordinal(3)
    pid = hashlib.sha256(
        f"{cand['opaque_case_id']}|{cand['T']}".encode()).hexdigest()
    packet = (c4d.c4ab.C3_STATE / 'packets' / f'{pid}.json')
    smap = {'version': 'csr8-national-context-support-v1',
            'ordinal': 3,
            'packet_sha256': sha_file(packet),
            'context_sha256':
                sidecar['context_commitment_sha256'],
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
    r = validator(smap_path, td / 'v1e_o3.json', packet)
    assert r.returncode == 0, r.stderr
    results['positive_case'] = {
        'ordinal': 3,
        'stock_records': len(stock_ids),
        'market_records': len(market_ids),
        'stock_layer_summary': sidecar['stock_layer_summary'],
        'cross_hypothesis_reuse': 'PASS',
        'old_global_uniqueness_would_reject':
            len([x for j in smap['judgments'].values() for x in j])
            != len({x for j in smap['judgments'].values() for x in j})}

    # -- 3. SOURCE_UNAVAILABLE fixture -----------------------------------
    base = json.loads((td / 'v1e_o4.json').read_bytes())
    base['stock_layer_summary'] = 'SOURCE_UNAVAILABLE'
    base['stock_capital_records'] = [{
        'context_record_id': 'S-000000', 'capital_layer': 'STOCK',
        'evidence_type': 'NATIONAL_ACTOR_HOLDING_STATE',
        'actor_id': '', 'state': 'UNKNOWN',
        'current_report_period': 'FIXTURE',
        'current_publication_date': '', 'current_available_date': '',
        'current_holding_ratio': '',
        'previous_report_period': '', 'previous_holding_ratio': '',
        'evidence_grade': 'SOURCE_UNAVAILABLE',
        'source_status': 'UNAVAILABLE'}]
    fixture = td / 'fixture_unavailable.json'
    fixture.write_text(json.dumps(base, ensure_ascii=False,
                                  indent=2) + '\n')
    cand4 = c4d.candidate_for_ordinal(4)
    pid4 = hashlib.sha256(
        f"{cand4['opaque_case_id']}|{cand4['T']}".encode()).hexdigest()
    packet4 = (c4d.c4ab.C3_STATE / 'packets' / f'{pid4}.json')
    smap_fix = {'version': 'csr8-national-context-support-v1',
                'ordinal': 4,
                'packet_sha256': sha_file(packet4),
                'context_sha256':
                    base['context_commitment_sha256'],
                'judgments': {
                    'rt_H01': ['S-000000'], 'rt_H02': ['S-000000'],
                    'rt_H03': [], 'rt_H04': [],
                    'rt_H05': ['S-000000'], 'rt_H06': ['S-000000']}}
    fix_path = td / 'smap_unavailable.json'
    fix_path.write_text(json.dumps(smap_fix, ensure_ascii=False,
                                   indent=2) + '\n')
    r = validator(fix_path, fixture, packet4)
    assert r.returncode == 0, r.stderr
    results['source_unavailable_fixture'] = 'PASS'

    # -- 4. negative control: within-hypothesis duplicate ----------------
    bad = json.loads(smap_path.read_bytes())
    bad['judgments']['rt_H01'] = list(stock_ids) + [stock_ids[0]]
    bad_path = td / 'smap_negative.json'
    bad_path.write_text(json.dumps(bad, ensure_ascii=False,
                                   indent=2) + '\n')
    r = validator(bad_path, td / 'v1e_o3.json', packet)
    assert r.returncode != 0, 'validator accepted a within-hypothesis ' \
                              'duplicate'
    results['negative_control_within_hypothesis_dup'] = 'FAIL_CLOSED_OK'

    # -- 5. annotation review envelope -----------------------------------
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
        'test': 'NC-ERRATUM-1 support contract (H2-CANARY-FIX1 item 4)',
        'status': 'PASS',
        'results': results,
        'scripts_sha256': {
            'build_national_capital_context_v1e.py': sha_file(
                ROOT / 'scripts/build_national_capital_context_v1e.py'),
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
