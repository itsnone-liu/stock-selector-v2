#!/usr/bin/env python3
"""Phase-I I2 unlock ceremony — PRE-GATES ONLY (steps 1-6).

Runs the frozen pre-unlock gates in one logged ceremony:
  G1  I1 contract canonical SHA re-verification
  G2  sealed-input archive verification (manifest self-digest + member equality
      + archive sha against the pinned durable release value)
  G3  price-store manifest canonical digest re-verification
  G4  live closed-world re-derivation of the 5,240-file price store
      (set equality, bytes equality, sha256 equality per file)
  G5  selector secret bytes-SHA equality only (never parsed)
  G6  freeze the I2 unlock runtime-read manifest (empty read log) that will
      govern the actual unblinding reads

NO selector-mapping parsing, NO per-case price value reads. Outcome data
stays sealed; this ceremony only authorizes-or-blocks the unblind step.
"""
import hashlib, json, sys, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / 'docs/audit/evidence'
STORE = ROOT / 'data/adjustment_baostock'
SECRET = ROOT / 'data/csr8_phase_c/secret/packet_plan.json'
ARCHIVE = ROOT / 'phase_i_sealed_input_archive_v1.tar.gz'

PINNED = {
    'contract_sha256': '1b2db3ae2b51234d05cac80f98eebef5ca8ba6058d1fc17e7cb597cd8f7addf3',
    'archive_sha256': '21365b9e0d8448031c922e4850bcded286827b511fe00e071757e2bf57f7e8f2',
    'price_manifest_sha256': '1d8c351982dab0ecd776f5710f9a57a97833214f4107d19b6b26dcf5c1ec7037',
    'secret_sha256': '6a3051cb26cea71849838a42a17a76836a431e841a6f146a8f4a214bb1278a34',
    'i1_commit': '6f39dac5f660d87a75d0414344f7d69636faaf4d',
    'archive_closeout_commit': '60bef10',
}

reads = []


def logged_read(rel, purpose):
    p = ROOT / rel
    b = p.read_bytes()
    reads.append({'relative_path': rel, 'bytes': len(b),
                  'sha256': hashlib.sha256(b).hexdigest(), 'purpose': purpose})
    return b


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def g1_contract():
    b = logged_read('docs/audit/evidence/phase_i_i1_contract.json', 'I1 contract pre-gate re-verification')
    outer = json.loads(b)
    c = dict(outer['contract'])
    c['unlock_gate']['i1_contract_sha256'] = ''
    actual = hashlib.sha256(canon(c).encode()).hexdigest()
    return actual == PINNED['contract_sha256'] == outer['contract_sha256'], {'recomputed': actual, 'claimed': outer['contract_sha256']}


def g2_archive():
    mb = logged_read('docs/audit/evidence/phase_i_sealed_input_archive_manifest.json', 'sealed archive manifest pre-gate')
    m = json.loads(mb)
    stripped = dict(m); stripped['manifest_sha256'] = ''
    digest_ok = hashlib.sha256(canon(stripped).encode()).hexdigest() == m['manifest_sha256']
    ab = logged_read('phase_i_sealed_input_archive_v1.tar.gz', 'sealed archive asset pre-gate (hash only)')
    archive_ok = hashlib.sha256(ab).hexdigest() == PINNED['archive_sha256']
    got = {}
    import io
    with tarfile.open(fileobj=io.BytesIO(ab)) as tf:
        from pathlib import PurePosixPath
        for mm in tf.getmembers():
            if not (mm.isfile() or mm.isdir()):
                return False, {'error': 'non-regular member %s' % mm.name}
            pp = PurePosixPath(mm.name)
            if pp.is_absolute() or any(part == '..' for part in pp.parts):
                return False, {'error': 'traversal member %s' % mm.name}
            if mm.isfile():
                got[mm.name] = hashlib.sha256(tf.extractfile(mm).read()).hexdigest()
    expected = {e['path']: e['sha256'] for e in m['files']}
    expected['docs/audit/evidence/phase_i_sealed_input_archive_manifest.json'] = hashlib.sha256(mb).hexdigest()
    members_ok = set(got) == set(expected) and all(got[k] == expected[k] for k in got)
    return digest_ok and archive_ok and members_ok, {'manifest_self_digest': digest_ok, 'archive_sha': archive_ok, 'member_equality': members_ok, 'file_count': len(got)}


def g3_price_manifest_digest():
    b = logged_read('docs/audit/evidence/phase_i_price_store_manifest.json', 'price manifest digest pre-gate')
    m = json.loads(b)
    stripped = dict(m); stripped['manifest_sha256'] = ''
    actual = hashlib.sha256(canon(stripped).encode()).hexdigest()
    return actual == m['manifest_sha256'] == PINNED['price_manifest_sha256'], {'recomputed': actual, 'declared': m['manifest_sha256']}


def g4_price_closed_world():
    m = json.loads((EVID / 'phase_i_price_store_manifest.json').read_text())
    fetch = json.loads((STORE / 'fetch_manifest.json').read_text())
    declared = fetch.get('stocks', {})
    entries = {e['code']: e for e in m['entries']}
    files = sorted((STORE / 'per_stock').glob('*.json.gz'))
    if len(files) != 5240 or len(entries) != 5240:
        return False, {'file_count': len(files), 'manifest_count': len(entries)}
    set_ok = {f.name[:-8] for f in files} == set(entries)
    bytes_bad, sha_bad = [], []
    for f in files:
        code = f.name[:-8]
        e = entries[code]
        size = f.stat().st_size
        if size != e['bytes']:
            bytes_bad.append(code); continue
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        if h != e['sha256']:
            sha_bad.append(code)
        # fetch-manifest cross-check reuses the same hash, no extra read
        d = declared.get(code)
        if not isinstance(d, dict) or d.get('sha256') != h:
            sha_bad.append(code + ':fetch')
    ok = set_ok and not bytes_bad and not sha_bad
    return ok, {'set_equality': set_ok, 'bytes_mismatches': bytes_bad[:5], 'sha_mismatches': sha_bad[:5], 'checked': len(files)}


def g5_secret_hash():
    b = logged_read('data/csr8_phase_c/secret/packet_plan.json', 'selector secret pre-gate (hash only, never parsed)')
    actual = hashlib.sha256(b).hexdigest()
    return actual == PINNED['secret_sha256'], {'recomputed': actual, 'parsed': False}


def main():
    gates = {}
    gates['G1_i1_contract_sha'] = g1_contract()
    gates['G2_sealed_archive'] = g2_archive()
    gates['G3_price_manifest_digest'] = g3_price_manifest_digest()
    gates['G4_price_closed_world_rehash'] = g4_price_closed_world()
    gates['G5_secret_bytes_hash'] = g5_secret_hash()
    all_pass = all(ok for ok, _ in gates.values())
    # G6: freeze the unlock runtime-read manifest (read log currently contains only pre-gate reads)
    unlock_manifest = {
        'report_type': 'PHASE_I_I2_UNLOCK_RUNTIME_READ_MANIFEST',
        'status': 'ARMED' if all_pass else 'BLOCKED',
        'pre_gate_reads': reads,
        'allowed_roots_for_unblind': [
            'data/csr8_phase_c/secret/packet_plan.json (parse mapping; ordinal 7-38 only)',
            'data/adjustment_baostock/per_stock/<mapped code>.json.gz (frozen price series)',
            'docs/audit/evidence/phase_i_i1_contract.json',
            'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ (sealed packet metadata for T/identity cross-check)',
        ],
        'forbidden': ['any outcome table other than the one produced by this ceremony', 'any data source outside the pinned store'],
        'outcome_read_authorized': False,
    }
    (EVID / 'phase_i_i2_unlock_read_manifest.json').write_text(json.dumps(unlock_manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    ceremony = {
        'report_type': 'PHASE_I_I2_UNLOCK_CEREMONY_PREGATES',
        'status': 'ALL_PASS' if all_pass else 'FAIL_CLOSED',
        'pinned': PINNED,
        'gates': {k: {'pass': ok, 'detail': d} for k, (ok, d) in gates.items()},
        'pre_gate_read_count': len(reads),
        'outcome_values_read': 0,
        'mapping_parsed': False,
        'next_step': 'await explicit authorization for steps 7-9 (mapping parse, per-case price read, outcome table) under this armed manifest',
    }
    (EVID / 'phase_i_i2_unlock_ceremony.json').write_text(json.dumps(ceremony, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'status': ceremony['status'], 'gates': {k: v['pass'] for k, v in ceremony['gates'].items()}, 'pre_gate_reads': len(reads), 'outcome_read_authorized': False}))
    if not all_pass:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
