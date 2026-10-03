#!/usr/bin/env python3
"""I2 PROTOCOL RATIFICATION — append-only. No outcome table/readout modification.

Ratifies the seven post-GO allowlist extensions used by 15b7eb7 as
pre-outcome deterministic authorities:

  R1  secret_salt: sha256(live salt) == C1 frozen salt commitment
  R2  calendar: session-date union rebuilt independently from the I1-pinned
      5,240 price files == frozen_exchange_calendar.csv date set, n=1386,
      sha 87f8f959... (closes early-C3-frozen calendar == I1-store-defined
      calendar)
  R3  national_context 32/32: live sha == I0.2 context_sha256
  R4  annotation_draft 32/32: live sha == I0.2 annotation_draft_sha256
  R5  I0.2 lineage + price manifest + I1 contract == I1 pinned hashes
  R6  incident record: 62f473e allowlist omission -> 15b7eb7 used 7
      extensions; all pre-outcome authorities; outcome artifacts untouched
      (byte-identity check against HEAD).
"""
import gzip, hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / 'docs/audit/evidence'
STORE = ROOT / 'data/adjustment_baostock/per_stock'
C1_COMMITMENT = 'd1df23bd0c33298d34274ac9ca8a1063defe42567c9a22b2c4b8e52baf9e5ee4'
CAL_EXPECT = {'n_days': 1386, 'sha256': '87f8f959910295640ebdf89b40cedb8de03049bc88c6ad4aace3f39b249c3f80'}
ORDINALS = list(range(7, 39))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def r1_salt():
    live = sha((ROOT / 'data/csr8_phase_c/secret/secret_salt').read_bytes().strip())
    return live == C1_COMMITMENT, {'live_sha256': live, 'c1_frozen_commitment': C1_COMMITMENT}


def r2_calendar():
    # rebuild the union of unadj session dates from the I1-pinned 5,240 files
    manifest = json.loads((EVID / 'phase_i_price_store_manifest.json').read_text())
    entries = manifest['entries']
    union = set()
    for e in entries:
        f = STORE / (e['code'] + '.json.gz')
        d = json.loads(gzip.decompress(f.read_bytes()))
        for row in d['unadj']:
            union.add(row[0])
    days = sorted(union)
    rebuilt_sha = sha(('date\n' + '\n'.join(days) + '\n').encode())
    lines = (ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv').read_text().splitlines()
    frozen_days = [l for l in lines if l and not l.startswith('#') and l != 'date']
    frozen_body_sha = sha(('date\n' + '\n'.join(frozen_days) + '\n').encode())
    ok = (days == sorted(frozen_days) and len(days) == CAL_EXPECT['n_days']
          and rebuilt_sha == CAL_EXPECT['sha256'] and frozen_body_sha == CAL_EXPECT['sha256'])
    return ok, {'rebuilt_n_days': len(days), 'frozen_n_days': len(frozen_days),
                'date_sets_identical': days == sorted(frozen_days),
                'rebuilt_body_sha256': rebuilt_sha, 'frozen_body_sha256': frozen_body_sha,
                'source': 'union of unadj session dates across I1-pinned 5,240 price files'}


def _r34(field, rel_fmt, two_args=False):
    lin = json.loads((EVID / 'phase_i_i0_2_evidence_derived_lineage.json').read_text())
    mismatches = []
    checked = 0
    for o in ORDINALS:
        row = next(r for r in lin['rows'] if r['ordinal'] == o)
        expected = row.get(field)
        rel = rel_fmt % (o - 2, o) if two_args else rel_fmt % o
        actual = sha((ROOT / rel).read_bytes())
        checked += 1
        if not expected or expected != actual:
            mismatches.append({'ordinal': o, 'expected': expected, 'actual': actual})
    return not mismatches, {'checked': checked, 'mismatches': mismatches[:5]}


def r3_context():
    return _r34('context_sha256', 'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/h%d/national_context/ordinal-%04d-national-ctx-v1.json', two_args=True)


def r4_draft():
    return _r34('annotation_draft_sha256', 'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-%04d/annotation_draft.json')


def r5_pinned_hashes():
    i1 = json.loads((EVID / 'phase_i_i1_contract.json').read_text())['contract']
    pinned = i1['pinned_input_hashes']
    checks = {}
    ok = True
    for rel_key, expected in pinned.items():
        rel = rel_key if '/' in rel_key else ('docs/audit/evidence/' + rel_key)
        actual = sha((ROOT / rel).read_bytes())
        checks[rel] = {'i1_pinned': expected, 'live': actual, 'match': actual == expected}
        ok = ok and actual == expected
    # price store closed-world canonical digest
    pm = json.loads((EVID / 'phase_i_price_store_manifest.json').read_text())
    stripped = dict(pm); stripped['manifest_sha256'] = ''
    pm_canon = sha(json.dumps(stripped, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    pm_ok = pm_canon == pm['manifest_sha256'] == '1d8c351982dab0ecd776f5710f9a57a97833214f4107d19b6b26dcf5c1ec7037'
    checks['price_store_manifest_canonical_digest'] = {'recomputed': pm_canon, 'declared': pm['manifest_sha256'], 'match': pm_ok}
    ok = ok and pm_ok
    return ok, checks


def r6_outcome_untouched():
    # byte-identity of outcome artifacts vs HEAD (no re-write, no replacement)
    out = {}
    ok = True
    for rel in ('docs/audit/evidence/phase_i_i2_outcome_table.json',
                'docs/audit/evidence/phase_i_i2_readout_report.json'):
        r = subprocess.run(['git', 'diff', 'HEAD', '--', rel], cwd=ROOT, capture_output=True, text=True)
        same = r.stdout.strip() == ''
        out[rel] = {'identical_to_HEAD': same}
        ok = ok and same
    return ok, out


def main():
    rat = {}
    rat['R1_secret_salt_vs_c1_commitment'] = r1_salt()
    rat['R2_calendar_union_from_5240_store'] = r2_calendar()
    rat['R3_national_context_sha_eq_i0_2'] = r3_context()
    rat['R4_annotation_draft_sha_eq_i0_2'] = r4_draft()
    rat['R5_pinned_input_hashes_eq_i1'] = r5_pinned_hashes()
    rat['R6_outcome_artifacts_untouched'] = r6_outcome_untouched()
    all_pass = all(ok for ok, _ in rat.values())
    record = {
        'report_type': 'PHASE_I_I2_PROTOCOL_RATIFICATION',
        'authority': 'user ruling on 15b7eb7: RATIFICATION_REQUIRED — append-only, no outcome modification',
        'incident': {
            'finding': '15b7eb7 reader used 7 allowlist extensions not enumerated by the 62f473e ARMED allowlist',
            'classification': 'protocol-authorization omission, not outcome contamination',
            'extensions': [
                'extension:secret_salt_for_ocid_hmac_resolution',
                'extension:contract_trading_calendar_proxy_pre-materialized',
                'extension:annotation_draft_for_taxonomy_diagnostic',
                'extension:national_context_primary_explanatory_variables',
                'extension:frozen_i0_2_lineage_hash_chain',
                'extension:armed_unlock_read_manifest_self',
                'extension:pinned_price_store_manifest',
            ],
            'pre_outcome_authority_basis': [
                'salt: C1 frozen commitment d1df23bd... (pre-outcome)',
                'calendar: C3 frozen at 04f54e1 as universe_stem_union n=1386 (pre-outcome)',
                'national_context / annotation_draft: byte-pinned in I0.2 frozen lineage (pre-outcome)',
                'lineage / price manifest / contract: committed I1-frozen artifacts (pre-outcome)',
            ],
        },
        'ratifications': {k: {'pass': ok, 'detail': d} for k, (ok, d) in rat.items()},
        'status': 'RATIFIED' if all_pass else 'RATIFICATION_FAILED',
        'outcome_table_modified': False,
        'readout_modified': False,
        'decision_A': 'unchanged (mechanical output of frozen rubric; ratified, not recomputed)',
    }
    (EVID / 'phase_i_i2_protocol_ratification.json').write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'status': record['status'], 'checks': {k: v['pass'] for k, v in record['ratifications'].items()}}))
    if not all_pass:
        sys.exit(1)


if __name__ == '__main__':
    main()
