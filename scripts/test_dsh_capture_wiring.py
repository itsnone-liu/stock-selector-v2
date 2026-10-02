#!/usr/bin/env python3
"""End-to-end wiring regression (ruling 2026-10-02 Batch-2 wiring FIX):

  capture_pre_spawn_dsh_snapshot (real zstd trust-root capture)
    -> reviewer ledger row (IDs exist only after spawn)
    -> reviewer_id_novelty_spot_check via _read_snapshot DSH-v4 branch
    -> complete_batch with --previous-batch-record derivation

Negative controls prove the v4 branch actually re-derives the decoded text
from the frozen raw zstd instead of trusting the snapshot's payload.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_batch_h_orchestrator as orch
import ctypes

FAILS = []

_lib = ctypes.CDLL('/lib/x86_64-linux-gnu/libzstd.so.1')
_lib.ZSTD_compressBound.restype = ctypes.c_size_t
_lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
_lib.ZSTD_compress.restype = ctypes.c_size_t
_lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]

def zstd_frame(data: bytes, level=3) -> bytes:
    cap = _lib.ZSTD_compressBound(len(data))
    dst = ctypes.create_string_buffer(cap)
    src = ctypes.create_string_buffer(data)
    n = _lib.ZSTD_compress(ctypes.cast(dst, ctypes.c_void_p), cap,
                           ctypes.cast(src, ctypes.c_void_p), len(data), level)
    if n == 0: raise RuntimeError('ZSTD_compress failed')
    return dst.raw[:n]

def zstd_frames(chunks):
    """Concatenate independent zstd frames (multi-frame file)."""
    return b''.join(zstd_frame(c) for c in chunks)

def build_live(td, with_ids=False):
    """Live session.jsonl.zstd with two frames: session record + chatter.
    Optionally embed a reviewer ID pre-spawn (premature-ID negative control)."""
    sid = 'session-e2etest-0001'
    rec = {'type': 'session', 'id': sid, 'origin': None, 'parentSession': None}
    chatter = 'executor chatter line\n' * 50
    if with_ids: chatter += 'reviewer_run_id reviewer_20261002_e2e_probe\n'
    raw = zstd_frames([json.dumps(rec).encode() + b'\n', chatter.encode()])
    live = Path(td) / 'session.jsonl.zstd'
    live.write_bytes(raw)
    return live, sid

def write_ledger(td, ids):
    """Synthetic append-only ledger: one row per (ordinal, op) pair."""
    rows = []; prev = ''
    for i, (o, op, run, sess) in enumerate(ids):
        row = {'sequence': i, 'ordinal': o, 'operation': op, 'state': 'APPROVE',
               'campaign_id': 'synthetic', 'created_at': '2026-10-02T00:00:00Z',
               'input_commitment_sha256': 'a' * 64, 'reviewer_run_id': run,
               'reviewer_session_id': sess, 'prev_review_hash': prev}
        row['review_hash'] = orch.digest(orch.canon(row).encode())
        rows.append(row); prev = row['review_hash']
    p = Path(td) / 'reviews.jsonl'
    p.write_text('\n'.join(orch.canon(r) for r in rows) + '\n')
    return p, rows

def capture_and_spawn(td, live, sid, ledger_rows):
    """Capture pre-spawn, then append the post-spawn frame carrying the IDs."""
    frozen = Path(td) / 'frozen' / 'session.jsonl.zstd'
    snap_p = Path(td) / 'snap.json'; anch_p = Path(td) / 'snap.anchor.json'
    snap, anch = orch.capture_pre_spawn_dsh_snapshot(str(live), sid, snap_p, anch_p, frozen)
    # post-spawn growth: new frame with the reviewer IDs (not in the capture)
    live.write_bytes(live.read_bytes() + zstd_frames([b'reviewer echo reviewer_20261002_e2e_probe\n']))
    samples = [{'ordinal': r['ordinal'], 'reviewer_operation': r['operation'],
                'ledger_sequence': r['sequence'], 'review_hash': r['review_hash'],
                'reviewer_run_id': r['reviewer_run_id'], 'reviewer_session_id': r['reviewer_session_id'],
                'executor_session_id': sid, 'pre_spawn_snapshot': str(snap_p),
                'snapshot_anchor_path': str(anch_p)} for r in ledger_rows]
    return snap, samples

def expect_fail(name, fn):
    try:
        fn()
    except Exception as e:
        print(f'{name}: REJECTED ({e})'); return
    FAILS.append(name); print(f'{name}: NOT REJECTED — FAIL')

def main():
    with tempfile.TemporaryDirectory() as td0:
        # ---- happy path: capture -> ledger -> spot_check -> complete_batch ----
        td = Path(td0) / 'w1'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td)
        ids = [(15 + i, 'NEXT_REVEAL', f'reviewer_20261002_e2e_o{15+i}', f'subagent-e2e-{i}')
               for i in range(8)]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        # prior batch record for previous-id derivation
        prior = Path(td) / 'prior_batch.json'
        prior_ids = [x for (_, _, run, sess) in ids[:0]]  # none of current
        prior.write_text(json.dumps({'status': 'BATCH_COMPLETE',
            'novelty_gate': {'evidence': [{'reviewer_run_id': 'reviewer_old_1',
                                           'reviewer_session_id': 'subagent-old-1'}]}}))
        rec = orch.complete_batch(15, list(range(15, 23)), samples, ledger_p,
                                  previous_batch_record=str(prior))
        gate = rec['novelty_gate']
        ok = (rec['status'] == 'BATCH_COMPLETE' and gate['novelty'] and
              gate['checked_samples'] == 8 and
              all('frozen_capture_path' in e and 'raw_zstd_sha256' in e for e in gate['evidence']))
        print('e2e capture->ledger->spot_check->complete_batch:',
              'PASS' if ok else 'FAIL')
        if not ok: FAILS.append('e2e happy')
        dev = orch.derive_previous_ids(prior)
        if dev == ['reviewer_old_1', 'subagent-old-1']:
            print('derive_previous_ids from prior record: PASS')
        else:
            FAILS.append('derive'); print('derive_previous_ids: FAIL')

        # ---- negative control: reviewer ID already present pre-spawn ----
        td = Path(td0) / 'w2'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td, with_ids=True)
        ids = [(23, 'NEXT_REVEAL', 'reviewer_20261002_e2e_probe', 'subagent-w2')]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        expect_fail('premature ID in pre-spawn capture',
                    lambda: orch.reviewer_id_novelty_spot_check(23, (), samples, ledger_p))

        # ---- negative control: frozen trust-root tampered (extra bytes) ----
        td = Path(td0) / 'w3'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td)
        ids = [(23, 'NEXT_REVEAL', 'reviewer_20261002_e2e_w3', 'subagent-w3')]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        frozen = Path(snap['frozen_capture_path']); frozen.chmod(0o600)
        frozen.write_bytes(frozen.read_bytes() + zstd_frames([b'extra\n']))
        expect_fail('frozen capture tamper', lambda: orch._read_snapshot(
            Path(td) / 'snap.json', Path(td) / 'snap.anchor.json'))

        # ---- negative control: anchor mismatch ----
        td = Path(td0) / 'w4'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td)
        ids = [(23, 'NEXT_REVEAL', 'reviewer_20261002_e2e_w4', 'subagent-w4')]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        anch = Path(td) / 'snap.anchor.json'; anch.chmod(0o600)
        a = json.loads(anch.read_text()); a['raw_zstd_sha256'] = '0' * 64
        anch.write_text(orch.canon(a))
        expect_fail('anchor provenance mismatch', lambda: orch._read_snapshot(
            Path(td) / 'snap.json', anch))

        # ---- negative control: snapshot decoded text forged (sha kept) ----
        td = Path(td0) / 'w5'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td)
        ids = [(23, 'NEXT_REVEAL', 'reviewer_20261002_e2e_w5', 'subagent-w5')]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        snap_p = Path(td) / 'snap.json'; snap_p.chmod(0o600)
        s = json.loads(snap_p.read_text()); s['transcript_prefix'] += 'FORGED\n'
        snap_p.write_text(orch.canon(s))
        expect_fail('forged decoded text vs re-derived decode', lambda: orch._read_snapshot(
            snap_p, Path(td) / 'snap.anchor.json'))

        # ---- negative control: manual previous_ids conflicting with record ----
        td = Path(td0) / 'w6'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td)
        ids = [(15 + i, 'NEXT_REVEAL', f'reviewer_20261002_e2e_v{i}', f'subagent-v{i}')
               for i in range(8)]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        expect_fail('manual previous_ids conflict',
                    lambda: orch.complete_batch(15, list(range(15, 23)), samples,
                                                ledger_p, previous_ids=['bogus'],
                                                previous_batch_record=str(prior)))

        # ---- CLI: --previous-id together with --previous-batch-record refused ----
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'csr8_batch_h_orchestrator.py'),
                            '--batch-start', '15'] + sum([['--completed-ordinal', str(o)] for o in range(15, 23)], []) +
                           ['--novelty-evidence-json', '/dev/null', '--ledger', '/dev/null',
                            '--previous-id', 'x', '--previous-batch-record', str(prior)],
                           capture_output=True, text=True)
        if r.returncode != 0 and 'refusing manual' in (r.stdout + r.stderr):
            print('CLI refuses --previous-id + --previous-batch-record: PASS')
        else:
            FAILS.append('cli mutex'); print('CLI mutex: FAIL', r.returncode, r.stderr[-200:])

        # ---- CLI: record-only happy path via subprocess ----
        td = Path(td0) / 'w7'; (td / 'frozen').mkdir(parents=True)
        live, sid = build_live(td)
        ids = [(15 + i, 'NEXT_REVEAL', f'reviewer_20261002_e2e_c{i}', f'subagent-c{i}')
               for i in range(8)]
        ledger_p, rows = write_ledger(td, ids)
        snap, samples = capture_and_spawn(td, live, sid, rows)
        ev_p = Path(td) / 'samples.json'; ev_p.write_text(orch.canon(samples))
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'csr8_batch_h_orchestrator.py'),
                            '--batch-start', '15'] + sum([['--completed-ordinal', str(o)] for o in range(15, 23)], []) +
                           ['--novelty-evidence-json', str(ev_p), '--ledger', str(ledger_p),
                            '--previous-batch-record', str(prior)],
                           capture_output=True, text=True)
        out = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}
        if out.get('status') == 'BATCH_COMPLETE':
            print('CLI --previous-batch-record happy path: PASS')
        else:
            FAILS.append('cli happy'); print('CLI happy: FAIL', r.stderr[-300:])

    print(f'ALL PASS' if not FAILS else f'FAILURES: {FAILS}')
    sys.exit(1 if FAILS else 0)

if __name__ == '__main__':
    main()
