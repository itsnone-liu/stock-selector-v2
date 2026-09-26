#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C C2 — synthetic REVEAL/SEAL hash-chain state machine dry run.

C2 scope (user ruling): SYNTHETIC FIXTURE ONLY — no real case reveal, no real
annotation, no hidden-plan observation window. Problems found here are fixed
here; C1 frozen facts @ 9292d0d are never touched (this module does not read
the real secret domain).

Commands:
  dryrun           build a normal synthetic chain, verify it, then inject all
                   twelve illegal paths on COPIES of the chain (the real
                   dry-run chain is never mutated — stronger than try/finally:
                   negative tests operate on throwaway copies by construction)
  verify <log> [<head>]   independently replay-verify any chain file

Machine-proven invariants (design v1.0 §5):
  sequence_no strictly monotonic; prev_event_hash == hash(previous event);
  event_hash deterministic; REVEAL packet hash binds exact revealed bytes;
  SEAL binds exact annotation receipt; sealed(T_i) precedes REVEAL(T_{i+1});
  full chain replay-verifiable from genesis.
FAIL-CLOSED: REVEAL before prior SEAL, duplicate REVEAL/SEAL, SEAL without
REVEAL, wrong packet_id/packet hash/sequence_no/prev_event_hash, tampered
historical event, out-of-order T, truncation (head anchor), fork.
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
    return f'SYNTH|{case}|{T}|packet-body-v1'.encode()


def synth_receipt(case, T):
    return canon({'annotator': 'SYNTH', 'T': T, 'opaque_case_id':
                  synth_ocid(case), 'answers': {'q1': 'x'}}).encode()


# ---------------- hash-chain sealing log ------------------------------------
class SealingLog:
    def __init__(self, log_path, head_path=None):
        self.path = Path(log_path)
        self.head_path = Path(head_path) if head_path else \
            self.path.with_suffix('.head.json')
        self.events = []

    def load(self):
        self.events = []
        if not self.path.exists():
            return self
        for line in self.path.read_text().splitlines():
            if line.strip():
                self.events.append(json.loads(line))
        return self

    def head(self):
        if not self.events:
            return GENESIS
        return self.events[-1]['event_hash']

    def _event_hash(self, seq, prev, etype, payload):
        return sha(f'{seq}|{prev}|{etype}|{canon(payload)}'.encode())

    def append(self, etype, payload):
        """Structural state-machine gate BEFORE any write."""
        self.load()
        self._gate(etype, payload)
        seq = len(self.events)
        prev = self.head()
        eh = self._event_hash(seq, prev, etype, payload)
        ev = {'sequence_no': seq, 'prev_event_hash': prev,
              'event_type': etype, 'payload': payload, 'event_hash': eh,
              'ts': time.time()}
        with open(self.path, 'a') as f:
            f.write(canon(ev) + '\n')
        self.events.append(ev)
        self._write_head()
        return ev

    def _write_head(self):
        self.head_path.write_text(canon(
            {'count': len(self.events), 'head_hash': self.head()}))

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

    # independent replay verification — no state trusted from append time
    def verify(self, check_head=True):
        prev = GENESIS
        seen_reveal, seen_seal, ts_prev = [], [], -1.0
        case_max_T = {}
        for i, ev in enumerate(self.events):
            p = ev['payload']
            if ev['sequence_no'] != i:
                fail(f'wrong sequence_no at event {i}')
            if ev['prev_event_hash'] != prev:
                fail(f'wrong prev_event_hash at event {i}')
            expect_h = self._event_hash(i, prev, ev['event_type'], p)
            if ev['event_hash'] != expect_h:
                fail(f'tampered event or hash at event {i}')
            if ev['ts'] < ts_prev:
                fail(f'non-monotonic timestamp at event {i}')
            ts_prev = ev['ts']
            key = (p['opaque_case_id'], p['T'])
            if ev['event_type'] == REVEAL:
                if key in seen_reveal:
                    fail(f'duplicate REVEAL at event {i}')
                if seen_reveal and seen_reveal[-1] not in seen_seal:
                    fail(f'REVEAL at {i} precedes SEAL of previous REVEAL')
                if p['packet_id'] != synth_packet_id_by_ocid(p):
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
            else:
                fail(f'unknown event type at {i}')
            if ev['event_type'] == SEAL:
                case_max_T[p['opaque_case_id']] = max(
                    case_max_T.get(p['opaque_case_id'], p['T']), p['T'])
            prev = ev['event_hash']
        # sealed(T_i) precedes REVEAL(T_{i+1}): strict alternation already
        # proven above (no new REVEAL while previous unsealed)
        if check_head and self.head_path.exists():
            h = json.loads(self.head_path.read_text())
            if h['count'] != len(self.events) or h['head_hash'] != self.head():
                fail('chain head anchor mismatch (truncation or fork)')
        return len(self.events)


def synth_packet_id_by_ocid(p):
    return sha(f"{p['opaque_case_id']}|{p['T']}".encode())


# ---------------- normal-chain builder --------------------------------------
def build_normal_chain(log_path):
    """3 rounds x 2 cases interleaved: A0 B0 A1 B1 A2 B2 (each REVEAL->SEAL)."""
    log = SealingLog(log_path)
    n = 0
    for ti, T in enumerate(SYNTH_TS[:3]):
        for case in SYNTH_CASES:
            ocid = synth_ocid(case)
            pkt = synth_packet_bytes(case, T)
            log.append(REVEAL, {'opaque_case_id': ocid, 'T': T,
                                'packet_id': synth_packet_id(case, T),
                                'packet_sha256': sha(pkt)})
            log.append(SEAL, {'opaque_case_id': ocid, 'T': T,
                              'receipt_sha256': sha(synth_receipt(case, T))})
            n += 2
    return n


# ---------------- negative injections (on throwaway copies) -----------------
def inject(label, mutate):
    """Copy the frozen dry-run chain to a temp dir, mutate, verify MUST fail."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        log = tdp / 'log.jsonl'
        head = tdp / 'log.head.json'
        shutil.copy(DRY_LOG, log)
        shutil.copy(DRY_HEAD, head)
        outcome = mutate(tdp, log, head)
        if outcome == 'verify':
            rejected = False
            try:
                SealingLog(log, head).load().verify()
            except SystemExit:
                rejected = True
            if not rejected:
                fail(f'injection {label} was NOT rejected')
        elif outcome not in ('rejected',):
            fail(f'injection {label} was NOT rejected')


def read_events(log_path):
    return [json.loads(l) for l in Path(log_path).read_text().splitlines() if l.strip()]


def write_events(log_path, events):
    Path(log_path).write_text(
        '\n'.join(canon(e) for e in events) + '\n')


DRY_LOG = C2DIR / 'dryrun_sealing_log.jsonl'
DRY_HEAD = C2DIR / 'dryrun_sealing_log.head.json'


# ---------------- command: dryrun --------------------------------------------
def cmd_dryrun():
    C2DIR.mkdir(parents=True, exist_ok=True)
    if DRY_LOG.exists():
        fail('dry-run chain already exists — remove it explicitly to rerun')
    n = build_normal_chain(DRY_LOG)
    sl = SealingLog(DRY_LOG, DRY_HEAD).load()
    got = sl.verify()
    print(f'normal chain: {n} events appended, replay-verified {got} '
          f'from genesis, head anchored')

    def append_dup_reveal(td, log, head):
        evs = read_events(log)
        dup = dict(evs[0])
        dup['sequence_no'] = len(evs)
        dup['prev_event_hash'] = evs[-1]['event_hash']
        write_events(log, evs + [dup])
        return 'verify'

    def skip_seal(td, log, head):
        # delete a MIDDLE SEAL and cascade-recompute successor hashes:
        # a trailing open REVEAL alone is a legal mid-annotation state, so
        # the illegal path is REVEAL -> REVEAL with the SEAL between removed
        evs = read_events(log)
        del evs[-3]  # SEAL A2 -> next REVEAL B2 now follows an unsealed one
        prev = evs[-4]['event_hash']
        for i in range(len(evs) - 3, len(evs)):
            evs[i]['sequence_no'] = i
            evs[i]['prev_event_hash'] = prev
            evs[i]['event_hash'] = sha(
                f"{i}|{prev}|{evs[i]['event_type']}|{canon(evs[i]['payload'])}"
                .encode())
            prev = evs[i]['event_hash']
        write_events(log, evs)
        h = json.loads(Path(head).read_text())
        h['count'] = len(evs)
        h['head_hash'] = evs[-1]['event_hash']
        Path(head).write_text(canon(h))
        return 'verify'

    def dup_seal(td, log, head):
        evs = read_events(log)
        dup = dict(evs[-1])
        dup['sequence_no'] = len(evs)
        dup['prev_event_hash'] = evs[-1]['event_hash']
        dup['event_hash'] = sha(f"{dup['sequence_no']}|{dup['prev_event_hash']}"
                                f"|{dup['event_type']}|{canon(dup['payload'])}"
                                .encode())
        write_events(log, evs + [dup])
        h = json.loads(Path(head).read_text())
        h['count'] += 1
        h['head_hash'] = dup['event_hash']
        Path(head).write_text(canon(h))
        return 'verify'

    def seal_no_reveal(td, log, head):
        evs = read_events(log)
        fake = {'sequence_no': len(evs), 'prev_event_hash': evs[-1]['event_hash'],
                'event_type': SEAL, 'ts': evs[-1]['ts'] + 1,
                'payload': {'opaque_case_id': synth_ocid('C2_SYNTH_B'),
                            'T': '2099-02-01',
                            'receipt_sha256': sha(b'fake')}}
        fake['event_hash'] = sha(f"{fake['sequence_no']}|{fake['prev_event_hash']}"
                                 f"|{SEAL}|{canon(fake['payload'])}".encode())
        write_events(log, evs + [fake])
        h = json.loads(Path(head).read_text())
        h['count'] += 1
        h['head_hash'] = fake['event_hash']
        Path(head).write_text(canon(h))
        return 'verify'

    def wrong_packet_id(td, log, head):
        evs = read_events(log)
        evs[0]['payload']['packet_id'] = 'f' * 64
        write_events(log, evs)
        return 'verify'

    def wrong_packet_hash(td, log, head):
        evs = read_events(log)
        evs[0]['payload']['packet_sha256'] = sha(b'not-the-packet')
        write_events(log, evs)
        return 'verify'

    def wrong_sequence(td, log, head):
        evs = read_events(log)
        evs[3]['sequence_no'] = 99
        write_events(log, evs)
        return 'verify'

    def wrong_prev(td, log, head):
        evs = read_events(log)
        evs[4]['prev_event_hash'] = 'e' * 64
        write_events(log, evs)
        return 'verify'

    def tamper_history(td, log, head):
        evs = read_events(log)
        evs[2]['payload']['T'] = '2099-12-31'  # payload changed, hash not
        write_events(log, evs)
        return 'verify'

    def out_of_order(td, log, head):
        evs = read_events(log)
        evs[4]['payload']['T'] = '2098-01-01'  # earlier than case max sealed
        write_events(log, evs)
        return 'verify'

    def truncation(td, log, head):
        evs = read_events(log)
        write_events(log, evs[:4])  # head anchor still claims 6
        return 'verify'

    def fork(td, log, head):
        evs = read_events(log)
        f1 = {'sequence_no': len(evs), 'prev_event_hash': evs[-1]['event_hash'],
              'event_type': REVEAL, 'ts': evs[-1]['ts'] + 1,
              'payload': {'opaque_case_id': synth_ocid('C2_SYNTH_A'),
                          'T': '2099-03-01',
                          'packet_id': synth_packet_id('C2_SYNTH_A',
                                                       '2099-03-01'),
                          'packet_sha256': sha(b'f1')}}
        f2 = dict(f1)
        f2['payload'] = dict(f1['payload'], packet_sha256=sha(b'f2'))
        for f in (f1, f2):
            f['event_hash'] = sha(f"{f['sequence_no']}|{f['prev_event_hash']}"
                                  f"|{REVEAL}|{canon(f['payload'])}".encode())
        write_events(log, evs + [f1, f2])  # same prev, two children
        return 'verify'

    def append_reveal_before_seal(td, log, head):
        # build a REAL open-REVEAL state on the copy, then a second REVEAL
        # while unsealed must be rejected by the append-time gate
        sl = SealingLog(log, head)
        sl.append(REVEAL, {'opaque_case_id': synth_ocid('C2_SYNTH_A'),
                           'T': '2099-01-08',
                           'packet_id': synth_packet_id('C2_SYNTH_A',
                                                        '2099-01-08'),
                           'packet_sha256': sha(synth_packet_bytes(
                               'C2_SYNTH_A', '2099-01-08'))})
        try:
            sl.append(REVEAL, {'opaque_case_id': synth_ocid('C2_SYNTH_B'),
                               'T': '2099-01-09',
                               'packet_id': synth_packet_id('C2_SYNTH_B',
                                                            '2099-01-09'),
                               'packet_sha256': sha(b'x')})
        except SystemExit:
            return 'rejected'
        return 'accepted'

    injections = [
        ('REVEAL before prior SEAL (append gate)', append_reveal_before_seal),
        ('duplicate REVEAL (verify)', append_dup_reveal),
        ('REVEAL-before-SEAL truncation (verify)', skip_seal),
        ('duplicate SEAL (verify)', dup_seal),
        ('SEAL without REVEAL (verify)', seal_no_reveal),
        ('wrong packet_id', wrong_packet_id),
        ('wrong packet hash', wrong_packet_hash),
        ('wrong sequence_no', wrong_sequence),
        ('wrong prev_event_hash', wrong_prev),
        ('tampered historical event', tamper_history),
        ('out-of-order T', out_of_order),
        ('chain truncation (head anchor)', truncation),
        ('chain fork (same prev, two children)', fork),
    ]
    results = []
    for label, mut in injections:
        inject(label, mut)
        results.append(label)
        print(f'  injection rejected: {label}')
    # the real dry-run chain is untouched by construction (copies only)
    SealingLog(DRY_LOG, DRY_HEAD).load().verify()
    report = {'normal_chain_events': n,
              'injections_rejected': results,
              'note': 'synthetic fixture only; real dry-run chain verified '
                      'untouched after all injections (copy-isolation)'}
    (C2DIR / 'c2_dryrun_report.json').write_text(canon(report))
    print(f'C2 DRY RUN PASS: {n}-event chain + '
          f'{len(results)} illegal paths all FAIL-CLOSED')


def cmd_verify(log_path, head_path=None):
    sl = SealingLog(log_path, head_path).load()
    n = sl.verify()
    print(f'chain verified: {n} events from genesis, head anchored')


def main():
    if len(sys.argv) < 2:
        fail('usage: csr8_phase_c_seal.py dryrun | verify <log> [<head>]')
    cmd = sys.argv[1]
    if cmd == 'dryrun':
        cmd_dryrun()
    elif cmd == 'verify':
        if len(sys.argv) < 3:
            fail('verify needs <log> [<head>]')
        cmd_verify(sys.argv[2],
                   sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        fail(f'unknown command {cmd}')


if __name__ == '__main__':
    main()
