#!/usr/bin/env python3
"""BATCH-H-RECOVERY-ERRATUM-1: append-only recovered-prefix novelty evidence.

Scope: ordinal 7-14 ONLY (first Batch H batch), per user ruling 2026-10-02.

Realtime pre-spawn capture (FIX5/FIX6 snapshot form) was NOT performed for this
batch and is NOT fabricated here.  Instead this module:

  1. freezes a byte-exact copy of the DSH executor transcript
     (session.jsonl.zstd, quiescent atomic copy, sha256-pinned, 0400);
  2. decodes it with the frozen H0 multi-frame zstd decoder;
  3. for EVERY reviewer ledger row of the batch (full coverage, no sampling)
     derives, inside the pre-approval domain:
       - reviewer run_id / session_id first-occurrence decoded-byte offsets
         (or NO_OCCURRENCE_IN_COMPLETE_TRANSCRIPT when genuinely absent),
       - recovered_prefix_cutoff = min(found offsets),
       - recovered_prefix_sha256 + absence booleans before the cutoff,
       - the row's reviewer spawn marker and marker<first-occurrence ordering;
  4. verifies all of the above by independent re-derivation from the frozen
     copy before complete_batch_recovery may report BATCH_COMPLETE.

Empirical note (documented in the erratum): the live transcript file is NOT
byte-append-only across turn boundaries (late record insertion at
chronological positions was observed).  Therefore verification anchors on the
frozen capture + record ordering, never on live-file byte-prefix stability.
"""
import argparse, ctypes, hashlib, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from csr8_phase_h_entry_gate import _zstd_lib                     # frozen H0 decoder
from csr8_batch_h_orchestrator import load_ledger                 # ledger chain validation

RECOVERY_VERSION = 'csr8-batch-h-recovery-novelty-v1'
ERRATUM_ID = 'BATCH-H-RECOVERY-ERRATUM-1'
EVIDENCE_MODE = 'APPEND_ONLY_RECOVERED_PREFIX'
REALTIME_CAPTURE = 'NOT_AVAILABLE'
ATTESTATION_LEVEL = 'PLATFORM_OPAQUE_SUBAGENT'
NO_OCCURRENCE = 'NO_OCCURRENCE_IN_COMPLETE_TRANSCRIPT'
BOUNDARY_MARKER = 'APPEND_ONLY_RECOVERED_PREFIX'   # first uttered after batch completion (recovery contract approval)
TOOL_MARKER = 'scripts/_h3_reviewer_tool.py --ordinal {ordinal} {operation}'
CORRECTION_MARKER = 'scripts/_h3_review_correction.py --ordinal {ordinal}'
MAX_DECODED = 512 * 1024 * 1024
ENTRY_GATE = Path(__file__).resolve().parent / 'csr8_phase_h_entry_gate.py'

def canon(obj): return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def digest(raw): return hashlib.sha256(raw).hexdigest()

# ---------------------------------------------------------------- transcript

def decode_transcript_bytes(raw, max_total=MAX_DECODED):
    """Multi-frame zstd -> exact decoded bytes (frozen H0 decoder, fail-closed)."""
    lib, InB, OutB = _zstd_lib()
    src = ctypes.create_string_buffer(raw)
    zds = lib.ZSTD_createDStream()
    out = bytearray(); chunk = 1 << 20
    obuf = ctypes.create_string_buffer(chunk)
    inb = InB(ctypes.cast(src, ctypes.c_void_p), len(raw), 0)
    guard = 0
    try:
        while inb.pos < len(raw):
            guard += 1
            if guard > 65536: raise ValueError('transcript decompression did not converge')
            lib.ZSTD_initDStream(zds)
            while inb.pos < len(raw):
                ob = OutB(ctypes.cast(obuf, ctypes.c_void_p), chunk, 0)
                ret = lib.ZSTD_decompressStream(zds, ctypes.byref(ob), ctypes.byref(inb))
                if ob.pos:
                    out += obuf.raw[:ob.pos]
                    if len(out) > max_total: raise ValueError('transcript exceeds decode bound')
                if ret == 0: break
    finally:
        lib.ZSTD_freeDStream(zds)
    return bytes(out)

def freeze_transcript(live_path, frozen_path, attempts=5):
    """Quiescent atomic byte-exact copy: read->stat->read->compare, then O_EXCL 0400."""
    live = Path(live_path)
    if not live.is_file(): raise ValueError('live transcript source required')
    for _ in range(attempts):
        st1 = os.stat(live); b1 = live.read_bytes()
        st2 = os.stat(live); b2 = live.read_bytes()
        if b1 == b2 and st1.st_size == st2.st_size == len(b1):
            out = Path(frozen_path); out.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try: os.write(fd, b1); os.fsync(fd)
            finally: os.close(fd)
            os.chmod(out, 0o400)
            d = os.open(out.parent, os.O_RDONLY); os.fsync(d); os.close(d)
            return {'live_path': str(live.resolve()), 'live_device': st1.st_dev,
                    'live_inode': st1.st_ino, 'live_mtime': st1.st_mtime,
                    'captured_at_unix': time.time(),
                    'frozen_path': str(out.resolve()), 'raw_zstd_sha256': digest(b1),
                    'raw_zstd_bytes': len(b1)}
        time.sleep(0.2)
    raise ValueError('transcript not quiescent during freeze')

# ------------------------------------------------------------------ evidence

def _pin_session_record(domain_bytes):
    sess = None
    for line in domain_bytes.split(b'\n'):
        line = line.strip()
        if not line: continue
        try: rec = json.loads(line)
        except ValueError: continue
        if rec.get('type') == 'session':
            sess = rec
    if sess is None or not sess.get('id'):
        raise ValueError('session record not found in transcript domain')
    return {'session_id': sess.get('id'), 'origin': sess.get('origin'),
            'parent_session': sess.get('parentSession'), 'created_at_ms': sess.get('createdAt')}

def _row_marker(row):
    if row['operation'] == 'ANNOTATION_CORRECTION':
        return CORRECTION_MARKER.format(ordinal=row['ordinal'])
    return TOOL_MARKER.format(ordinal=row['ordinal'], operation=row['operation'])

def derive_rows(batch_rows, domain, decoded_length):
    """Per-row first-occurrence derivation inside the pre-approval domain."""
    entries = []; ids = []
    for row in batch_rows:
        rid, sid = row['reviewer_run_id'], row['reviewer_session_id']
        if not rid or not sid: raise ValueError('ledger row missing reviewer IDs: seq %s' % row['sequence'])
        ro = domain.find(rid.encode()); so = domain.find(sid.encode())
        run_status = ro if ro >= 0 else NO_OCCURRENCE
        sess_status = so if so >= 0 else NO_OCCURRENCE
        found = [o for o in (ro, so) if o >= 0]
        cutoff = min(found) if found else decoded_length
        prefix = domain[:cutoff]
        run_absent = prefix.find(rid.encode()) < 0
        sess_absent = prefix.find(sid.encode()) < 0
        if not (run_absent and sess_absent): raise ValueError('absence invariant broken: seq %s' % row['sequence'])
        marker = _row_marker(row); mo = domain.find(marker.encode())
        if mo < 0: raise ValueError('spawn marker absent: seq %s' % row['sequence'])
        if found and mo >= min(found):
            raise ValueError('spawn marker does not precede ID occurrence: seq %s' % row['sequence'])
        entries.append({
            'ordinal': row['ordinal'], 'operation': row['operation'],
            'ledger_sequence': row['sequence'], 'review_hash': row['review_hash'],
            'reviewer_run_id': rid, 'reviewer_session_id': sid,
            'executor_session_id': None,  # filled by caller
            'run_id_first_occurrence_decoded_offset': run_status,
            'session_id_first_occurrence_decoded_offset': sess_status,
            'recovered_prefix_cutoff': cutoff,
            'recovered_prefix_sha256': digest(prefix),
            'recovered_prefix_bytes': cutoff,
            'run_id_absent_before_cutoff': run_absent,
            'session_id_absent_before_cutoff': sess_absent,
            'spawn_marker': marker, 'spawn_marker_offset': mo,
            'spawn_marker_precedes_ids': True})
        ids += [rid, sid]
    return entries, ids

def generate_recovery_evidence(ledger_path, live_transcript, frozen_path,
                               executor_session_id, batch_start, batch_end,
                               evidence_path, anchor_path, previous_ids=()):
    prov = freeze_transcript(live_transcript, frozen_path)
    raw = Path(prov['frozen_path']).read_bytes()
    if digest(raw) != prov['raw_zstd_sha256']: raise ValueError('frozen copy hash drift')
    decoded = decode_transcript_bytes(raw)
    boundary = decoded.find(BOUNDARY_MARKER.encode())
    if boundary < 0: raise ValueError('recovery boundary marker absent')
    domain = decoded[:boundary]
    sess = _pin_session_record(domain)
    if sess['session_id'] != executor_session_id:
        raise ValueError('transcript session %s != executor session %s' % (sess['session_id'], executor_session_id))
    rows = load_ledger(ledger_path)
    batch_rows = [r for r in rows if batch_start <= r.get('ordinal', -1) <= batch_end]
    if not batch_rows: raise ValueError('no ledger rows in batch range')
    entries, ids = derive_rows(batch_rows, domain, len(domain))
    for e in entries: e['executor_session_id'] = executor_session_id
    max_off = max([e['spawn_marker_offset'] for e in entries] +
                  [o for e in entries for o in (e['run_id_first_occurrence_decoded_offset'],
                                                e['session_id_first_occurrence_decoded_offset']) if isinstance(o, int)])
    if max_off >= boundary: raise ValueError('marker/ID offset past recovery boundary')
    if len(ids) != len(set(ids)): raise ValueError('reviewer duplicate IDs in batch')
    prev = list(previous_ids)
    if set(prev) & set(ids): raise ValueError('reviewer previous-batch overlap')
    ev = {
        'evidence_version': RECOVERY_VERSION, 'erratum_id': ERRATUM_ID,
        'evidence_mode': EVIDENCE_MODE, 'realtime_pre_spawn_capture': REALTIME_CAPTURE,
        'attestation_level': ATTESTATION_LEVEL, 'generated_at_unix': time.time(),
        'batch_start': batch_start, 'batch_end': batch_end, 'rows_checked': len(entries),
        'coverage': 'ALL_LEDGER_ROWS_IN_BATCH_RANGE', 'executor_session_id': executor_session_id,
        'transcript_session': sess,
        'source': {
            'live_path': prov['live_path'], 'live_device': prov['live_device'],
            'live_inode': prov['live_inode'], 'live_mtime': prov['live_mtime'],
            'frozen_path': prov['frozen_path'],
            'raw_zstd_sha256': prov['raw_zstd_sha256'], 'raw_zstd_bytes': prov['raw_zstd_bytes'],
            'decoder': {
                'decoder': 'csr8_phase_h_entry_gate._zstd_lib + csr8_batch_h_recovery_novelty.decode_transcript_bytes',
                'decoder_module_sha256': digest(Path(__file__).read_bytes()),
                'entry_gate_sha256': digest(ENTRY_GATE.read_bytes())},
            'decoded_sha256': digest(decoded), 'decoded_bytes': len(decoded),
            'boundary_marker': BOUNDARY_MARKER, 'boundary_offset': boundary,
            'domain_bytes': len(domain), 'domain_sha256': digest(domain),
            'boundary_semantics': 'transcript state at recovery-contract approval; executor self-echoes after this point are excluded by construction'},
        'previous_ids': prev, 'rows': entries,
        'summary': {'novelty': True, 'duplicate_ids': False, 'previous_overlap': False,
                    'no_occurrence_labels': sum(1 for e in entries for o in
                        (e['run_id_first_occurrence_decoded_offset'], e['session_id_first_occurrence_decoded_offset'])
                        if o == NO_OCCURRENCE)}}
    out = Path(evidence_path); out.parent.mkdir(parents=True, exist_ok=True)
    data = canon(ev).encode()
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try: os.write(fd, data); os.fsync(fd)
    finally: os.close(fd)
    os.chmod(out, 0o400)
    anch = {'anchor_version': 'csr8-batch-h-recovery-anchor-v1', 'erratum_id': ERRATUM_ID,
            'evidence_sha256': digest(data), 'frozen_transcript_sha256': prov['raw_zstd_sha256'],
            'domain_sha256': digest(domain), 'executor_session_id': executor_session_id}
    ap = Path(anchor_path); fd = os.open(ap, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try: os.write(fd, canon(anch).encode()); os.fsync(fd)
    finally: os.close(fd)
    os.chmod(ap, 0o400)
    return ev

# ------------------------------------------------------------------ verifier

def verify_recovery_evidence(evidence_path, ledger_path, previous_ids=()):
    """Independent re-derivation from the frozen capture + ledger. Fail-closed."""
    ev = json.loads(Path(evidence_path).read_text())
    if ev.get('evidence_version') != RECOVERY_VERSION or ev.get('erratum_id') != ERRATUM_ID:
        raise ValueError('unknown recovery evidence version')
    if ev.get('evidence_mode') != EVIDENCE_MODE or ev.get('realtime_pre_spawn_capture') != REALTIME_CAPTURE:
        raise ValueError('recovery evidence mode mismatch')
    frozen = Path(ev['source']['frozen_path'])
    if not frozen.is_file(): raise ValueError('frozen transcript capture missing')
    raw = frozen.read_bytes()
    if digest(raw) != ev['source']['raw_zstd_sha256'] or len(raw) != ev['source']['raw_zstd_bytes']:
        raise ValueError('frozen transcript hash/length mismatch')
    decoded = decode_transcript_bytes(raw)
    if digest(decoded) != ev['source']['decoded_sha256'] or len(decoded) != ev['source']['decoded_bytes']:
        raise ValueError('decoded transcript hash/length mismatch')
    boundary = decoded.find(ev['source']['boundary_marker'].encode())
    if boundary != ev['source']['boundary_offset']: raise ValueError('recovery boundary moved')
    domain = decoded[:boundary]
    if digest(domain) != ev['source']['domain_sha256'] or len(domain) != ev['source']['domain_bytes']:
        raise ValueError('domain hash/length mismatch')
    sess = _pin_session_record(domain)
    if sess != ev['transcript_session']: raise ValueError('transcript session pin mismatch')
    if sess['session_id'] != ev['executor_session_id']: raise ValueError('executor session mismatch')
    rows = load_ledger(ledger_path)   # full hash-chain validation
    batch_rows = [r for r in rows if ev['batch_start'] <= r.get('ordinal', -1) <= ev['batch_end']]
    entries, ids = derive_rows(batch_rows, domain, len(domain))
    if len(entries) != ev['rows_checked']: raise ValueError('row coverage changed')
    for e_new, e_old in zip(entries, ev['rows']):
        for k, v in e_new.items():
            if k == 'executor_session_id': v = ev['executor_session_id']
            if e_old.get(k) != v: raise ValueError('re-derivation mismatch at seq %s field %s' % (e_new['ledger_sequence'], k))
    if len(ids) != len(set(ids)): raise ValueError('reviewer duplicate IDs')
    if set(previous_ids) & set(ids) or set(ev.get('previous_ids', [])) & set(ids):
        raise ValueError('reviewer previous-batch overlap')
    return {'status': 'PASS', 'erratum_id': ERRATUM_ID, 'evidence_mode': EVIDENCE_MODE,
            'realtime_pre_spawn_capture': REALTIME_CAPTURE, 'attestation_level': ATTESTATION_LEVEL,
            'batch_start': ev['batch_start'], 'batch_end': ev['batch_end'],
            'rows_checked': len(entries), 'novelty': True, 'previous_overlap': False,
            'rows': [{'ordinal': e['ordinal'], 'operation': e['operation'],
                      'ledger_sequence': e['ledger_sequence'], 'review_hash': e['review_hash'],
                      'reviewer_run_id': e['reviewer_run_id'],
                      'reviewer_session_id': e['reviewer_session_id'],
                      'recovered_prefix_cutoff': e['recovered_prefix_cutoff'],
                      'run_id_absent_before_cutoff': e['run_id_absent_before_cutoff'],
                      'session_id_absent_before_cutoff': e['session_id_absent_before_cutoff'],
                      'run_id_first_occurrence_decoded_offset': e['run_id_first_occurrence_decoded_offset'],
                      'session_id_first_occurrence_decoded_offset': e['session_id_first_occurrence_decoded_offset']}
                     for e in entries],
            'frozen_transcript_sha256': ev['source']['raw_zstd_sha256'],
            'domain_sha256': ev['source']['domain_sha256'],
            'evidence_path': str(Path(evidence_path).resolve()),
            'verified_by_independent_rederivation': True}

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument('--generate', action='store_true'); sub.add_argument('--verify', action='store_true')
    ap.add_argument('--ledger', required=True); ap.add_argument('--evidence', required=True)
    ap.add_argument('--anchor'); ap.add_argument('--live-transcript'); ap.add_argument('--frozen-transcript')
    ap.add_argument('--executor-session-id'); ap.add_argument('--batch-start', type=int, required=True)
    ap.add_argument('--batch-end', type=int, required=True); ap.add_argument('--previous-id', action='append', default=[])
    a = ap.parse_args()
    if a.generate:
        if not (a.live_transcript and a.frozen_transcript and a.executor_session_id and a.anchor):
            raise SystemExit('generate requires --live-transcript --frozen-transcript --executor-session-id --anchor')
        ev = generate_recovery_evidence(a.ledger, a.live_transcript, a.frozen_transcript,
                                        a.executor_session_id, a.batch_start, a.batch_end,
                                        a.evidence, a.anchor, a.previous_id)
        print(json.dumps({'status': 'GENERATED', 'rows_checked': ev['rows_checked'],
                          'frozen_transcript_sha256': ev['source']['raw_zstd_sha256'],
                          'domain_sha256': ev['source']['domain_sha256']}, sort_keys=True))
    else:
        print(json.dumps(verify_recovery_evidence(a.evidence, a.ledger, a.previous_id),
                         sort_keys=True, separators=(',', ':')))

if __name__ == '__main__':
    main()
