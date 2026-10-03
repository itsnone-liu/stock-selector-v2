#!/usr/bin/env python3
"""PHASE-I SEALED INPUT ARCHIVE builder + verifier (outcome-free).

Scope (frozen by the I1 unlock gate):
  - every file in the I0.2 runtime read manifest (sealed inputs actually used)
  - sealing_log.jsonl (already inside the runtime manifest; asserted present)
  - Batch 1-4 completion bindings (asserted present via runtime manifest)
  - phase_i_price_store_manifest.json and the baostock fetch_manifest.json
  - Phase-I verifier/code commitments (I0/I0.1/I0.2 builders, envelope module)

Never touches the selector secret or any per-stock price file: the archive
binds the price store through its closed-world manifest only.

CLI:
  --build-manifest  --manifest OUT.json --archive OUT.tar.gz
  --verify --archive X.tar.gz --manifest M.json
  --replay-lineage --archive X.tar.gz --workdir DIR
"""
import argparse, hashlib, json, sys, tarfile, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ID = 'phase-i-sealed-input-archive-v1'
EVID = ROOT / 'docs/audit/evidence'

RUNTIME_MANIFEST = EVID / 'phase_i_i0_2_evidence_derived_lineage.json'
EXTRA_FILES = [
    'docs/audit/evidence/phase_i_price_store_manifest.json',
    'data/adjustment_baostock/fetch_manifest.json',
    'scripts/phase_i_i0_inventory.py',
    'scripts/phase_i_i0_1_lineage.py',
    'scripts/phase_i_i0_2_lineage.py',
    'scripts/phase_i_price_store_manifest.py',
    'scripts/phase_i_i1_contract.py',
    'scripts/csr8_phase_h_review_envelope.py',
    'docs/audit/evidence/phase_i_i1_contract.json',
    'docs/audit/evidence/phase_i_i0_corpus_inventory.json',
    'docs/audit/evidence/phase_i_i0_1_sealed_case_lineage.json',
    'docs/audit/evidence/phase_i_i0_1_runtime_read_manifest.json',
    'docs/audit/evidence/phase_i_i0_no_outcome_dependency_report.json',
]


def digest(b):
    return hashlib.sha256(b).hexdigest()


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def collect():
    lineage = json.loads(RUNTIME_MANIFEST.read_text())
    rm = lineage['runtime_read_manifest']
    seen = {}
    for r in rm:
        seen.setdefault(r['relative_path'], r)
    for rel in EXTRA_FILES:
        if rel not in seen:
            seen[rel] = None
    entries = []
    for rel in sorted(seen):
        p = ROOT / rel
        if not p.is_file():
            raise RuntimeError('archive input missing: %s' % rel)
        b = p.read_bytes()
        entries.append({'path': rel, 'bytes': len(b), 'sha256': digest(b),
                        'runtime_manifest_purpose': seen[rel]['purpose'] if seen[rel] else 'phase-i code/contract commitment'})
    # structural assertions required by the I1 unlock gate
    paths = {e['path'] for e in entries}
    for required in ['data/csr8_phase_c/production/c4-prod-0002/sealing/sealing_log.jsonl',
                     'docs/audit/evidence/batch_h_batch1_completion.json',
                     'docs/audit/evidence/batch_h_batch2_completion.json',
                     'docs/audit/evidence/batch_h_batch3_completion.json',
                     'docs/audit/evidence/batch_h_batch4_completion.json',
                     'docs/audit/evidence/phase_i_price_store_manifest.json']:
        if required not in paths:
            raise RuntimeError('required scope file absent: %s' % required)
    return entries


def build_manifest(manifest_out, archive_out):
    entries = collect()
    m = {'archive_id': ARCHIVE_ID,
         'file_count': len(entries),
         'total_bytes': sum(e['bytes'] for e in entries),
         'files': entries,
         'selector_secret_included': False,
         'per_stock_price_files_included': False,
         'price_store_binding': 'closed-world manifest only (phase_i_price_store_manifest.json); no price file bytes archived',
         'canonicalization': 'manifest_sha256 = sha256(canon(manifest with manifest_sha256=""))'}
    m['manifest_sha256'] = ''
    d = hashlib.sha256(canon(m).encode()).hexdigest()
    m['manifest_sha256'] = d
    Path(manifest_out).write_text(json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    with tarfile.open(archive_out, 'w:gz') as tf:
        for e in entries:
            tf.add(str(ROOT / e['path']), arcname=e['path'], recursive=False)
        tf.add(str(manifest_out), arcname='docs/audit/evidence/phase_i_sealed_input_archive_manifest.json', recursive=False)
    a = digest(Path(archive_out).read_bytes())
    print(json.dumps({'status': 'BUILT', 'archive_id': ARCHIVE_ID, 'file_count': m['file_count'],
                      'total_bytes': m['total_bytes'], 'manifest_sha256': d, 'archive_sha256': a,
                      'archive_path': str(archive_out)}))
    return m, a


def _safe_members(tf):
    from pathlib import PurePosixPath
    safe = []
    for mm in tf.getmembers():
        if not (mm.isfile() or mm.isdir()):
            raise ValueError('non-regular member: %s' % mm.name)
        pp = PurePosixPath(mm.name)
        if pp.is_absolute() or any(part == '..' for part in pp.parts):
            raise ValueError('path traversal: %s' % mm.name)
        safe.append(mm)
    return safe


def verify(archive_path, manifest_path):
    m = json.loads(Path(manifest_path).read_text())
    stripped = dict(m); stripped['manifest_sha256'] = ''
    if hashlib.sha256(canon(stripped).encode()).hexdigest() != m['manifest_sha256']:
        raise RuntimeError('manifest self-digest mismatch')
    got = {}
    with tarfile.open(archive_path) as tf:
        for mm in _safe_members(tf):
            if not mm.isfile():
                continue
            got[mm.name] = digest(tf.extractfile(mm).read())
    expected = {e['path']: e['sha256'] for e in m['files']}
    embedded = 'docs/audit/evidence/phase_i_sealed_input_archive_manifest.json'
    expected[embedded] = digest(Path(manifest_path).read_bytes())
    extra = set(got) - set(expected)
    missing = set(expected) - set(got)
    bad = [p for p in set(got) & set(expected) if got[p] != expected[p]]
    if extra or missing or bad:
        raise RuntimeError('archive mismatch: extra=%d missing=%d bad=%d' % (len(extra), len(missing), len(bad)))
    print(json.dumps({'status': 'VERIFY_PASS', 'archive_id': m['archive_id'], 'file_count': m['file_count'],
                      'archive_sha256': digest(Path(archive_path).read_bytes())}))


def replay_lineage(archive_path, workdir):
    """Extract archive copies only, then re-run the I0.2 verifier against them."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path) as tf:
        tf.extractall(workdir, members=_safe_members(tf))
    sys.path.insert(0, str(workdir / 'scripts'))
    import importlib
    i01 = importlib.import_module('phase_i_i0_1_lineage')
    i02 = importlib.import_module('phase_i_i0_2_lineage')
    # rebind roots to the extracted tree
    i01.ROOT = workdir
    for name in ('RECEIPTS', 'PROPOSALS', 'CAMPAIGN', 'PRODUCTION', 'DOCS'):
        base = {'RECEIPTS': 'data/csr8_phase_c/c4d_receipts/c4-prod-0002',
                'PROPOSALS': 'data/csr8_phase_c/c4d_proposals/c4-prod-0002',
                'CAMPAIGN': 'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927',
                'PRODUCTION': 'data/csr8_phase_c/production/c4-prod-0002',
                'DOCS': 'docs/audit/evidence'}[name]
        setattr(i01, name, workdir / base)
    i02.OUT = workdir / 'docs/audit/evidence'
    i02.ROOT = workdir
    i02.RECEIPTS, i02.PROPOSALS, i02.CAMPAIGN, i02.PRODUCTION, i02.DOCS = (
        i01.RECEIPTS, i01.PROPOSALS, i01.CAMPAIGN, i01.PRODUCTION, i01.Docs() if False else i01.DOCS)
    orig_print = print
    import io
    buf = io.StringIO()
    i02.main.__globals__['__print__'] = None
    import contextlib
    with contextlib.redirect_stdout(buf):
        i02.main()
    out = json.loads(buf.getvalue())
    replay = json.loads((workdir / 'docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json').read_text())
    fresh = json.loads((ROOT / 'docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json').read_text())
    same = all(a['annotation_envelope_sha256'] == b['annotation_envelope_sha256'] and
               a['review_verdict_input_commitment_sha256'] == b['review_verdict_input_commitment_sha256']
               for a, b in zip(replay['rows'], fresh['rows']))
    ok = out.get('ordinary_complete') == 32 and replay['ordinary_lineage_complete_count'] == 32 and same
    print(json.dumps({'status': 'REPLAY_PASS' if ok else 'REPLAY_FAIL',
                      'ordinary_complete': replay['ordinary_lineage_complete_count'],
                      'envelope_binding_preserved': bool(same)}))
    if not ok:
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-manifest', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--replay-lineage', action='store_true')
    ap.add_argument('--manifest', default=str(EVID / 'phase_i_sealed_input_archive_manifest.json'))
    ap.add_argument('--archive', default=str(ROOT / 'phase_i_sealed_input_archive_v1.tar.gz'))
    ap.add_argument('--workdir', default=None)
    a = ap.parse_args()
    if a.build_manifest:
        build_manifest(a.manifest, a.archive)
    elif a.verify:
        verify(a.archive, a.manifest)
    elif a.replay_lineage:
        replay_lineage(a.archive, a.workdir or (Path(tempfile.mkdtemp()) / 'replay'))


if __name__ == '__main__':
    main()
