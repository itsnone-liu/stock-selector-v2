#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C C2 — synthetic REVEAL/SEAL hash-chain state machine dry run.

C2-AUDIT-FIX1 (user audit):
  1. exact-byte binding — every REVEAL stores the revealed packet bytes and
     every SEAL stores the annotation receipt bytes in an archive next to the
     log; the replay verifier re-hashes the ACTUAL bytes and compares them to
     the payload hash. A hash recorded in the chain is thereby bound to the
     exact bytes it claims.
  2. semantic injections cascade-recompute event hashes + head from the
     mutation point, so rejection can only come from the TARGET gate.
  3. receipt-hash mutation added (cascade-recomputed chain still fails).
  4. head anchor is MANDATORY when check_head=True: missing head -> FAIL.
     Scope note (honest wording): the anchor proves the log was not truncated
     RELATIVE TO a trusted, not-simultaneously-rewritten anchor; it is not
     self-certifying against an attacker who rewrites log+head together.
  5. append() verifies the existing chain + head BEFORE accepting any new
     event — state transitions only build on a verified predecessor state.
  Fork semantics (linear append-only log): two events claiming the same
  parent -> the second violates parent continuity -> FAIL-CLOSED.

C2 scope (user ruling): SYNTHETIC FIXTURE ONLY. No real case reveal, no real
annotation, no hidden-plan observation window. This module does not import
C1 code and does not read the real secret domain.
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C2DIR = ROOT / 'output/research/csr/08_pilot_cases/phase_c/c2_dryrun'
GENESIS = '0' * 64
REVEAL, SEAL = 'REVEAL_PACKET', 'SEAL_ANNOTATION'


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'))


def sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    print(f'FAIL-CLOSED: {msg}')
    sys.exit(1)


# ---------------- synthetic fixture (C2-local, never the real secret) -------
FIXTURE_SALT = 'c2-dryrun-fixture-salt-not-the-real-one'
SYNTH_CASES = ['C2_SYNTH_A', 'C2_SYNTH_B']
SYNTH_TS = ['2099-01-02', '2099-01-03', '2099-01-06', '2099-01-07']  # grid


def synth_ocid(case):
    import hmac
    return hmac.new(FIXTURE_SALT.encode(), case.encode(),
                    'sha256').hexdigest()


def synth_packet_id(case, T):
    return sha(f'{synth_ocid(case)}|{T}'.encode())


def synth_packet_bytes(case, T):
    return f'SYNTH|{case}|{T}|packet-body-v2'.encode()


def synth_receipt(case, T):
    return canon({'annotator': 'SYNTH', 'T': T, 'opaque_case_id':
                  synth_ocid(case), 'answers': {'q1': 'x'}}).encode()


# ---------------- hash-chain sealing log ------------------------------------
class SealingLog:
    """Append-only linear hash chain with exact-byte binding archive."""

    def __init__(self, log_path, head_path=None, check_head=True):
        self.path = Path(log_path)
        self.head_path = Path(head_path) if head_path else \
            self.path.with_suffix('.head.json')
        self.check_head = check_head
        self.events = []

    # ---- persistence ----
    def load(self):
        self.events = []
        if not self.path.exists():
            return self
        for line in self.path.read_text().splitlines():
            if line.strip():
                self.events.append(json.loads(line))
        return self

    def head(self):
        return self.events[-1]['event_hash'] if self.events else GENESIS

    def bytes_path(self, ev):
        return self.path.parent / ev['payload']['bytes_ref']

    # ---- hashing ----
    def _write_head(self):
        self.head_path.write_text(canon(
            {'count': len(self.events), 'head_hash': self.head()}))

    # ---- append: verified-predecessor + structural gate + exact bytes ----
    def append(self, etype, payload, content_bytes):
        """Verify persisted predecessor and validate bytes before any write."""
        log_exists, head_exists = self.path.exists(), self.head_path.exists()
        if log_exists != head_exists:
            fail('persisted state incomplete: log/head must both exist or both '
                 'be absent before append')
        self.load()
        if log_exists and head_exists:
            # FIX1-5 + FIX2-F1: even an empty/truncated existing log is not
            # genesis; its trusted head must be replay-verified first.
            self.verify()
        self._gate(etype, payload)
        hash_key = 'packet_sha256' if etype == REVEAL else 'receipt_sha256'
        declared = payload.get(hash_key)
        if not declared or sha(content_bytes) != declared:
            fail(f'pre-write exact-byte binding failed for {etype}')
        seq = len(self.events)
        prev = self.head()
        bref = f'bytes/{etype.lower()}/{seq}.bin'
        payload = dict(payload, bytes_ref=bref)
        eh = event_hash(seq, prev, etype, payload)
        ev = {'sequence_no': seq, 'prev_event_hash': prev,
              'event_type': etype, 'payload': payload, 'event_hash': eh,
              'ts': time.time()}
        bp = self.path.parent / bref
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_bytes(content_bytes)
        with open(self.path, 'a') as f:
            f.write(canon(ev) + '\n')
        self.events.append(ev)
        self._write_head()
        return ev

    def _gate(self, etype, payload):
        """append-time legality; verify() re-proves everything independently."""
        key = (payload['opaque_case_id'], payload['T'])
        opens = [(e['payload']['opaque_case_id'], e['payload']['T'])
                 for e in self.events if e['event_type'] == REVEAL]
        seals = [(e['payload']['opaque_case_id'], e['payload']['T'])
                 for e in self.events if e['event_type'] == SEAL]
        if etype == REVEAL:
            if opens and opens[-1] not in seals:
                fail('REVEAL attempted while a previous REVEAL is unsealed')
            if key in opens:
                fail('duplicate REVEAL for (case,T)')
            case_ts = [t for (c, t) in opens
                       if c == payload['opaque_case_id']]
            if case_ts and max(case_ts) >= payload['T']:
                fail('out-of-order T for case (must strictly ascend)')
        elif etype == SEAL:
            if not opens or opens[-1] != key:
                fail('SEAL without a matching open REVEAL')
            if key in seals:
                fail('duplicate SEAL for (case,T)')
        else:
            fail(f'unknown event type {etype}')

    # ---- independent replay verification (zero trust in append time) ----
    def verify(self, check_head=None):
        if check_head is None:
            check_head = self.check_head
        if check_head and not self.head_path.exists():
            fail('head anchor MISSING (mandatory): cannot prove the log was '
                 'not truncated')
        prev = GENESIS
        seen_reveal, seen_seal, ts_prev = [], [], -1.0
        case_max_T = {}
        for i, ev in enumerate(self.events):
            p = ev['payload']
            if ev['sequence_no'] != i:
                fail(f'wrong sequence_no at event {i}')
            if ev['prev_event_hash'] != prev:
                fail(f'wrong prev_event_hash at event {i} '
                     f'(linear parent continuity)')
            expect_h = event_hash(i, prev, ev['event_type'], p)
            if ev['event_hash'] != expect_h:
                fail(f'tampered event or hash at event {i}')
            if ev['ts'] < ts_prev:
                fail(f'non-monotonic timestamp at event {i}')
            ts_prev = ev['ts']
            # FIX1-1: exact-byte binding — re-hash the ACTUAL archived bytes
            bp = self.bytes_path(ev)
            if not bp.exists():
                fail(f'archived bytes missing for event {i} '
                     f'({p.get("bytes_ref")})')
            actual = sha(bp.read_bytes())
            if ev['event_type'] == REVEAL:
                if actual != p['packet_sha256']:
                    fail(f'packet exact-byte binding violated at event {i}')
            elif ev['event_type'] == SEAL:
                if actual != p['receipt_sha256']:
                    fail(f'receipt exact-byte binding violated at event {i}')
            key = (p['opaque_case_id'], p['T'])
            if ev['event_type'] == REVEAL:
                if key in seen_reveal:
                    fail(f'duplicate REVEAL at event {i}')
                if seen_reveal and seen_reveal[-1] not in seen_seal:
                    fail(f'REVEAL at {i} precedes SEAL of previous REVEAL')
                if p['packet_id'] != sha(f"{p['opaque_case_id']}|{p['T']}"
                                         .encode()):
                    fail(f'wrong packet_id at event {i}')
                mt = case_max_T.get(p['opaque_case_id'])
                if mt is not None and mt >= p['T']:
                    fail(f'out-of-order T at event {i}')
                seen_reveal.append(key)
            elif ev['event_type'] == SEAL:
                if key not in seen_reveal:
                    fail(f'SEAL without prior REVEAL at event {i}')
                if key in seen_seal:
                    fail(f'duplicate SEAL at event {i}')
                if seen_reveal[-1] != key:
                    fail(f'SEAL at {i} does not close the open REVEAL')
                seen_seal.append(key)
                case_max_T[p['opaque_case_id']] = max(
                    case_max_T.get(p['opaque_case_id'], p['T']), p['T'])
            else:
                fail(f'unknown event type at {i}')
            prev = ev['event_hash']
        # sealed(T_i) precedes REVEAL(T_{i+1}): strict alternation proven above
        if check_head:
            h = json.loads(self.head_path.read_text())
            if h['count'] != len(self.events) or h['head_hash'] != self.head():
                fail('chain head anchor mismatch (truncation relative to '
                     'anchor)')
        return len(self.events)


# ---------------- normal-chain builder --------------------------------------
def build_normal_chain(log_path):
    log = SealingLog(log_path)
    n = 0
    for T in SYNTH_TS[:3]:
        for case in SYNTH_CASES:
            ocid = synth_ocid(case)
            pkt = synth_packet_bytes(case, T)
            log.append(REVEAL, {'opaque_case_id': ocid, 'T': T,
                                'packet_id': synth_packet_id(case, T),
                                'packet_sha256': sha(pkt)}, pkt)
            rec = synth_receipt(case, T)
            log.append(SEAL, {'opaque_case_id': ocid, 'T': T,
                              'receipt_sha256': sha(rec)}, rec)
            n += 2
    return n


# ---------------- injection machinery (on throwaway copies) -----------------
def read_events(log_path):
    return [json.loads(l) for l in Path(log_path).read_text().splitlines()
            if l.strip()]


def write_events(log_path, events):
    Path(log_path).write_text(
        '\n'.join(canon(e) for e in events) + '\n')


def event_hash(seq, prev, etype, payload):
    return sha(f'{seq}|{prev}|{etype}|{canon(payload)}'.encode())


def cascade_rehash(evs, from_idx):
    """Recompute sequence/prev/event_hash from from_idx (legalizing hashes so
    only the TARGET semantic gate can reject the injection)."""
    prev = evs[from_idx - 1]['event_hash'] if from_idx else GENESIS
    for i in range(from_idx, len(evs)):
        evs[i]['sequence_no'] = i
        evs[i]['prev_event_hash'] = prev
        evs[i]['event_hash'] = event_hash(
            i, prev, evs[i]['event_type'], evs[i]['payload'])
        prev = evs[i]['event_hash']
    return evs


def sync_head(head_path, evs):
    Path(head_path).write_text(canon(
        {'count': len(evs), 'head_hash': evs[-1]['event_hash']}))


DRY_LOG = C2DIR / 'dryrun_sealing_log.jsonl'
DRY_HEAD = C2DIR / 'dryrun_sealing_log.head.json'


def inject(label, mutate):
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        log = tdp / 'log.jsonl'
        head = tdp / 'log.head.json'
        shutil.copy(DRY_LOG, log)
        shutil.copy(DRY_HEAD, head)
        if (C2DIR / 'bytes').exists():
            shutil.copytree(C2DIR / 'bytes', tdp / 'bytes')
        outcome = mutate(tdp, log, head)
        if outcome == 'verify':
            rejected = False
            try:
                SealingLog(log, head).load().verify()
            except SystemExit:
                rejected = True
            if not rejected:
                fail(f'injection {label} was NOT rejected')
        elif outcome != 'rejected':
            fail(f'injection {label} was NOT rejected')


def cmd_dryrun():
    C2DIR.mkdir(parents=True, exist_ok=True)
    if DRY_LOG.exists():
        fail('dry-run chain already exists — remove it explicitly to rerun')
    n = build_normal_chain(DRY_LOG)
    sl = SealingLog(DRY_LOG, DRY_HEAD).load()
    got = sl.verify()
    print(f'normal chain: {n} events appended, replay-verified {got} '
          f'from genesis, exact-byte bound, head anchored')

    # --- semantic injections: cascade-rehashed so ONLY the target gate fires
    def dup_reveal(td, log, head):
        evs = read_events(log)
        dup = dict(evs[0])
        dup['ts'] = evs[-1]['ts'] + 1
        evs.append(dup)
        cascade_rehash(evs, 0)  # full legal rehash incl. the duplicate
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def skip_middle_seal(td, log, head):
        evs = read_events(log)
        del evs[-3]  # SEAL A2 -> REVEAL B2 follows an unsealed REVEAL
        cascade_rehash(evs, len(evs) - 3)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def dup_seal(td, log, head):
        evs = read_events(log)
        dup = dict(evs[-1])
        dup['ts'] = evs[-1]['ts'] + 1
        evs.append(dup)
        cascade_rehash(evs, len(evs) - 1)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def seal_no_reveal(td, log, head):
        # reference an EXISTING bytes archive so the exact-byte gate passes
        # and only the target 'SEAL without prior REVEAL' gate can fire
        evs = read_events(log)
        existing = evs[1]['payload']  # a real SEAL's payload
        fake = {'sequence_no': len(evs), 'prev_event_hash': '',
                'event_type': SEAL, 'ts': evs[-1]['ts'] + 1,
                'payload': {'opaque_case_id': synth_ocid('C2_SYNTH_B'),
                            'T': '2099-02-01',
                            'receipt_sha256': existing['receipt_sha256'],
                            'bytes_ref': existing['bytes_ref']}}
        evs.append(fake)
        cascade_rehash(evs, len(evs) - 1)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def wrong_packet_id(td, log, head):
        evs = read_events(log)
        evs[0]['payload']['packet_id'] = 'f' * 64
        cascade_rehash(evs, 0)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def wrong_packet_hash(td, log, head):
        evs = read_events(log)
        evs[0]['payload']['packet_sha256'] = sha(b'not-the-packet')
        cascade_rehash(evs, 0)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def wrong_receipt_hash(td, log, head):
        # FIX1-3: cascade-recomputed chain still fails on receipt binding
        evs = read_events(log)
        evs[1]['payload']['receipt_sha256'] = sha(b'not-the-receipt')
        cascade_rehash(evs, 0)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def receipt_bytes_swapped(td, log, head):
        # mutate the ARCHIVED bytes; chain untouched -> binding must fail
        evs = read_events(log)
        bp = td / evs[1]['payload']['bytes_ref']
        bp.write_bytes(b'tampered receipt bytes')
        return 'verify'

    def wrong_sequence(td, log, head):
        evs = read_events(log)
        evs[3]['sequence_no'] = 99   # structural gate target: no rehash
        write_events(log, evs)
        return 'verify'

    def wrong_prev(td, log, head):
        evs = read_events(log)
        evs[4]['prev_event_hash'] = 'e' * 64  # structural gate target
        write_events(log, evs)
        return 'verify'

    def tamper_history(td, log, head):
        evs = read_events(log)
        evs[2]['payload']['T'] = '2099-12-31'  # payload changed, hash not
        write_events(log, evs)
        return 'verify'

    def out_of_order(td, log, head):
        # Keep packet_id, packet bytes and packet hash mutually valid so only
        # the per-case T-order gate can reject this mutation.
        evs = read_events(log)
        evs[4]['payload']['T'] = '2099-01-01'  # earlier than A's sealed T
        evs[4]['payload']['packet_id'] = synth_packet_id(
            'C2_SYNTH_A', '2099-01-01')
        pkt = synth_packet_bytes('C2_SYNTH_A', '2099-01-01')
        evs[4]['payload']['packet_sha256'] = sha(pkt)
        (td / evs[4]['payload']['bytes_ref']).write_bytes(pkt)
        cascade_rehash(evs, 4)
        write_events(log, evs)
        sync_head(head, evs)
        return 'verify'

    def append_must_fail(td, log, head, etype, payload, content, label,
                         truncate=False):
        """F2 negative: failed append must have zero persistent side effects."""
        log_before = log.read_bytes()
        head_before = head.read_bytes()
        bytes_before = sorted((p.relative_to(td), p.read_bytes())
                              for p in (td / 'bytes').rglob('*') if p.is_file())
        if truncate:
            log.write_bytes(b'')  # old trusted head remains
        try:
            SealingLog(log, head).append(etype, payload, content)
        except SystemExit:
            pass
        else:
            fail(f'injection {label} was NOT rejected')
        if log.read_bytes() != (b'' if truncate else log_before):
            fail(f'injection {label} mutated log despite rejection')
        if head.read_bytes() != head_before:
            fail(f'injection {label} mutated head despite rejection')
        bytes_after = sorted((p.relative_to(td), p.read_bytes())
                             for p in (td / 'bytes').rglob('*') if p.is_file())
        if bytes_after != bytes_before:
            fail(f'injection {label} mutated bytes archive despite rejection')
        return 'rejected'

    def append_old_head_empty(td, log, head):
        return append_must_fail(
            td, log, head, REVEAL,
            {'opaque_case_id': synth_ocid('C2_SYNTH_A'), 'T': '2099-04-01',
             'packet_id': synth_packet_id('C2_SYNTH_A', '2099-04-01'),
             'packet_sha256': sha(b'valid')}, b'valid',
            'old head + empty log', truncate=True)

    def append_wrong_packet_bytes(td, log, head):
        return append_must_fail(
            td, log, head, REVEAL,
            {'opaque_case_id': synth_ocid('C2_SYNTH_A'), 'T': '2099-04-01',
             'packet_id': synth_packet_id('C2_SYNTH_A', '2099-04-01'),
             'packet_sha256': sha(b'declared-A')}, b'actual-B',
            'wrong packet content/hash')

    def append_wrong_receipt_bytes(td, log, head):
        # Open a valid next REVEAL first; then the SEAL reaches the pre-write
        # byte-binding check instead of failing at the structural gate.
        pkt = synth_packet_bytes('C2_SYNTH_A', '2099-04-01')
        SealingLog(log, head).append(
            REVEAL, {'opaque_case_id': synth_ocid('C2_SYNTH_A'),
                     'T': '2099-04-01',
                     'packet_id': synth_packet_id('C2_SYNTH_A', '2099-04-01'),
                     'packet_sha256': sha(pkt)}, pkt)
        return append_must_fail(
            td, log, head, SEAL,
            {'opaque_case_id': synth_ocid('C2_SYNTH_A'), 'T': '2099-04-01',
             'receipt_sha256': sha(b'declared-receipt')}, b'actual-receipt',
            'wrong receipt content/hash')

    def truncation(td, log, head):
        evs = read_events(log)
        write_events(log, evs[:4])  # head still claims 6+
        return 'verify'

    def missing_head(td, log, head):
        Path(head).unlink()
        return 'verify'

    def fork(td, log, head):
        # two children with DISTINCT legal sequence numbers, SAME parent
        evs = read_events(log)
        parent = evs[-1]['event_hash']
        children = []
        for tag in (b'f1', b'f2'):
            seq = len(evs) + len(children)
            payload = {'opaque_case_id': synth_ocid('C2_SYNTH_A'),
                       'T': '2099-03-01',
                       'packet_id': synth_packet_id('C2_SYNTH_A', '2099-03-01'),
                       'packet_sha256': sha(tag),
                       'bytes_ref': f'bytes/reveal_packet/{seq}.bin'}
            eh = event_hash(seq, parent, REVEAL, payload)
            children.append({'sequence_no': seq, 'prev_event_hash': parent,
                             'event_type': REVEAL, 'payload': payload,
                             'event_hash': eh, 'ts': evs[-1]['ts'] + 1})
            # archive real bytes so the exact-byte gate passes and only the
            # parent-continuity gate can reject the second child
            (td / payload['bytes_ref']).write_bytes(tag)
        write_events(log, evs + children)
        sync_head(head, evs + children)
        return 'verify'  # 2nd child breaks linear parent continuity

    def append_reveal_before_seal(td, log, head):
        sl = SealingLog(log, head)
        pkt = synth_packet_bytes('C2_SYNTH_A', '2099-01-08')
        sl.append(REVEAL, {'opaque_case_id': synth_ocid('C2_SYNTH_A'),
                           'T': '2099-01-08',
                           'packet_id': synth_packet_id('C2_SYNTH_A',
                                                        '2099-01-08'),
                           'packet_sha256': sha(pkt)}, pkt)
        try:
            sl.append(REVEAL, {'opaque_case_id': synth_ocid('C2_SYNTH_B'),
                               'T': '2099-01-09',
                               'packet_id': synth_packet_id('C2_SYNTH_B',
                                                            '2099-01-09'),
                               'packet_sha256': sha(b'x')}, b'x')
        except SystemExit:
            return 'rejected'
        return 'accepted'

    injections = [
        ('REVEAL before prior SEAL (append gate)', append_reveal_before_seal),
        ('duplicate REVEAL (semantic, cascade-rehashed)', dup_reveal),
        ('REVEAL-before-SEAL via middle-SEAL removal (semantic)',
         skip_middle_seal),
        ('duplicate SEAL (semantic, cascade-rehashed)', dup_seal),
        ('SEAL without REVEAL (semantic, cascade-rehashed)', seal_no_reveal),
        ('wrong packet_id (semantic, cascade-rehashed)', wrong_packet_id),
        ('wrong packet hash (semantic, cascade-rehashed)', wrong_packet_hash),
        ('wrong receipt hash (semantic, cascade-rehashed)', wrong_receipt_hash),
        ('receipt archived bytes swapped (exact-byte binding)',
         receipt_bytes_swapped),
        ('wrong sequence_no (structural)', wrong_sequence),
        ('wrong prev_event_hash (structural)', wrong_prev),
        ('tampered historical event (structural)', tamper_history),
        ('out-of-order T (semantic, cascade-rehashed)', out_of_order),
        ('chain truncation (head anchor)', truncation),
        ('head anchor missing (mandatory)', missing_head),
        ('fork: same parent, distinct seqs (parent continuity)', fork),
        ('append old head + empty log (genesis bypass)', append_old_head_empty),
        ('append wrong packet content/hash (pre-write gate)', append_wrong_packet_bytes),
        ('append wrong receipt content/hash (pre-write gate)', append_wrong_receipt_bytes),
    ]
    results = []
    for label, mut in injections:
        inject(label, mut)
        results.append(label)
        print(f'  injection rejected: {label}')
    SealingLog(DRY_LOG, DRY_HEAD).load().verify()
    report = {
        'normal_chain_events': n,
        'injections_rejected': results,
        'head_anchor_scope': 'proves no truncation RELATIVE TO a trusted, '
                             'not-simultaneously-rewritten anchor; not '
                             'self-certifying against joint log+head rewrite',
        'fork_semantics': 'linear append-only log: second child of the same '
                          'parent violates parent continuity',
        'note': 'synthetic fixture only; real dry-run chain verified '
                'untouched after all injections (copy-isolation)'}
    (C2DIR / 'c2_dryrun_report.json').write_text(canon(report))
    print(f'C2 DRY RUN PASS: {n}-event chain + '
          f'{len(results)} illegal paths all FAIL-CLOSED')


def cmd_verify(log_path, head_path=None):
    sl = SealingLog(log_path, head_path, check_head=True).load()
    n = sl.verify()
    print(f'chain verified: {n} events from genesis, exact-byte bound, '
          f'head anchored')


def main():
    if len(sys.argv) < 2:
        fail('usage: csr8_phase_c_seal.py dryrun | verify <log> [<head>]')
    cmd = sys.argv[1]
    if cmd == 'dryrun':
        cmd_dryrun()
    elif cmd == 'verify':
        if len(sys.argv) < 3:
            fail('verify needs <log> [<head>]')
        cmd_verify(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        fail(f'unknown command {cmd}')


if __name__ == '__main__':
    main()
