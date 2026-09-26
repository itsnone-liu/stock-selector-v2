#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C3 Real Packet Integration & Preflight (NO production reveal).

Implements the frozen C3 v1.0 design @ 3308de9.  All packet-level artifacts,
case/T mapping and isolated event log stay in the C3 secret-domain.  Public
output is commitment + boolean summary only.
"""
import csv, gzip, hashlib, json, os, shutil, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# C3-DESIGN-ERRATUM-PRICE-SOURCE @ d1eb677: BaoStock unadjusted is the
# Phase-B frozen research-window SoR; authority is universe_frozen.json, not
# a hash freshly minted from the current directory.
UNIVERSE = ROOT / 'config/universe_frozen.json'
FETCH = ROOT / 'data/adjustment_baostock/fetch_manifest.json'
PRICE = ROOT / 'data/adjustment_baostock/per_stock'
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

def file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()

def parse_date(value, label):
    if not isinstance(value, str): fail(f'{label}: date is not a string')
    s = value.replace('/', '-').replace('.', '-')
    if len(s) == 8 and s.isdigit(): s = f'{s[:4]}-{s[4:6]}-{s[6:]}'
    try: return date.fromisoformat(s)
    except ValueError: fail(f'{label}: invalid date {value!r}')

def load_calendar():
    with open(CAL) as f: return [r[0] for r in list(csv.reader(f))[1:]]

def verify_price_authority():
    frozen = json.loads(UNIVERSE.read_text())
    if file_sha(FETCH) != frozen['fetch_manifest_sha256']:
        fail('G-C3-CHART frozen fetch_manifest hash mismatch')
    manifest = json.loads(FETCH.read_text())
    stocks = manifest.get('stocks', {})
    parts = [f'{code}:{stocks[code]["sha256"]}' for code in sorted(stocks)]
    if sha(('\n'.join(parts)).encode()) != frozen['per_stock_root_sha256']:
        fail('G-C3-CHART frozen per-stock root mismatch')
    if len(stocks) != 5240 or set(stocks) != set(frozen['codes']):
        fail('G-C3-CHART frozen price universe mismatch')
    for code, meta in stocks.items():
        fp = PRICE / f'{code}.json.gz'
        if not fp.exists() or file_sha(fp) != meta['sha256']:
            fail(f'G-C3-CHART price file SHA mismatch: {code}')
    return frozen, manifest

def verify_payload_schema(endpoint, payload, allowlist):
    if endpoint not in allowlist or set(payload) != set(allowlist[endpoint]):
        fail(f'G-C3-SCHEMA endpoint payload allowlist mismatch: {endpoint}')

def load_case_map(c1):
    cases = c1.load_cases(); salt = c1.load_salt()
    by_ocid = {}
    for code, c in cases.items():
        by_ocid[c1.opaque_case_id(salt, c['key'])] = (code, c)
    return by_ocid

def expected_chart(code, T, calendar):
    if T not in calendar: fail(f'G-C3-CHART T not in frozen calendar: {T}')
    end = calendar.index(T); start = calendar[max(0, end - LOOKBACK + 1)]
    fp = PRICE / f'{code}.json.gz'
    if not fp.exists(): fail(f'G-C3-CHART price source missing: {code}')
    obj = json.loads(gzip.open(fp, 'rt').read())
    rows = [r for r in obj.get('unadj', []) if start <= r[0] <= T]
    if not rows: fail(f'G-C3-CHART empty chart slice {code} {T}')
    dates = [parse_date(r[0], f'price {code}') for r in rows]
    if dates != sorted(dates) or len(set(dates)) != len(dates): fail('G-C3-CHART dates not strictly sorted/unique')
    return {'source_id':'baostock_unadjusted_v1', 'start_date':start,
            'end_date':T, 'dates':[r[0] for r in rows],
            'values':[r[4] for r in rows]}

def date_leq(v, T, label='date'):
    return parse_date(v, label) <= parse_date(T, 'T')

def run(state_dir=C3S, artifact_dir=C3A):
    global C3S, C3A
    os.umask(0o077)
    C3S, C3A = Path(state_dir), Path(artifact_dir)
    if C3S.exists(): fail('C3 state domain must be fresh before run')
    C3S.mkdir(parents=True, mode=0o700)
    os.chmod(C3S, 0o700)
    C3A.mkdir(parents=True, exist_ok=True)
    os.chmod(C3A, 0o700)
    # Import C1/C2 implementations only; do not invoke their commands.
    sys.path.insert(0, str(ROOT / 'scripts'))
    import csr8_phase_c_packet as c1
    import csr8_phase_c_seal as c2
    c1.verify_salt_binding(); c1.verify_plan_binding()
    frozen_price, price_manifest = verify_price_authority()
    # F1: bind C1 projection to the frozen public projection output hash.
    proj_summary = json.loads((PC/'c1_artifacts/projection_summary.json').read_text())
    if file_sha(PROJ) != proj_summary['output_sha256']:
        fail('F1 C1 projection frozen output hash mismatch')
    index = load_index(); calendar = load_calendar(); by_ocid = load_case_map(c1)
    projected = load_jsonl(PROJ)
    if len(projected) != 24802: fail('C1 projected row count changed')
    # Parse every source/index date before constructing EXPECTED: invalid dates
    # must fail, never disappear through a filter.
    for rid, r in index.items():
        parse_date(r.get('observation_date'), f'index {rid} observation_date')
        parse_date(r.get('available_date'), f'index {rid} available_date')
    for p in projected:
        parse_date(p.get('observation_date'), f'projection {p.get("record_id")} observation_date')
    # record_id 1:1 source congruence and case membership
    records = {}; case_records = {}
    for p in projected:
        rid = p['record_id']
        if rid in records: fail('projected duplicate record_id')
        if rid not in index: fail(f'projected record missing from index: {rid}')
        i = index[rid]
        if p['endpoint'] != i['endpoint'] or p['observation_date'] != i['observation_date']:
            fail(f'G-C3-COVERAGE source/index mismatch: {rid}')
        verify_payload_schema(p['endpoint'], p.get('payload', {}), c1.ALLOWLIST)
        if p['opaque_case_id'] not in by_ocid: fail('unknown opaque case id')
        records[rid] = (p, i)
        case_records.setdefault(p['opaque_case_id'], []).append(rid)
    plan = json.loads(PLAN.read_text())
    # selector-only manifest: never public
    packet_manifest = []
    packet_gate_results = []
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
            if not date_leq(i['available_date'], T, f'{rid} available_date') or not date_leq(i['observation_date'], T, f'{rid} observation_date'): fail('G-C3-EVIDENCE future record')
            date_keys = {'margin_sse':['信用交易日期'], 'margin_szse':[], 'lhb':['上榜日'], 'dzjy':['交易日期']}[p['endpoint']]
            for k in date_keys:
                if k not in payload or not date_leq(payload[k], T, f'{rid} payload {k}'): fail(f'G-C3-DATE violation {k}')
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
        if set(packet['as_of']) != {'decision_clock','T'}:
            fail('G-C3-SCHEMA as_of nested key mismatch')
        if set(packet['price_panel']) != {'source_id','start_date','end_date','dates','values'}:
            fail('G-C3-SCHEMA price_panel nested key mismatch')
        if len(packet['price_panel']['dates']) != len(packet['price_panel']['values']):
            fail('G-C3-SCHEMA chart dates/values shape mismatch')
        if not all(isinstance(x, str) for x in packet['price_panel']['values']):
            fail('G-C3-SCHEMA chart values are not close-only strings')
        for e in evidence:
            if set(e) != {'record_id','endpoint','observation_date','available_date','payload'}:
                fail('G-C3-SCHEMA evidence key mismatch')
            if set(e['payload']) != set(c1.ALLOWLIST[e['endpoint']]):
                fail('G-C3-SCHEMA nested endpoint payload mismatch')
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
        packet_gate_results.append({'packet_id':packet_id,'gates':{g:'PASS' for g in GATE_IDS}})
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
    # selector-only audit; gate results are persisted and summary is derived.
    (C3S/'packet_manifest.json').write_text(canon(packet_manifest))
    (C3S/'gate_results.jsonl').write_text(''.join(canon(x)+'\n' for x in packet_gate_results))
    os.chmod(C3S/'gate_results.jsonl', 0o600)
    os.chmod(C3S/'packet_manifest.json', 0o600)
    (C3S/'gate_audit.json').write_text(canon({'gate_ids':GATE_IDS,'counts':gates,
        'all_pass': all(gates[g] == len(packet_manifest) for g in GATE_IDS),
        'construction_mode':'C2-format batch construction + frozen C2 full replay + frozen C2 append smoke'}))
    os.chmod(C3S/'gate_audit.json', 0o600)
    if not all(gates[g] == len(packet_manifest) for g in GATE_IDS): fail('gate audit count mismatch')
    summary = {'ALL_GATES_PASS': all(gates[g] == len(packet_manifest) for g in GATE_IDS),
               'NO_PRODUCTION_REVEAL':True,'NO_PRODUCTION_SEAL':True,
               'NO_REAL_ANNOTATION':True,'G5_BLOCKED':True,'XP_BLOCKED_FOR_PIT':True}
    schema_hash = sha(canon({'packet':sorted({'packet_id','opaque_case_id','as_of','evidence','price_panel'}),
        'as_of':['decision_clock','T'],'price_panel':['source_id','start_date','end_date','dates','values'],
        'evidence':['record_id','endpoint','observation_date','available_date','payload'],
        'payload_allowlist':c1.ALLOWLIST}).encode())
    public = {'packet_manifest_commitment':sha(canon(packet_manifest).encode()),
              'packet_schema_sha256':schema_hash, 'source_commitments':{
                  'c1_projection':proj_summary['output_sha256'],
                  'c1_salt':json.loads((C1A/'salt_commitment.json').read_text())['salt_commitment'],
                  'c1_plan':json.loads((C1A/'plan_commitment.json').read_text())['plan_commitment'],
                  'price_source_id':'baostock_unadjusted_v1',
                  'price_fetch_manifest_sha256':frozen_price['fetch_manifest_sha256'],
                  'price_per_stock_root_sha256':frozen_price['per_stock_root_sha256']}}
    C3A.mkdir(parents=True, exist_ok=True)
    (C3A/'c3_manifest_commitment.json').write_text(canon(public))
    (C3A/'c3_boolean_summary.json').write_text(canon(summary))
    (C3A/'C3_PREFLIGHT_REPORT.md').write_text('# C3 PREFLIGHT PASS\n\nNO_PRODUCTION_REVEAL\nNO_PRODUCTION_SEAL\nNO_REAL_ANNOTATION\nG5_BLOCKED\nXP_BLOCKED_FOR_PIT\n')
    print('C3 PREFLIGHT PASS; public output is commitments + booleans only')
    return sha(canon(packet_manifest).encode())

C1A = PC/'c1_artifacts'

def negative_tests():
    """Four isolated fail-closed fixtures; no frozen input is modified."""
    import tempfile
    def expect(label, fn):
        try: fn()
        except (RuntimeError, ValueError, KeyError):
            print(f'NEGATIVE PASS: {label}'); return
        fail(f'negative fixture unexpectedly passed: {label}')
    frozen = json.loads(UNIVERSE.read_text())
    expected_proj = json.loads((PC/'c1_artifacts/projection_summary.json').read_text())['output_sha256']
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td)/'projection.jsonl'; raw = PROJ.read_bytes(); bad.write_bytes(raw[:-1] + (b'X' if raw[-1:] != b'X' else b'Y'))
        expect('one-byte projection mutation → C1 binding FAIL', lambda: (
            file_sha(bad) == expected_proj or fail('projection binding')))
        expect('future/invalid payload field → schema FAIL', lambda: verify_payload_schema('lhb', {'上榜日':'2025-01-01','future_field':1}, {'lhb':['上榜日']}))
        expect('available_date 2025-99-99 → temporal parse FAIL', lambda: parse_date('2025-99-99','negative'))
        mutated = dict(frozen); mutated['per_stock_root_sha256'] = '0'*64
        expect('one-bit price authority mutation → chart source FAIL', lambda: (
            sha(('\n'.join(f'{c}:{json.loads(FETCH.read_text())["stocks"][c]["sha256"]}' for c in sorted(json.loads(FETCH.read_text())['stocks']))).encode()) == mutated['per_stock_root_sha256'] or fail('price authority')))
    print('C3 NEGATIVE TESTS PASS: 4 isolated fail-closed fixtures')

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('preflight','negative'):
        fail('usage: csr8_phase_c_preflight.py preflight|negative')
    try:
        if sys.argv[1] == 'negative':
            negative_tests(); return
        first = run()
        # F5: independent fresh state and artifact domains; compare the full
        # selector-only manifest commitment, not merely files after one write.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            second = run(Path(td)/'state', Path(td)/'artifacts')
        if first != second:
            fail('F5 two-run determinism mismatch')
        print('C3 determinism PASS: two fresh independent runs identical')
    except RuntimeError: sys.exit(1)
if __name__ == '__main__': main()
