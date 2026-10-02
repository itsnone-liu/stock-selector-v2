#!/usr/bin/env python3
"""BATCH-H-RECOVERY-ERRATUM-1 recovery evidence tests (synthetic multi-frame zstd)."""
import ctypes, hashlib, json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_batch_h_recovery_novelty as rec

PASS = []
def check(name, fn):
    fn(); PASS.append(name); print('PASS', name)

def digest(raw): return hashlib.sha256(raw).hexdigest()
def canon(obj): return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

# --- synthetic zstd multi-frame writer (mirrors harness append-form files) ---
_lib = ctypes.CDLL('/lib/x86_64-linux-gnu/libzstd.so.1')
_lib.ZSTD_compressBound.restype = ctypes.c_size_t
_lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
_lib.ZSTD_compress.restype = ctypes.c_size_t
_lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]

def zstd_frame(data: bytes, level=3) -> bytes:
    cap = _lib.ZSTD_compressBound(len(data))
    dst = ctypes.create_string_buffer(cap)
    src = ctypes.create_string_buffer(data)
    n = _lib.ZSTD_compress(ctypes.cast(dst, ctypes.c_void_p), cap, ctypes.cast(src, ctypes.c_void_p), len(data), level)
    if n == 0: raise RuntimeError('ZSTD_compress failed')
    return dst.raw[:n]

def write_frames(path, parts):
    blob = b''.join(zstd_frame(p.encode()) for p in parts)
    Path(path).write_bytes(blob); return blob

def make_ledger(path, rows_spec):
    """rows_spec: list of (ordinal, operation, run_id, session_id)."""
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

def build_world(td, ids_after_marker=True, premature=False):
    Path(td).mkdir(parents=True, exist_ok=True)
    live = Path(td) / 'session.jsonl.zstd'
    sess = json.dumps({'type': 'session', 'id': 'session-TESTEXEC', 'origin': None,
                       'parentSession': None, 'createdAt': 1790909631696})
    head = sess + '\n' + '{"type":"user","text":"earlier session content"}\n'
    m1 = 'python3 scripts/_h3_reviewer_tool.py --ordinal 7 NEXT_REVEAL deadbeef\n'
    found_ids = 'reviewer_run_id=reviewer_t1 reviewer_session_id=subagent-t1\n'
    m2 = 'python3 scripts/_h3_reviewer_tool.py --ordinal 7 ANNOTATION cafebabe\n'
    early = 'subagent-t1 premature echo\n' if premature else 'plain chatter\n'
    boundary = 'user ruling: APPEND_ONLY_RECOVERED_PREFIX approved\n'
    tail = 'analysis echo reviewer_t2 subagent-t2 NO_OCCURRENCE\n'
    p1 = head + (early if premature else 'chatter0\n')
    p2 = m1 + found_ids + m2
    p3 = boundary + tail
    write_frames(live, [p1, p2, p3])
    return live

def main():
    td = tempfile.mkdtemp(prefix='csr8-rec-')

    def happy():
        live = build_world(td + '/a')
        ledger = Path(td) / 'a' / 'reviews.jsonl'
        make_ledger(ledger, [(7, 'NEXT_REVEAL', 'reviewer_t1', 'subagent-t1'),
                             (7, 'ANNOTATION', 'reviewer_t2', 'subagent-t2')])
        ev = rec.generate_recovery_evidence(
            str(ledger), str(live), td + '/a/frozen/session.jsonl.zstd', 'session-TESTEXEC',
            7, 7, td + '/a/recovery_evidence.json', td + '/a/anchor.json')
        assert ev['rows_checked'] == 2
        r0, r1 = ev['rows']
        assert isinstance(r0['run_id_first_occurrence_decoded_offset'], int)
        assert r0['spawn_marker_offset'] < r0['run_id_first_occurrence_decoded_offset']
        assert r0['run_id_absent_before_cutoff'] and r0['session_id_absent_before_cutoff']
        assert r1['run_id_first_occurrence_decoded_offset'] == rec.NO_OCCURRENCE
        assert r1['session_id_first_occurrence_decoded_offset'] == rec.NO_OCCURRENCE
        assert r1['recovered_prefix_cutoff'] == ev['source']['domain_bytes']
        v = rec.verify_recovery_evidence(td + '/a/recovery_evidence.json', str(ledger))
        assert v['status'] == 'PASS' and v['rows_checked'] == 2
    check('generate+verify happy path incl NO_OCCURRENCE row', happy)

    def tamper():
        p = Path(td) / '/a/recovery_evidence.json'  # 0400; tamper a copy instead
        ev = json.loads(Path(td + '/a/recovery_evidence.json').read_text())
        ev['rows'][0]['recovered_prefix_cutoff'] += 5
        tp = Path(td) / 'tampered.json'; tp.write_text(canon(ev))
        try:
            rec.verify_recovery_evidence(str(tp), td + '/a/reviews.jsonl'); raise AssertionError('tamper accepted')
        except ValueError as e:
            assert 're-derivation mismatch' in str(e) or 'mismatch' in str(e)
    check('tampered evidence rejected by verifier', tamper)

    def premature():
        live = build_world(td + '/b', premature=True)
        ledger = Path(td) / 'b' / 'reviews.jsonl'
        make_ledger(ledger, [(7, 'NEXT_REVEAL', 'reviewer_t1', 'subagent-t1')])
        try:
            rec.generate_recovery_evidence(str(ledger), str(live), td + '/b/frozen/session.jsonl.zstd',
                                           'session-TESTEXEC', 7, 7,
                                           td + '/b/ev.json', td + '/b/anchor.json')
            raise AssertionError('premature ID accepted')
        except ValueError as e:
            assert 'does not precede' in str(e)
    check('ID before spawn marker fails generate (fail-closed)', premature)

    def live_growth():
        # evidence stays verifiable regardless of live file later growth
        v = rec.verify_recovery_evidence(td + '/a/recovery_evidence.json', td + '/a/reviews.jsonl')
        assert v['status'] == 'PASS'
        live = Path(td + '/a/session.jsonl.zstd')
        with open(live, 'ab') as f: f.write(zstd_frame('late append reviewer_t1 subagent-t1\n'.encode()))
        v2 = rec.verify_recovery_evidence(td + '/a/recovery_evidence.json', td + '/a/reviews.jsonl')
        assert v2['status'] == 'PASS'
    check('live-file growth does not disturb frozen-capture verification', live_growth)

    def chain_break():
        src = Path(td + '/a/reviews.jsonl').read_text().splitlines()
        rows = [json.loads(x) for x in src]
        rows[1]['prev_review_hash'] = '0' * 64
        p = Path(td) / 'broken.jsonl'; p.write_text('\n'.join(canon(r) for r in rows) + '\n')
        try:
            rec.verify_recovery_evidence(td + '/a/recovery_evidence.json', str(p))
            raise AssertionError('chain break accepted')
        except ValueError as e:
            assert 'ledger' in str(e)
    check('ledger chain break rejected', chain_break)

    def frozen_hash_drift():
        # a rewritten frozen copy (hash mismatch) must fail
        alt = Path(td + '/a/frozen2'); alt.mkdir(parents=True, exist_ok=True)
        ev_txt = json.loads(Path(td + '/a/recovery_evidence.json').read_text())
        src = Path(ev_txt['source']['frozen_path'])
        live = Path(td + '/a/session.jsonl.zstd')
        with open(live, 'ab') as f: f.write(zstd_frame('extra\n'.encode()))
        blob = live.read_bytes()
        fp = alt / 'session.jsonl.zstd'; fp.write_bytes(blob)
        ev2 = dict(ev_txt); ev2['source'] = dict(ev_txt['source']); ev2['source']['frozen_path'] = str(fp)
        ev2['source']['raw_zstd_sha256'] = digest(blob); ev2['source']['raw_zstd_bytes'] = len(blob)
        tp = Path(td) / 'drift.json'; tp.write_text(canon(ev2))
        try:
            rec.verify_recovery_evidence(str(tp), td + '/a/reviews.jsonl')
            raise AssertionError('decoded mismatch not caught')
        except ValueError as e:
            assert 'decoded transcript hash/length mismatch' in str(e)
    check('frozen/decoded hash drift rejected', frozen_hash_drift)

    print('ALL %d PASS' % len(PASS))

if __name__ == '__main__':
    main()
