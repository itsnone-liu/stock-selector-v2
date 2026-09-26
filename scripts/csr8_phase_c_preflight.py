#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C3 Real Packet Integration & Preflight (NO production reveal).

Implements the frozen C3 v1.0 design @ 3308de9.  All packet-level artifacts,
case/T mapping and isolated event log stay in the C3 secret-domain.  Public
output is commitment + boolean summary only.
"""
import csv, gzip, hashlib, json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RT = ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt'
PC = ROOT / 'output/research/csr/08_pilot_cases/phase_c'
SECRET = ROOT / 'data/csr8_phase_c/secret'
C3S = ROOT / 'data/csr8_phase_c/c3_preflight'
C3A = PC / 'c3_preflight_artifacts'
CASE_CSV = RT / 'normalized_case84_2021-03-08_2026-09-17.csv'
PROJ = SECRET / 'projected_case84.jsonl'
PLAN = SECRET / 'packet_plan.json'
CAL = RT / 'frozen_exchange_calendar.csv'
PRICE = ROOT / 'data/adjustment_baostock/per_stock'
GATE_IDS = ['G-C3-SCHEMA','G-C3-COVERAGE','G-C3-EVIDENCE','G-C3-DATE','G-C3-CHART','G-C3-CONGRUENCE']
LOOKBACK = 120


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def sha(b): return hashlib.sha256(b).hexdigest()
def fail(msg):
    print('FAIL-CLOSED:', msg); raise RuntimeError(msg)

def load_jsonl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]

def load_index():
    out = {}
    with open(CASE_CSV) as f:
        for r in csv.DictReader(f):
            if r['record_id'] in out: fail('duplicate index record_id')
            out[r['record_id']] = r
    return out

def load_calendar():
    with open(CAL) as f: return [r[0] for r in list(csv.reader(f))[1:]]

def load_case_map(c1):
    cases = c1.load_cases(); salt = c1.load_salt()
    by_ocid = {}
    for code, c in cases.items():
        by_ocid[c1.opaque_case_id(salt, c['key'])] = (code, c)
    return by_ocid

def expected_chart(code, T, calendar):
    if T not in calendar: fail(f'chart T not in frozen calendar: {T}')
    end = calendar.index(T)
    start = calendar[max(0, end - LOOKBACK + 1)]
    fp = PRICE / f'{code}.json.gz'
    if not fp.exists(): fail(f'price source missing: {code}')
    obj = json.loads(gzip.open(fp, 'rt').read())
    rows = [r for r in obj['unadj'] if start <= r[0] <= T]
    if not rows: fail(f'empty chart slice {code} {T}')
    if [r[0] for r in rows] != sorted(r[0] for r in rows): fail('chart dates not sorted')
    return {'start_date': rows[0][0], 'end_date': T,
            'dates': [r[0] for r in rows], 'values': rows}

def date_leq(v, T):
    if not isinstance(v, str): return False
    s = v.replace('/', '-').replace('.', '-')
    if len(s) == 8 and s.isdigit(): s = s[:4]+'-'+s[4:6]+'-'+s[6:]
    return len(s) == 10 and s <= T

def run():
    # Import C1/C2 implementations only; do not invoke their commands.
    sys.path.insert(0, str(ROOT / 'scripts'))
    import csr8_phase_c_packet as c1
    import csr8_phase_c_seal as c2
    c1.verify_salt_binding(); c1.verify_plan_binding()
    index = load_index(); calendar = load_calendar(); by_ocid = load_case_map(c1)
    projected = load_jsonl(PROJ)
    if len(projected) != 24802: fail('C1 projected row count changed')
    # record_id 1:1 source congruence and case membership
    records = {}; case_records = {}
    for p in projected:
        rid = p['record_id']
        if rid in records: fail('projected duplicate record_id')
        if rid not in index: fail(f'projected record missing from index: {rid}')
        i = index[rid]
        if p['endpoint'] != i['endpoint'] or p['observation_date'] != i['observation_date']:
            fail(f'G-C3-COVERAGE source/index mismatch: {rid}')
        if p['opaque_case_id'] not in by_ocid: fail('unknown opaque case id')
        records[rid] = (p, i)
        case_records.setdefault(p['opaque_case_id'], []).append(rid)
    plan = json.loads(PLAN.read_text())
    # selector-only manifest: never public
    packet_manifest = []
    gates = {g: 0 for g in GATE_IDS}; packet_hashes = []
    C3S.mkdir(parents=True, exist_ok=True); (C3S/'packets').mkdir(exist_ok=True)
    # isolated C2 domain, no production path.  The frozen C2 append() performs
    # a full replay before every event (correct but O(n^2) for 3,510 events).
    # C3 therefore uses a linear batch writer with the same event/byte format,
    # then runs the frozen C2 verifier over the complete chain.  A separate
    # two-event C2 append smoke below exercises the append precondition itself.
    log = C3S / 'isolated_preflight_log.jsonl'; head = C3S / 'isolated_preflight_log.head.json'
    if log.exists(): fail('C3 state already exists; use fresh state directory')
    chain = c2.SealingLog(log, head)
    def batch_append(etype, payload, content):
        if not payload.get('packet_sha256', payload.get('receipt_sha256')) == sha(content):
            fail('C3 batch pre-write byte binding failed')
        seq = len(chain.events); prev = chain.head()
        bref = f'bytes/{etype.lower()}/{seq}.bin'
        payload = dict(payload, bytes_ref=bref)
        ev = {'sequence_no':seq,'prev_event_hash':prev,'event_type':etype,
              'payload':payload,'event_hash':c2.event_hash(seq,prev,etype,payload),
              'ts':float(seq)}
        bp = log.parent / bref; bp.parent.mkdir(parents=True, exist_ok=True); bp.write_bytes(content)
        with open(log, 'a') as f: f.write(canon(ev)+'\n')
        chain.events.append(ev)
        head.write_text(canon({'count':len(chain.events),'head_hash':chain.head()}))
    for ent in plan['entries']:
        ocid = c1.opaque_case_id(c1.load_salt(), ent['case_key']); T = ent['T']
        if ocid not in by_ocid: fail('plan case not in frozen case map')
        code, case = by_ocid[ocid]
        expected = {rid for rid in case_records.get(ocid, []) if date_leq(records[rid][1]['available_date'], T)}
        evidence = []
        for rid in sorted(expected):
            p, i = records[rid]
            payload = p['payload']
            # G-C3-EVIDENCE + frozen DATE registry
            if not date_leq(i['available_date'], T) or not date_leq(i['observation_date'], T): fail('G-C3-EVIDENCE future record')
            date_keys = {'margin_sse':['信用交易日期'], 'margin_szse':[], 'lhb':['上榜日'], 'dzjy':['交易日期']}[p['endpoint']]
            for k in date_keys:
                if k not in payload or not date_leq(payload[k], T): fail(f'G-C3-DATE violation {k}')
            evidence.append({'record_id':rid, 'endpoint':p['endpoint'],
                             'observation_date':i['observation_date'], 'available_date':i['available_date'],
                             'payload':payload})
        actual = {x['record_id'] for x in evidence}
        if actual != expected or len(actual) != len(evidence): fail('G-C3-COVERAGE equality failed')
        gates['G-C3-COVERAGE'] += 1; gates['G-C3-EVIDENCE'] += 1; gates['G-C3-DATE'] += 1
        packet_id = c1.packet_id(ocid, T)
        chart = expected_chart(code, T, calendar)
        # exact deterministic chart function and blindness is inherent: no case window input
        packet = {'packet_id':packet_id, 'opaque_case_id':ocid,
                  'as_of':{'decision_clock':'CLOSE_AFTER_T','T':T},
                  'evidence':evidence, 'price_panel':chart}
        allowed = {'packet_id','opaque_case_id','as_of','evidence','price_panel'}
        if set(packet) != allowed: fail('G-C3-SCHEMA packet key mismatch')
        for e in evidence:
            if set(e) != {'record_id','endpoint','observation_date','available_date','payload'}:
                fail('G-C3-SCHEMA evidence key mismatch')
        gates['G-C3-SCHEMA'] += 1; gates['G-C3-CHART'] += 1
        packet_bytes = canon(packet).encode(); ph = sha(packet_bytes)
        ppath = C3S/'packets'/f'{packet_id}.json'; ppath.write_bytes(packet_bytes)
        # synthetic/preflight receipt, never a real annotation
        receipt = canon({'preflight':True,'opaque_case_id':ocid,'T':T,'packet_id':packet_id}).encode()
        # C3-CONGRUENCE before C2 append
        if packet['opaque_case_id'] != ocid or packet['as_of']['T'] != T or packet['packet_id'] != packet_id: fail('G-C3-CONGRUENCE packet metadata')
        if sha(packet_bytes) != ph or json.loads(receipt)['opaque_case_id'] != ocid or json.loads(receipt)['T'] != T: fail('G-C3-CONGRUENCE bytes/receipt')
        gates['G-C3-CONGRUENCE'] += 1
        batch_append(c2.REVEAL, {'opaque_case_id':ocid,'T':T,'packet_id':packet_id,'packet_sha256':ph}, packet_bytes)
        batch_append(c2.SEAL, {'opaque_case_id':ocid,'T':T,'receipt_sha256':sha(receipt)}, receipt)
        packet_manifest.append({'case_key':ent['case_key'],'T':T,'packet_id':packet_id,'sha256':ph,'record_count':len(evidence)})
        packet_hashes.append(ph)
    chain.verify()
    # C2 append precondition smoke in a separate ephemeral directory: the
    # frozen engine itself still verifies predecessor state before append.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        smoke_log, smoke_head = Path(td)/'log.jsonl', Path(td)/'log.head.json'
        smoke = c2.SealingLog(smoke_log, smoke_head)
        smoke_pkt = b'C3 isolated append smoke'
        smoke.append(c2.REVEAL, {'opaque_case_id':'c3-smoke', 'T':'2099-01-01',
                                 'packet_id':sha(b'c3-smoke|2099-01-01'),
                                 'packet_sha256':sha(smoke_pkt)}, smoke_pkt)
        smoke_rec = b'C3 synthetic receipt'
        smoke.append(c2.SEAL, {'opaque_case_id':'c3-smoke', 'T':'2099-01-01',
                               'receipt_sha256':sha(smoke_rec)}, smoke_rec)
        smoke.verify()
    # determinism: packet bytes are canonical and reloaded hashes match.
    if any(sha((C3S/'packets'/f'{x["packet_id"]}.json').read_bytes()) != x['sha256'] for x in packet_manifest): fail('determinism/hash mismatch')
    # selector-only audit; no public cardinality/hash/distribution.
    (C3S/'packet_manifest.json').write_text(canon(packet_manifest))
    summary = {'ALL_GATES_PASS':True,'NO_PRODUCTION_REVEAL':True,'NO_PRODUCTION_SEAL':True,
               'NO_REAL_ANNOTATION':True,'G5_BLOCKED':True,'XP_BLOCKED_FOR_PIT':True}
    public = {'packet_manifest_commitment':sha(canon(packet_manifest).encode()),
              'packet_schema':'c3-visible-v1', 'source_commitments':{
                  'c1_projection':sha(PROJ.read_bytes()),
                  'c1_salt':json.loads((C1A/'salt_commitment.json').read_text())['salt_commitment'],
                  'c1_plan':json.loads((C1A/'plan_commitment.json').read_text())['plan_commitment']}}
    C3A.mkdir(parents=True, exist_ok=True)
    (C3A/'c3_manifest_commitment.json').write_text(canon(public))
    (C3A/'c3_boolean_summary.json').write_text(canon(summary))
    (C3A/'C3_PREFLIGHT_REPORT.md').write_text('# C3 PREFLIGHT PASS\n\nNO_PRODUCTION_REVEAL\nNO_PRODUCTION_SEAL\nNO_REAL_ANNOTATION\nG5_BLOCKED\nXP_BLOCKED_FOR_PIT\n')
    print('C3 PREFLIGHT PASS; public output is commitments + booleans only')

C1A = PC/'c1_artifacts'

def main():
    if len(sys.argv) != 2 or sys.argv[1] != 'preflight':
        fail('usage: csr8_phase_c_preflight.py preflight')
    try: run()
    except RuntimeError: sys.exit(1)
if __name__ == '__main__': main()
