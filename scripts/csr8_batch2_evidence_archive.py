#!/usr/bin/env python3
"""Batch-2 evidence archive (ruling 2026-10-02, batch-2 REVISE close-out).

The 41 pre-spawn DSH captures (40 official + 1 fail-closed incident) are the
trust roots of BATCH_COMPLETE for ordinal 15-22, but captures/ is gitignored.
This tool builds a closed-world manifest over them and provides an independent
verifier that unpacks the archive tarball and re-runs the FULL DSH-v4
trust-root chain for every sample (frozen raw zstd -> hash -> re-decode ->
decoded hash -> snapshot/anchor binding), so future auditors can replay the
batch-2 novelty proof from exact bytes.

CLI:
  --build-manifest --captures-root PATH --manifest OUT.json
  --verify --archive X.tar.gz --manifest M.json --samples samples.json
"""
import argparse, hashlib, json, sys, tarfile, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_batch_h_orchestrator as orch

ARCHIVE_ID = 'batch-h-b2-evidence-archive-v1'
OPS = {'next_reveal': 'NEXT_REVEAL', 'annotation': 'ANNOTATION',
       'receipt': 'RECEIPT', 'seal': 'SEAL', 'post_seal': 'POST_SEAL'}


def digest(b): return hashlib.sha256(b).hexdigest()


def classify(rel):
    p = Path(rel)
    parts = p.parts
    if len(parts) != 4 or parts[0] != 'captures' or parts[1] != 'batch2':
        raise ValueError('unexpected path in archive: %s' % rel)
    fname = parts[-1]
    if parts[2] == 'frozen':
        body = fname.split('.session')[0]
        o, rest = body[1:].split('_', 1)
        if rest.endswith('_retry'):
            name, attempt = rest[:-len('_retry')], 2
        else:
            name, attempt = rest, 1
        return int(o), OPS[name], attempt, 'frozen'
    else:
        o = int(parts[2][1:])
        dots = fname.split('.')
        # forms: <name>.snapshot.json | <name>.anchor.json | <name>.retry.snapshot.json | <name>.retry.anchor.json
        if len(dots) == 3:
            name, kind = dots[0], dots[1]
            attempt = 1
        elif len(dots) == 4:
            name, kind, attempt = dots[0], dots[1], 2
        else:
            raise ValueError('unclassifiable: %s' % rel)
        return o, OPS[name], attempt, kind


def build_manifest(captures_root, out_path):
    root = Path(captures_root)
    files = []
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        rel = 'captures/batch2/' + p.relative_to(root).as_posix()
        b = p.read_bytes()
        o, op, attempt, role = classify(rel)
        files.append({'path': rel, 'bytes': len(b), 'sha256': digest(b),
                      'ordinal': o, 'operation': op, 'attempt': attempt, 'role': role})
    m = {'archive_id': ARCHIVE_ID,
         'file_count': len(files),
         'total_bytes': sum(f['bytes'] for f in files),
         'capture_sets': len({(f['ordinal'], f['operation'], f['attempt']) for f in files}),
         'files': files}
    Path(out_path).write_text(json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    print(json.dumps({'status': 'BUILT', 'archive_id': ARCHIVE_ID, 'file_count': m['file_count'],
                      'capture_sets': m['capture_sets'], 'total_bytes': m['total_bytes'],
                      'manifest_sha256': digest(Path(out_path).read_bytes())}))


def verify(archive_path, manifest_path, samples_path):
    m = json.loads(Path(manifest_path).read_text())
    if m.get('archive_id') != ARCHIVE_ID:
        raise ValueError('unknown archive id')
    expected = {f['path']: f for f in m['files']}
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(archive_path, 'r:gz') as tf:
            names = [mm.name for mm in tf.getmembers() if mm.isfile()]
            extra = set(names) - set(expected)
            missing = set(expected) - set(names)
            if extra or missing:
                raise ValueError('archive closed-world violation: extra=%s missing=%s' % (sorted(extra)[:3], sorted(missing)[:3]))
            tf.extractall(td)
        root = Path(td)
        for f in m['files']:
            b = (root / f['path']).read_bytes()
            if len(b) != f['bytes'] or digest(b) != f['sha256']:
                raise ValueError('archive byte drift: %s' % f['path'])
        # full DSH-v4 trust-root re-verification for every official sample
        samples = json.loads(Path(samples_path).read_text())
        verified = 0
        for s in samples:
            snap_p = root / s['pre_spawn_snapshot']
            anch_p = root / s['snapshot_anchor_path']
            view, prefix = orch._read_snapshot(snap_p, anch_p)  # re-freezes nothing; re-decodes frozen bytes
            if view['executor_session_id'] != s['executor_session_id']:
                raise ValueError('session mismatch in archive sample seq %s' % s['ledger_sequence'])
            if s['reviewer_run_id'] in prefix or s['reviewer_session_id'] in prefix:
                raise ValueError('premature ID resurfaces in archive verify')
            verified += 1
        # incident capture (ordinal-21 RECEIPT attempt 1, failed spawn) integrity
        inc = [f for f in m['files'] if f['ordinal'] == 21 and f['operation'] == 'RECEIPT' and f['attempt'] == 1]
        if len(inc) != 3:
            raise ValueError('incident capture set incomplete: %d files' % len(inc))
        orch._read_snapshot(root / 'captures/batch2/o21/receipt.snapshot.json',
                            root / 'captures/batch2/o21/receipt.anchor.json')
        verdict = {'status': 'PASS', 'archive_id': ARCHIVE_ID,
                   'manifest_sha256': digest(Path(manifest_path).read_bytes()),
                   'archive_sha256': digest(Path(archive_path).read_bytes()),
                   'files_verified': len(m['files']), 'samples_verified': verified,
                   'incident_capture': 'VERIFIED', 'closed_world': 'PASS'}
        print(json.dumps(verdict, sort_keys=True, separators=(',', ':')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-manifest', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--captures-root', default='captures/batch2')
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--archive')
    ap.add_argument('--samples')
    a = ap.parse_args()
    if a.build_manifest:
        build_manifest(a.captures_root, a.manifest)
    elif a.verify:
        verify(a.archive, a.manifest, a.samples)
    else:
        raise SystemExit('choose --build-manifest or --verify')


if __name__ == '__main__':
    main()
