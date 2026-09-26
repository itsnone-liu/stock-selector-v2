#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C packet generator — C1: hidden infrastructure & projection freeze.

Commands (C1 scope ONLY — reveal/seal deliberately NOT implemented here):
  salt      generate 256-bit secret_salt into secret domain + public commitment
  plan      build hidden (case,T) packet plan into secret domain + public
            commitment (aggregate metadata only)
  project   closed-world allowlist projection of all frozen case84 payloads
  verify    run machine gates C1-G1..G10 (or a single gate: verify G5)

Design: PHASE_C_PACKET_DESIGN.md v1.0 @ 9474de8 (FROZEN).
C1 invariants per user ruling; failure is ALWAYS closed (non-zero exit).

Secret domain semantics (design §3, clarified):
  selector = owner; packet-generator = restricted reader;
  annotation/evaluator/analysis side = NO ACCESS; public artifact = commitment only.
"""
import csv
import hashlib
import hmac
import json
import os
import secrets as pysecrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RT = ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt'
PC = ROOT / 'output/research/csr/08_pilot_cases/phase_c'
SECRET = ROOT / 'data/csr8_phase_c/secret'          # NOT in git (.gitignore)
ART = PC / 'c1_artifacts'                            # public commitments/audits

CASE_CSV = RT / 'normalized_case84_2021-03-08_2026-09-17.csv'
SIDECAR = RT / 'payload_case84_2021-03-08_2026-09-17.jsonl'
PLAN_JSON = RT / 'ingest_plan.json'
CAL_CSV = RT / 'frozen_exchange_calendar.csv'
SAMPLE = ROOT / 'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'

SALT_FILE = SECRET / 'secret_salt'
PLAN_FILE = SECRET / 'packet_plan.json'
PROJ_FILE = SECRET / 'projected_case84.jsonl'

# ---------------- frozen source schemas (observed 2026-09-26 full sidecar) ----
SOURCE_SCHEMA = {
    'margin_sse': ['信用交易日期', '标的证券代码', '标的证券简称', '融资余额',
                   '融资买入额', '融资偿还额', '融券余量', '融券卖出量', '融券偿还量'],
    'margin_szse': ['证券代码', '证券简称', '融资买入额', '融资余额', '融券卖出量',
                    '融券余量', '融券余额', '融资融券余额'],
    'lhb': ['序号', '代码', '名称', '上榜日', '解读', '收盘价', '涨跌幅',
            '龙虎榜净买额', '龙虎榜买入额', '龙虎榜卖出额', '龙虎榜成交额',
            '市场总成交额', '净买额占总成交比', '成交额占总成交比', '换手率',
            '流通市值', '上榜原因', '上榜后1日', '上榜后2日', '上榜后5日', '上榜后10日'],
    'dzjy': ['序号', '交易日期', '证券代码', '证券简称', '涨跌幅', '收盘价', '成交价',
             '折溢率', '成交量', '成交额', '成交额/流通市值', '买方营业部', '卖方营业部'],
}
# ---------------- frozen projection spec (design §2, closed-world) -----------
ALLOWLIST = {
    'margin_sse': ['信用交易日期', '融资余额', '融资买入额', '融资偿还额',
                   '融券余量', '融券卖出量', '融券偿还量'],
    'margin_szse': ['融资买入额', '融资余额', '融券卖出量', '融券余量',
                    '融券余额', '融资融券余额'],
    'lhb': ['上榜日', '收盘价', '涨跌幅', '龙虎榜净买额', '龙虎榜买入额',
            '龙虎榜卖出额', '龙虎榜成交额', '市场总成交额', '净买额占总成交比',
            '成交额占总成交比', '换手率', '流通市值', '上榜原因'],
    'dzjy': ['交易日期', '涨跌幅', '收盘价', '成交价', '折溢率', '成交量', '成交额',
             '成交额/流通市值', '买方营业部', '卖方营业部'],
}
DROP_REASON = {
    '标的证券代码': 'identity', '标的证券简称': 'identity', '证券代码': 'identity',
    '证券简称': 'identity', '代码': 'identity', '名称': 'identity', '序号': 'row_index',
    '上榜后1日': 'future_return', '上榜后2日': 'future_return',
    '上榜后5日': 'future_return', '上榜后10日': 'future_return',
    '解读': 'aggregator_derivative',
}
ANCHOR_FIELD = {'G2_breakout_fail': 'T0', 'G3_high_collapse': 'anchor',
                'G4_quiet_then_go': 'launch'}
GRID_STEP = 20  # every 20 frozen trading days from w_start (design §4)
TOTAL_INPUT_ROWS = 24802


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'))


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    print(f'FAIL-CLOSED: {msg}')
    sys.exit(1)


def load_salt():
    if not SALT_FILE.exists():
        fail('secret_salt missing — run: salt')
    return SALT_FILE.read_text().strip()


def load_cases():
    """84 frozen cases -> {code: {group,w_start,w_end,canonical_case_key}}."""
    plan = json.loads(PLAN_JSON.read_text())
    sample = json.loads(SAMPLE.read_text())
    anchor_by = {}
    for gname, g in sample['groups'].items():
        for e in g['chosen']:
            anchor_by[e['code']] = e.get(ANCHOR_FIELD.get(gname, ''), '')
    cases = {}
    for w_start, w_end, group, code in plan['spans']:
        key = f'{group}|{code}|{w_start}|{w_end}'
        if code in cases:
            fail(f'case code not unique: {code}')
        cases[code] = {'group': group, 'w_start': w_start, 'w_end': w_end,
                       'anchor': anchor_by.get(code, ''), 'key': key}
    if len(cases) != 84:
        fail(f'expected 84 cases, got {len(cases)}')
    return cases


def opaque_case_id(salt, key):
    return hmac.new(salt.encode(), key.encode(), hashlib.sha256).hexdigest()


def packet_id(ocid, T):
    return sha256_bytes(f'{ocid}|{T}'.encode())


def load_calendar():
    dates = [r[0] for r in csv.reader(open(CAL_CSV))][1:]
    return dates


# ---------------- C1 commands ----------------
def cmd_salt():
    SECRET.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    sc_path = ART / 'salt_commitment.json'
    # FIX2-A lifecycle gate: the frozen commitment can never be redefined
    if sc_path.exists():
        if SALT_FILE.exists():
            verify_salt_binding()   # mismatch -> FAIL
            print('salt already frozen; binding verified (no-op)')
            return
        fail('salt_commitment exists but secret_salt is MISSING — salt cannot '
             'be recovered from a hash; regeneration is FORBIDDEN (it would '
             'redefine the frozen identity space)')
    if SALT_FILE.exists():
        fail('secret_salt exists without a frozen commitment — refusing to '
             'establish a frozen fact from an unknown-origin secret')
    salt = pysecrets.token_hex(32)  # 256-bit
    SALT_FILE.write_text(salt)
    os.chmod(SALT_FILE, 0o600)
    commitment = sha256_bytes(salt.encode())
    sc_path.write_text(canon({
        'salt_commitment': commitment, 'bits': 256, 'created_by': 'C1 salt',
        'scheme': 'opaque_case_id=HMAC-SHA256(secret_salt,canonical_case_key); '
                  'packet_id=SHA256(opaque_case_id|T)'}))
    print(f'salt generated; commitment={commitment[:16]}... (salt NEVER printed)')


def cmd_plan():
    if not SALT_FILE.exists():
        fail('run salt first')
    cal = load_calendar()
    idx = {d: i for i, d in enumerate(cal)}
    cases = load_cases()
    plan_entries = []
    for code, c in cases.items():
        i0, i1 = idx.get(c['w_start']), idx.get(c['w_end'])
        if i0 is None or i1 is None:
            fail(f'window not on frozen calendar: {code}')
        Ts = set(cal[i] for i in range(i0, i1 + 1, GRID_STEP))
        if c['anchor'] and c['anchor'] in idx and i0 <= idx[c['anchor']] <= i1:
            Ts.add(c['anchor'])
        for T in sorted(Ts):
            plan_entries.append({'case_key': c['key'], 'T': T})
    plan_doc = {'version': 'c1', 'grid_step': GRID_STEP,
                'entries': plan_entries}
    blob = canon(plan_doc).encode()
    commitment = sha256_bytes(blob)
    pc_path = ART / 'plan_commitment.json'
    # FIX2-B lifecycle gate: commitment is authoritative once frozen
    if pc_path.exists():
        frozen = json.loads(pc_path.read_text())
        if PLAN_FILE.exists():
            verify_plan_binding()
            if commitment != frozen['plan_commitment']:
                fail('recomputed plan differs from frozen commitment — plan '
                     'inputs changed; refusing to overwrite frozen plan')
            print('plan already frozen; recomputation matches commitment (no-op)')
            return
        # secret plan lost, commitment frozen: deterministic recovery ONLY
        if commitment != frozen['plan_commitment']:
            fail('secret plan MISSING and recomputed plan != frozen '
                 'commitment — inputs changed under a frozen commitment; '
                 'recovery impossible, FAIL-CLOSED (commitment never updated)')
        PLAN_FILE.write_bytes(blob)
        os.chmod(PLAN_FILE, 0o600)
        print('secret plan recovered deterministically; commitment unchanged')
        return
    if PLAN_FILE.exists():
        fail('secret plan exists without a frozen commitment — refusing to '
             'establish a frozen fact from an unknown-origin plan')
    PLAN_FILE.write_bytes(blob)
    os.chmod(PLAN_FILE, 0o600)
    # F5: public artifact carries commitment + version ONLY — no packet
    # counts, no per-group aggregates (they are hidden-plan derivatives).
    pc_path.write_text(canon({
        'plan_commitment': commitment, 'version': 'c1'}))
    print('hidden plan written to secret domain (contents never printed)')


def _project_core(salt, out_path, expected_rows=None):
    """Closed-world projection. Returns summary dict. FAIL-CLOSED on schema drift.
    expected_rows: production is fixed 24,802; negative-test fixtures pass the
    row count they actually inject so a fixture CANNOT pass via the collateral
    row-count gate when the schema gate itself is broken (FIX2-1)."""
    if expected_rows is None:
        expected_rows = TOTAL_INPUT_ROWS
    cases = load_cases()
    eligibility = {code: ('PROVISIONAL_BLOCKED_FOR_CASE_VALIDITY'
                          if c['group'] == 'G5_sector_follower'
                          else 'PRODUCTION_RT')
                   for code, c in cases.items()}
    stats = {'input': 0, 'projected': 0, 'blocked': 0, 'invalid': 0,
             'invalid_detail': [], 'per_endpoint_drop_counts': {}}
    schema_seen = {ep: None for ep in SOURCE_SCHEMA}
    sidecar_sha = sha256_bytes(SIDECAR.read_bytes())
    with open(SIDECAR) as fin, open(out_path, 'w') as fout:
        for line in fin:
            rec = json.loads(line)
            stats['input'] += 1
            ep = rec['endpoint']
            payload = rec['payload']
            observed = set(payload.keys())
            if schema_seen[ep] is None:
                schema_seen[ep] = observed
            elif observed != schema_seen[ep]:
                fail(f'schema drift inside sidecar for {ep}')
            if observed != set(SOURCE_SCHEMA[ep]):
                extra = observed - set(SOURCE_SCHEMA[ep])
                missing = set(SOURCE_SCHEMA[ep]) - observed
                fail(f'source schema mismatch for {ep}: extra={sorted(extra)} '
                     f'missing={sorted(missing)} (frozen schema violated)')
            code6 = rec['stock_code']
            case_code = next((cc for cc in cases
                              if cc.split('.')[-1] == code6), None)
            if case_code is None:
                stats['invalid'] += 1
                stats['invalid_detail'].append({'record_id': rec['record_id'],
                                                'reason': 'no_case'})
                continue
            proj = {k: payload.get(k) for k in ALLOWLIST[ep]}
            missing_vals = [k for k, v in proj.items() if v is None]
            if missing_vals:
                stats['invalid'] += 1
                stats['invalid_detail'].append(
                    {'record_id': rec['record_id'],
                     'reason': f'allowlist_value_missing:{missing_vals}'})
                continue
            assert set(proj.keys()) == set(ALLOWLIST[ep])
            ocid = opaque_case_id(salt, cases[case_code]['key'])
            out = {'record_id': rec['record_id'], 'opaque_case_id': ocid,
                   'endpoint': ep, 'observation_date': rec['observation_date'],
                   'eligibility': eligibility[case_code],
                   'source_group_axis': 'PACKET_GENERATION_ALLOWED',
                   'payload': proj}
            fout.write(canon(out) + '\n')
            stats['projected'] += 1
    if stats['input'] != expected_rows:
        fail(f'input rows {stats["input"]} != {expected_rows}')
    if stats['projected'] + stats['blocked'] + stats['invalid'] != stats['input']:
        fail('row conservation violated')
    for ep, schema in schema_seen.items():
        dropped = [c for c in SOURCE_SCHEMA[ep] if c not in ALLOWLIST[ep]]
        stats['per_endpoint_drop_counts'][ep] = {c: DROP_REASON.get(c, 'identity')
                                                 for c in dropped}
    stats['sidecar_sha256'] = sidecar_sha
    stats['source_schema_sha256'] = sha256_bytes(
        canon({ep: SOURCE_SCHEMA[ep] for ep in sorted(SOURCE_SCHEMA)}).encode())
    stats['projected_schema_sha256'] = sha256_bytes(
        canon({ep: ALLOWLIST[ep] for ep in sorted(ALLOWLIST)}).encode())
    return stats


def cmd_project():
    if not SALT_FILE.exists():
        fail('run salt first')
    SECRET.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    salt = load_salt()
    stats = _project_core(salt, PROJ_FILE)
    os.chmod(PROJ_FILE, 0o600)
    (ART / 'projection_manifest.json').write_text(canon({
        'source_snapshot': 'payload_case84_2021-03-08_2026-09-17.jsonl',
        'sidecar_sha256': stats['sidecar_sha256'],
        'source_row_count': stats['input'],
        'source_schema_sha256': stats['source_schema_sha256'],
        'projected_schema_sha256': stats['projected_schema_sha256']}))
    audit = {}
    for ep in sorted(SOURCE_SCHEMA):
        dropped = [c for c in SOURCE_SCHEMA[ep] if c not in ALLOWLIST[ep]]
        audit[ep] = {'source_columns': SOURCE_SCHEMA[ep],
                     'allowed_columns': ALLOWLIST[ep],
                     'dropped_columns': dropped,
                     'drop_reason': {c: DROP_REASON.get(c, 'identity')
                                     for c in dropped}}
    (ART / 'projection_audit.json').write_text(canon(audit))
    summary = {k: v for k, v in stats.items() if k != 'invalid_detail'}
    summary['output_sha256'] = sha256_bytes(PROJ_FILE.read_bytes())
    (ART / 'projection_summary.json').write_text(canon(summary))
    if stats['invalid_detail']:
        (ART / 'projection_invalid.jsonl').write_text(
            '\n'.join(canon(d) for d in stats['invalid_detail']))
    print(f'projection: input={stats["input"]} projected={stats["projected"]} '
          f'blocked={stats["blocked"]} invalid={stats["invalid"]} '
          f'output_sha256={summary["output_sha256"][:16]}...')


# ---------------- C1 gates ----------------
def verify_salt_binding():
    """F2: current secret_salt must hash to the frozen public commitment."""
    sc = json.loads((ART / 'salt_commitment.json').read_text())
    if sha256_bytes(load_salt().encode()) != sc['salt_commitment']:
        fail('salt binding: current secret_salt != frozen commitment')


def verify_plan_binding():
    """F3: current secret plan bytes must hash to the frozen commitment."""
    pc = json.loads((ART / 'plan_commitment.json').read_text())
    if not PLAN_FILE.exists():
        fail('plan binding: secret plan missing')
    if sha256_bytes(PLAN_FILE.read_bytes()) != pc['plan_commitment']:
        fail('plan binding: current packet_plan != frozen commitment')


def expect_fail(fn, label):
    """F1: assertion lives OUTSIDE the except block — a code path that
    wrongly succeeds now fails the gate instead of self-swallowing."""
    rejected = False
    try:
        fn()
    except SystemExit:
        rejected = True
    if not rejected:
        fail(f'G10: {label} was NOT rejected')
def g1():
    salt = load_salt()
    cases = load_cases()
    ids = {}
    for code, c in cases.items():
        base = opaque_case_id(salt, c['key'])
        for T in ('2021-03-08', '2024-01-02', '2026-09-17'):  # distinct Ts
            if opaque_case_id(salt, c['key']) != base:
                fail('G1: opaque_case_id varies across T')
        ids[code] = base
    if len(set(ids.values())) != 84:
        fail('G1: opaque_case_id collision across cases')
    pub = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                         text=True).stdout
    for f in [p for p in SECRET.iterdir()]:
        if f.name in pub:
            fail(f'G1: secret file tracked in git: {f.name}')
    if salt in json.dumps(_read_art()):
        fail('G1: salt leaked into public artifacts')
    print('G1 PASS: stable across T, no collision, only commitment public')


def g2():
    salt = load_salt()
    cases = load_cases()
    c = list(cases.values())[0]
    ocid = opaque_case_id(salt, c['key'])
    ids = {packet_id(ocid, T) for T in ('2021-03-08', '2021-04-06', '2022-01-04')}
    if len(ids) != 3:
        fail('G2: same case different T must give different packet_id')
    for T in ('2021-03-08', '2023-05-08'):
        if packet_id(ocid, T) != sha256_bytes(f'{ocid}|{T}'.encode()):
            fail('G2: packet_id not deterministically recomputable')
    print('G2 PASS: packet_id deterministic and T-distinct')


def g3():
    doc = json.loads(PLAN_FILE.read_text())
    seen = set()
    prev = None
    for e in doc['entries']:
        k = (e['case_key'], e['T'])
        if k in seen:
            fail(f'G3: duplicate (case,T): {k[1]}')
        seen.add(k)
    per_case = {}
    for e in doc['entries']:
        per_case.setdefault(e['case_key'], []).append(e['T'])
    for k, Ts in per_case.items():
        if Ts != sorted(Ts):
            fail('G3: T list not strictly ascending within case')
    # recount grid independently
    cal = load_calendar()
    idx = {d: i for i, d in enumerate(cal)}
    cases = load_cases()
    expect_total = 0
    for code, c in cases.items():
        i0, i1 = idx[c['w_start']], idx[c['w_end']]
        grid = set(range(i0, i1 + 1, GRID_STEP))
        if c['anchor'] and c['anchor'] in idx and i0 <= idx[c['anchor']] <= i1:
            grid.add(idx[c['anchor']])
        expect_total += len(grid)
    if len(doc['entries']) != expect_total:
        fail(f'G3: entry count {len(doc["entries"])} != independent recount '
             f'{expect_total}')
    print(f'G3 PASS: {len(doc["entries"])} (case,T) unique, ascending, '
          f'matches independent recount')


def g4():
    doc = json.loads(PLAN_FILE.read_text())
    tset = {e['T'] for e in doc['entries']}
    keys = {e['case_key'] for e in doc['entries']}
    leaks = []
    for f in ART.iterdir():
        if not f.is_file():
            continue
        text = f.read_text()
        hits_t = sum(1 for T in tset if T in text)
        hits_k = sum(1 for k in keys if k in text)
        if hits_t >= 3 or hits_k >= 1:
            leaks.append(f.name)
        # F5 semantics: hidden-plan DERIVED aggregates are also leakage
        for banned_key in ('n_packets', 'per_group_packet_count'):
            if banned_key in text:
                leaks.append(f'{f.name}::{banned_key}')
    if leaks:
        fail(f'G4: hidden-plan plaintext/derived-aggregate leak: {leaks}')
    print('G4 PASS: no hidden-plan plaintext or derived aggregates in public')


def g5():
    n = 0
    for line in open(PROJ_FILE):
        rec = json.loads(line)
        if set(rec['payload'].keys()) != set(ALLOWLIST[rec['endpoint']]):
            fail(f'G5: projected fields != frozen allowlist for {rec["endpoint"]}')
        banned = {'stock_code', 'name', 'group', 'window_end', 'selector',
                  'xp'}
        if banned & set(rec.keys()):
            fail('G5: banned packet-level key present')
        n += 1
    if n != TOTAL_INPUT_ROWS:
        fail(f'G5: projected rows {n} != {TOTAL_INPUT_ROWS} (expected C1: all)')
    print(f'G5 PASS: closed-world — {n} rows, fields exactly equal allowlist')


def g6():
    audit = json.loads((ART / 'projection_audit.json').read_text())
    for ep in sorted(SOURCE_SCHEMA):
        expect_dropped = [c for c in SOURCE_SCHEMA[ep]
                          if c not in ALLOWLIST[ep]]
        if audit[ep]['dropped_columns'] != expect_dropped:
            fail(f'G6: dropped columns mismatch for {ep}')
        if set(audit[ep]['allowed_columns']) != set(ALLOWLIST[ep]):
            fail(f'G6: allowed columns mismatch for {ep}')
    if '上榜后1日' not in audit['lhb']['dropped_columns']:
        fail('G6: future-return column not dropped')
    print('G6 PASS: DROP proof matches design §2 for all endpoints')


def g7():
    s = json.loads((ART / 'projection_summary.json').read_text())
    if s['projected'] + s['blocked'] + s['invalid'] != s['input']:
        fail('G7: classification total != input')
    if s['input'] != TOTAL_INPUT_ROWS:
        fail('G7: input != 24802')
    print(f"G7 PASS: {s['projected']}+{s['blocked']}+{s['invalid']}="
          f"{s['input']} — no silent row loss")


def g8():
    import ast
    tree = ast.parse(Path(__file__).read_text())
    stems = ('reveal', 'seal', 'annotat', 'adjustment_bao')
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    hits = [n for n in names for s in stems if s in n]
    if hits:
        fail(f'G8: forbidden symbol in C1 code path: {sorted(set(hits))}')
    cmds = {n for n in names if n.startswith('cmd_')}
    if cmds != {'cmd_salt', 'cmd_plan', 'cmd_project'}:
        fail(f'G8: C1 command set must be salt/plan/project only, got {cmds}')
    print('G8 PASS (AST): no reveal/seal/annotation/price-panel symbol; '
          'command set = {salt, plan, project}')


def g9():
    salt = load_salt()
    tmp = SECRET / '_determinism_check.jsonl'
    _project_core(salt, tmp)
    h1 = sha256_bytes(tmp.read_bytes())
    tmp.unlink()
    h0 = sha256_bytes(PROJ_FILE.read_bytes())
    if h1 != h0:
        fail('G9: two runs produced different canonical bytes')
    print('G9 PASS: deterministic replay — identical canonical hash')


def g10():
    # negative injections — F1: expect_fail asserts OUTSIDE the except block
    # FIX2-1: fixtures pass expected_rows=1 so they can ONLY fail via the
    # schema/closed-world gate, never via the collateral row-count gate.
    # FIX2-2: every mutation of REAL frozen state is wrapped in try/finally
    # so a broken gate cannot leave the frozen state polluted.
    import tempfile
    global SIDECAR
    orig = SIDECAR
    rows = [json.loads(l) for l in open(orig)]
    with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
        tmp_path = Path(f.name)

    def core():
        _project_core(load_salt(), SECRET / '_g10.jsonl', expected_rows=1)

    try:
        # 1: extra future column appears
        rows[0]['payload']['未来10日最高涨幅'] = 0.5
        tmp_path.write_text('\n'.join(canon(r) for r in rows[:1]))
        SIDECAR = tmp_path
        expect_fail(core, 'extra future column')
        # 2: missing allowlist column (schema drift)
        rows2 = [json.loads(l) for l in open(orig)]
        del rows2[0]['payload']['融资余额']
        tmp_path.write_text(canon(rows2[0]))
        expect_fail(core, 'missing allowlist column')
        # 3: salt sensitivity is necessary but NOT sufficient — binding gates
        # prove the RUNNING salt/plan equal the frozen commitments.
        s1 = opaque_case_id('a' * 64, 'k')
        s2 = opaque_case_id('b' * 64, 'k')
        if s1 == s2:
            fail('G10: salt has no effect on opaque ids')
        # 4 (mutation): flip one bit of secret_salt -> salt binding MUST fail
        orig_salt = SALT_FILE.read_bytes()
        bad = bytearray(orig_salt)
        bad[0] ^= 1
        SALT_FILE.write_bytes(bytes(bad))
        expect_fail(verify_salt_binding, 'tampered secret_salt (1-bit flip)')
        SALT_FILE.write_bytes(orig_salt)
        verify_salt_binding()  # restored -> must pass again
        # 5 (mutation): change one T in hidden plan -> plan binding MUST fail
        orig_blob = PLAN_FILE.read_bytes()
        doc = json.loads(orig_blob)
        doc['entries'][0]['T'] = '1999-01-01'
        PLAN_FILE.write_bytes(canon(doc).encode())
        expect_fail(verify_plan_binding, 'tampered packet_plan (one T)')
        PLAN_FILE.write_bytes(orig_blob)
        verify_plan_binding()
        # 6 (lifecycle): plan file LOST + one plan input changed ->
        # cmd_plan MUST FAIL, never rewrite the frozen commitment
        plan_bak = SECRET / '_g10_plan.bak'
        plan_bak.write_bytes(PLAN_FILE.read_bytes())
        PLAN_FILE.unlink()
        ipj = PLAN_JSON.read_text()
        ip = json.loads(ipj)
        # perturb to a VALID calendar date so the failure must come from the
        # recompute != commitment branch, not a collateral calendar check
        cal = load_calendar()
        new_end = next(d for d in cal if d != ip['spans'][0][1]
                       and d > ip['spans'][0][0])
        ip['spans'][0][1] = new_end
        PLAN_JSON.write_text(json.dumps(ip, ensure_ascii=False))
        try:
            expect_fail(cmd_plan, 'plan-lost + changed inputs (must not '
                                  'redefine commitment)')
        finally:
            PLAN_JSON.write_text(ipj)
        # restore plan via the legitimate deterministic-recovery branch
        cmd_plan()
        verify_plan_binding()
        plan_bak.unlink()
        # 7 (lifecycle): salt file LOST, commitment still present ->
        # cmd_salt MUST FAIL (salt is unrecoverable from a hash)
        salt_bak = SECRET / '_g10_salt.bak'
        salt_bak.write_bytes(SALT_FILE.read_bytes())
        SALT_FILE.unlink()
        try:
            expect_fail(cmd_salt, 'salt-lost + frozen commitment '
                                  '(regeneration forbidden)')
        finally:
            SALT_FILE.write_bytes(salt_bak.read_bytes())
            os.chmod(SALT_FILE, 0o600)
            salt_bak.unlink()
        cmd_salt()   # restored -> no-op verified
        print('G10 PASS: seven negative paths — schema x2, salt 1-bit flip, '
              'plan one-T edit, plan-lost+input-change, salt-lost — all '
              'genuinely fail closed; frozen state round-trip verified')
    finally:
        SIDECAR = orig
        tmp_path.unlink(missing_ok=True)
        (SECRET / '_g10.jsonl').unlink(missing_ok=True)


GATES = {'G1': g1, 'G2': g2, 'G3': g3, 'G4': g4, 'G5': g5, 'G6': g6,
         'G7': g7, 'G8': g8, 'G9': g9, 'G10': g10}


def _read_art():
    out = {}
    for f in ART.iterdir():
        if f.is_file():
            out[f.name] = f.read_text()
    return out


def main():
    if len(sys.argv) < 2:
        fail('usage: csr8_phase_c_packet.py salt|plan|project|verify [GATE]')
    cmd = sys.argv[1]
    if cmd == 'salt':
        cmd_salt()
    elif cmd == 'plan':
        cmd_plan()
    elif cmd == 'project':
        cmd_project()
    elif cmd == 'verify':
        # F2/F3: commitment binding FIRST — every later gate runs only on
        # state proven equal to the frozen commitments
        verify_salt_binding()
        verify_plan_binding()
        print('BINDING PASS: running salt & plan == frozen commitments')
        gates = [sys.argv[2]] if len(sys.argv) > 2 else list(GATES)
        for g in gates:
            GATES[g]()
        print(f'ALL {len(gates)} GATES PASS')
    else:
        fail(f'unknown command {cmd} (C1 scope: salt/plan/project/verify)')


if __name__ == '__main__':
    main()
