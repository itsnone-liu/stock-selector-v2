#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase F §9.3 — outcome join contract（trusted 侧）。

* join 键 = (opaque_case_id, packet_id) —— 只有盲键，不含任何 identity。
* outcome 行由 trusted 侧用 secret_salt 解析 sealed case → 逐 stock 读取冻结
  BaoStock unadj 价格，计算 T→T+H close-to-close forward return。
* 删失语义显式：outcome_as_of 之前窗口未走完 / 价格缺失 ⇒ censored=true、
  forward_return=null、censor_reason 明示；censored ⇔ forward_return is null。
* join() 由 trusted 侧把 outcome 列并入盲态 analysis 行，产出
  analysis_labeled/（独立域：盲态 analysis 域在 join 之后仍必须通过 §9.2 全部
  渗透 gate —— labeled 数据经分析侧 guarded reader 不可达）。
"""
import argparse
import gzip
import hashlib
import hmac
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402
from csr8_phase_f_bridge import (CSR, SID, ROOT, canon, fail,
                                 sealed_pairs, read_analysis_rows,
                                 load_case_keys, resolve_codes)

CAL = ROOT / 'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'
PRICE = ROOT / 'data/adjustment_baostock/per_stock'
HORIZONS = (5, 20, 60)
OUTCOME_KEYS = {'opaque_case_id', 'packet_id', 'T', 'horizon_days',
                'outcome_as_of', 'forward_return', 'censored', 'censor_reason'}
CENSOR_WINDOW = 'OUTCOME_WINDOW_NOT_ELAPSED'
CENSOR_PRICE = 'PRICE_MISSING_AT_HORIZON'
# outcome 域合法携带 outcome 值（这正是它的用途）；禁区 = identity/secret 类。
# 未来类键在此域合法 —— 数据本身由 outcome_as_of 显式右删失界定。
OUTCOME_FORBIDDEN_KEYS = {
    'case_key', 'case_id', 'identity', 'symbol', 'ticker', 'code',
    'stock_code', 'name', 'person', 'user', 'security', 'sh', 'sz',
    'secret', 'secret_salt', 'salt', 'api_key', 'token',
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def outcomes_dir(root=CSR, sid=SID):
    return Path(root) / 'outcomes' / sid


def labeled_dir(root=CSR, sid=SID):
    return Path(root) / 'analysis_labeled' / sid


def load_calendar(cal_path=CAL):
    """冻结日历：embedded sha + 1386 天权威校验（只读）。"""
    lines = Path(cal_path).read_text().splitlines()
    if (len(lines) < 4 or not lines[0].startswith('# source=')
            or not lines[1].startswith('# n_days=') or lines[2] != 'date'):
        fail('frozen calendar header/schema mismatch')
    meta = lines[1].split('sha256=', 1)
    days = lines[3:]
    if len(days) != 1386 or sha(('date\n' + '\n'.join(days) + '\n').encode()) != meta[1].strip():
        fail('frozen calendar embedded SHA/day-count mismatch')
    return days


def load_unadj(code, price_root=PRICE):
    fp = Path(price_root) / f'{code}.json.gz'
    if not fp.exists():
        fail(f'trusted price source missing: {code}')
    obj = json.loads(gzip.open(fp, 'rt').read())
    return {r[0]: r[4] for r in obj.get('unadj', [])}


def build_outcomes(root=CSR, sid=SID, cal_path=CAL, price_root=PRICE,
                   outcome_as_of=None):
    root = Path(root)
    cal = load_calendar(cal_path)
    as_of = outcome_as_of or cal[-1]
    codes = resolve_codes(root, sid)
    rows = []
    for _, rev, _ in sealed_pairs(root, sid):
        rp = rev['payload']
        ocid, T, pid = rp['opaque_case_id'], rp['T'], rp['packet_id']
        if ocid not in codes:
            fail(f'trusted side cannot resolve sealed case {ocid[:12]}…')
        closes = load_unadj(codes[ocid], price_root)
        if T not in closes:
            fail(f'price missing at T for sealed case {ocid[:12]}…')
        c0 = float(closes[T])
        iT = cal.index(T)
        for h in HORIZONS:
            tgt_idx = iT + h
            tgt = cal[tgt_idx] if tgt_idx < len(cal) else None
            if tgt is None or tgt > as_of:
                row = {'censored': True, 'forward_return': None,
                       'censor_reason': CENSOR_WINDOW}
            elif tgt not in closes:
                row = {'censored': True, 'forward_return': None,
                       'censor_reason': CENSOR_PRICE}
            else:
                fwd = float(closes[tgt]) / c0 - 1.0
                row = {'censored': False,
                       'forward_return': f'{fwd:.10f}', 'censor_reason': None}
            rows.append({'opaque_case_id': ocid, 'packet_id': pid, 'T': T,
                         'horizon_days': h, 'outcome_as_of': as_of, **row})
            if set(rows[-1]) != OUTCOME_KEYS:
                fail('outcome row schema drift')
    odir = outcomes_dir(root, sid)
    odir.mkdir(parents=True, exist_ok=True)
    (odir / 'outcomes.jsonl').write_text(''.join(canon(r) + '\n' for r in rows))
    contract = {
        'contract_version': 'csr8-f-outcome-join-v1', 'session_id': sid,
        'join_keys': ['opaque_case_id', 'packet_id'],
        'identity_exposure': 'none — outcome rows carry blind join keys only',
        'horizons_trading_days': list(HORIZONS),
        'return_definition': 'close_to_close unadj: close[T+H]/close[T]-1, '
                             'fixed 10dp decimal string',
        'price_source': {'source_id': 'baostock_unadjusted_v1',
                         'per_stock_root': 'data/adjustment_baostock/per_stock '
                                           '(frozen universe commitment)'},
        'censoring': {
            'semantics': 'right-censored at outcome_as_of: forward_return is '
                         'null iff censored is true',
            'outcome_as_of_default': 'last frozen calendar day',
            'reasons': {CENSOR_WINDOW: 'horizon end beyond outcome_as_of or '
                                       'calendar end',
                        CENSOR_PRICE: 'no unadj close at horizon date'},
        },
        'n_rows': len(rows),
    }
    (odir / 'outcome_join_contract.json').write_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=1))
    return {'contract': contract, 'rows': rows}


def read_outcomes(root=CSR, sid=SID):
    p = outcomes_dir(root, sid) / 'outcomes.jsonl'
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def verify_outcomes(root=CSR, sid=SID, cal_path=CAL, price_root=PRICE):
    """§9.3 全 gate（audit 侧实测，含真实重算与反向渗透）。"""
    root = Path(root)
    from csr8_phase_f_bridge import _walk, _tokens, UNIVERSE
    gates = {}
    rows = read_outcomes(root, sid)
    arows = read_analysis_rows(root, sid)
    want = {(r['opaque_case_id'], r['packet_id'], h)
            for r in arows for h in HORIZONS}
    got = [(r['opaque_case_id'], r['packet_id'], r['horizon_days']) for r in rows]
    if len(got) != len(set(got)) or set(got) != want:
        fail('G-F-JOIN-KEYS: outcome/analysis join-key coverage mismatch')
    gates['G-F-JOIN-KEYS'] = 'PASS'
    for r in rows:
        if set(r) != OUTCOME_KEYS:
            fail('G-F-OUTCOME-SCHEMA: schema drift')
        if r['censored'] != (r['forward_return'] is None):
            fail('G-F-CENSOR: censored <=> forward_return null violated')
        if r['censored'] and r['censor_reason'] not in (CENSOR_WINDOW, CENSOR_PRICE):
            fail('G-F-CENSOR: reason not explicit')
        if not r['censored'] and r['censor_reason'] is not None:
            fail('G-F-CENSOR: observed row carries a censor reason')
    gates['G-F-OUTCOME-SCHEMA'] = 'PASS'
    gates['G-F-CENSOR'] = 'PASS'
    keys, strings = set(), []
    for r in rows:
        _walk(r, keys, strings)
    hit = sorted(keys & OUTCOME_FORBIDDEN_KEYS)
    if hit:
        fail(f'G-F-OUTCOME-BLIND: forbidden keys in outcome rows: {hit}')
    codes = set(json.loads(Path(UNIVERSE).read_text())['codes'])
    toks = _tokens(strings)
    hitc = sorted(t for t in toks if t in codes or f'sz.{t}' in codes or f'sh.{t}' in codes)
    if hitc:
        fail(f'G-F-OUTCOME-BLIND: identity tokens in outcome rows: {hitc}')
    gates['G-F-OUTCOME-BLIND'] = 'PASS'
    # 真实重算（audit 侧持价重导出抽全量）
    codes_map = resolve_codes(root, sid)
    cal = load_calendar(cal_path)
    as_of = rows[0]['outcome_as_of'] if rows else cal[-1]
    for r in rows:
        ocid, T, h = r['opaque_case_id'], r['T'], r['horizon_days']
        closes = load_unadj(codes_map[ocid], price_root)
        tgt = cal[cal.index(T) + h] if cal.index(T) + h < len(cal) else None
        if tgt is None or tgt > as_of:
            ok = r['censored'] and r['censor_reason'] == CENSOR_WINDOW
        elif tgt not in closes:
            ok = r['censored'] and r['censor_reason'] == CENSOR_PRICE
        else:
            fwd = float(closes[tgt]) / float(closes[T]) - 1.0
            ok = (not r['censored']
                  and r['forward_return'] == f'{fwd:.10f}')
        if not ok:
            fail(f'G-F-OUTCOME-RECOMPUTE: row mismatch {ocid[:12]}… H={h}')
    gates['G-F-OUTCOME-RECOMPUTE'] = 'PASS'
    return gates


def join(root=CSR, sid=SID):
    """trusted join：盲态 analysis 行 + outcome 列 → analysis_labeled/。"""
    root = Path(root)
    arows = read_analysis_rows(root, sid)
    orows = read_outcomes(root, sid)
    by_key = {(r['opaque_case_id'], r['packet_id']): [] for r in arows}
    for r in orows:
        by_key.setdefault((r['opaque_case_id'], r['packet_id']), []).append(r)
    labeled = []
    for a in arows:
        outs = by_key.get((a['opaque_case_id'], a['packet_id']), [])
        if len(outs) != len(HORIZONS):
            fail(f"join incomplete for {a['packet_id']}")
        for o in sorted(outs, key=lambda x: x['horizon_days']):
            labeled.append({**a, 'horizon_days': o['horizon_days'],
                            'outcome_as_of': o['outcome_as_of'],
                            'forward_return': o['forward_return'],
                            'censored': o['censored'],
                            'censor_reason': o['censor_reason']})
    ldir = labeled_dir(root, sid)
    ldir.mkdir(parents=True, exist_ok=True)
    (ldir / 'analysis_labeled.jsonl').write_text(
        ''.join(canon(r) + '\n' for r in labeled))
    manifest = {
        'join_version': 'csr8-f-outcome-join-v1', 'session_id': sid,
        'join_keys': ['opaque_case_id', 'packet_id'],
        'n_analysis_rows': len(arows), 'n_outcome_rows': len(orows),
        'n_labeled_rows': len(labeled),
        'censored': sum(1 for r in labeled if r['censored']),
        'contract_sha256': sha((outcomes_dir(root, sid) /
                                'outcome_join_contract.json').read_bytes()),
    }
    (ldir / 'join_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1))
    return {'manifest': manifest, 'rows': labeled}


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--root', type=Path, default=CSR)
    a.add_argument('--cal', type=Path, default=CAL)
    a.add_argument('--price-root', type=Path, default=PRICE)
    a.add_argument('--outcome-as-of')
    a.add_argument('--build', action='store_true')
    a.add_argument('--verify', action='store_true')
    a.add_argument('--join', action='store_true')
    x = a.parse_args()
    if x.build:
        out = build_outcomes(x.root, cal_path=x.cal, price_root=x.price_root,
                             outcome_as_of=x.outcome_as_of)
        print(json.dumps({'n_rows': out['contract']['n_rows']},
                         sort_keys=True, separators=(',', ':')))
    if x.verify:
        print(json.dumps(verify_outcomes(x.root, cal_path=x.cal,
                                         price_root=x.price_root),
                         sort_keys=True, separators=(',', ':')))
    if x.join:
        print(json.dumps(join(x.root)['manifest'],
                         sort_keys=True, separators=(',', ':')))
    if not (x.build or x.verify or x.join):
        print(json.dumps({'phase': 'F.3', 'commands': ['--build', '--verify', '--join']},
                         sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
