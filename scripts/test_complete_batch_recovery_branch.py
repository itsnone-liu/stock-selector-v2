#!/usr/bin/env python3
"""complete_batch_recovery / capture_pre_spawn_dsh_snapshot / derive_previous_ids tests."""
import ctypes, hashlib, json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_batch_h_recovery_novelty as rec
import csr8_batch_h_orchestrator as orch

PASS = []
def check(name, fn):
    fn(); PASS.append(name); print('PASS', name)

def digest(raw): return hashlib.sha256(raw).hexdigest()
def canon(obj): return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

_lib = ctypes.CDLL('/lib/x86_64-linux-gnu/libzstd.so.1')
_lib.ZSTD_compressBound.restype = ctypes.c_size_t
_lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
_lib.ZSTD_compress.restype = ctypes.c_size_t
_lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]

def zstd_frame(data: bytes) -> bytes:
    cap = _lib.ZSTD_compressBound(len(data))
    dst = ctypes.create_string_buffer(cap); src = ctypes.create_string_buffer(data)
    n = _lib.ZSTD_compress(ctypes.cast(dst, ctypes.c_void_p), cap, ctypes.cast(src, ctypes.c_void_p), len(data), 3)
    if n == 0: raise RuntimeError('ZSTD_compress failed')
    return dst.raw[:n]

def make_ledger(path, rows_spec):
    rows = []; prev = None
    for i, (o, op, rid, sid) in enumerate(rows_spec):
        body = {'sequence': i, 'ordinal': o, 'operation': op, 'state': 'APPROVE',
                'campaign_id': 'hc-test', 'created_at': '2026-10-02T00:00:00Z',
                'input_commitment_sha256': hashlib.sha256(op.encode()).hexdigest(),
                'reviewer_run_id': rid, 'reviewer_session_id': sid}
        if prev is not None: body['prev_review_hash'] = prev
        h = digest(canon(body).encode()); body = dict(body); body['review_hash'] = h
        rows.append(body); prev = h
    Path(path).write_text('\n'.join(canon(r) for r in rows) + '\n')
    return rows

def build(td):
    Path(td).mkdir(parents=True, exist_ok=True)
    live = Path(td) / 'session.jsonl.zstd'
    sess = json.dumps({'type': 'session', 'id': 'session-TESTEXEC', 'origin': None,
                       'parentSession': None, 'createdAt': 1})
    mid = []
    spec = []
    for i, o in enumerate(range(7, 15)):
        rid, sid = 'reviewer_t%d' % i, 'subagent-t%d' % i
        mid.append('python3 scripts/_h3_reviewer_tool.py --ordinal %d NEXT_REVEAL %s\n'
                   'reviewer_run_id=%s reviewer_session_id=%s\n' % (o, 'a' * 8, rid, sid))
        spec.append((o, 'NEXT_REVEAL', rid, sid))
    p1 = sess + '\nchatter\n'
    p2 = ''.join(mid)
    p3 = 'APPEND_ONLY_RECOVERED_PREFIX ruling\nlater analysis echo\n'
    live.write_bytes(zstd_frame(p1.encode()) + zstd_frame(p2.encode()) + zstd_frame(p3.encode()))
    ledger = Path(td) / 'reviews.jsonl'
    make_ledger(ledger, spec)
    return live, ledger

def main():
    td = tempfile.mkdtemp(prefix='csr8-cbr-')

    def happy_and_record():
        live, ledger = build(td + '/w1')
        ev = rec.generate_recovery_evidence(str(ledger), str(live), td + '/w1/frozen/session.jsonl.zstd',
                                            'session-TESTEXEC', 7, 14, td + '/w1/ev.json', td + '/w1/anchor.json')
        rec_ = orch.complete_batch_recovery(7, list(range(7, 15)), td + '/w1/ev.json', str(ledger))
        assert rec_['status'] == 'BATCH_COMPLETE'
        assert rec_['evidence_mode'] == 'APPEND_ONLY_RECOVERED_PREFIX'
        assert rec_['realtime_pre_spawn_capture'] == 'NOT_AVAILABLE'
        assert rec_['novelty_gate']['rows_checked'] == 8
        Path(td + '/w1/record.json').write_text(canon(rec_))
        ids = orch.derive_previous_ids(td + '/w1/record.json')
        assert len(ids) == 16 and ids[0] == 'reviewer_t0'
    check('complete_batch_recovery happy path + derive_previous_ids', happy_and_record)

    def coverage_gap():
        live, ledger = build(td + '/w2')
        ev = rec.generate_recovery_evidence(str(ledger), str(live), td + '/w2/frozen/session.jsonl.zstd',
                                            'session-TESTEXEC', 7, 14, td + '/w2/ev.json', td + '/w2/anchor.json')
        # add one more ledger row in batch range AFTER evidence generation -> coverage gap
        spec=[(o, 'NEXT_REVEAL', 'reviewer_t%d' % (o-7), 'subagent-t%d' % (o-7)) for o in range(7, 15)] + [(14, 'SEAL', 'reviewer_t9', 'subagent-t9')]
        make_ledger(Path(str(ledger) + '.x'), spec)
        try:
            orch.complete_batch_recovery(7, list(range(7, 15)), td + '/w2/ev.json', str(ledger) + '.x')
            raise AssertionError('coverage gap accepted')
        except ValueError as e:
            assert ('re-derivation mismatch' in str(e) or 'coverage' in str(e)
                    or 'spawn marker absent' in str(e) or 'missing reviewer IDs' in str(e))
    check('coverage gap (new ledger row) rejected', coverage_gap)

    def non_contiguous():
        live, ledger = build(td + '/w3')
        ev = rec.generate_recovery_evidence(str(ledger), str(live), td + '/w3/frozen/session.jsonl.zstd',
                                            'session-TESTEXEC', 7, 14, td + '/w3/ev.json', td + '/w3/anchor.json')
        try:
            orch.complete_batch_recovery(7, [7], td + '/w3/ev.json', str(ledger))
            raise AssertionError('non-contiguous accepted')
        except ValueError as e:
            assert 'non-contiguous' in str(e) or 'eight' in str(e)
    check('non-contiguous batch rejected', non_contiguous)

    def dsh_capture():
        live, ledger = build(td + '/w4')
        snap, anch = orch.capture_pre_spawn_dsh_snapshot(str(live), 'session-TESTEXEC',
                                                         td + '/w4/snap.json', td + '/w4/anchor.json',
                                                         td + '/w4/frozen/session.jsonl.zstd')
        assert snap['snapshot_version'] == orch.DSH_SNAPSHOT_VERSION
        assert snap['pre_spawn_sequence_cutoff'] == snap['raw_zstd_bytes'] == Path(td + '/w4/frozen/session.jsonl.zstd').stat().st_size
        assert 'subagent-t1' in snap['transcript_prefix']  # t1 appeared in transcript before capture: present is fine, capture is about freezing state
        # O_EXCL: second capture to same paths must fail
        try:
            orch.capture_pre_spawn_dsh_snapshot(str(live), 'session-TESTEXEC',
                                                td + '/w4/snap.json', td + '/w4/anchor2.json',
                                                td + '/w4/frozen/session.jsonl.zstd')
            raise AssertionError('O_EXCL violated')
        except FileExistsError:
            pass
        # wrong executor session id fails closed
        try:
            orch.capture_pre_spawn_dsh_snapshot(str(live), 'session-OTHER',
                                                td + '/w4/snap2.json', td + '/w4/anchor3.json',
                                                td + '/w4/frozen2/session.jsonl.zstd')
            raise AssertionError('session mismatch accepted')
        except ValueError as e:
            assert 'session' in str(e)
    check('capture_pre_spawn_dsh_snapshot: EOF pin, O_EXCL, session binding', dsh_capture)

    def eof_rule():
        live, ledger = build(td + '/w5')
        eof = live.stat().st_size
        try:
            orch.capture_pre_spawn_dsh_snapshot(str(live), 'session-TESTEXEC',
                                                td + '/w5/snap.json', td + '/w5/anchor.json',
                                                td + '/w5/frozen/session.jsonl.zstd',
                                                sequence_cutoff=eof - 1)
            raise AssertionError('non-EOF cutoff accepted')
        except ValueError as e:
            assert 'EOF' in str(e)
    check('FIX6 EOF rule enforced on zstd source', eof_rule)

    print('ALL %d PASS' % len(PASS))

if __name__ == '__main__':
    main()
