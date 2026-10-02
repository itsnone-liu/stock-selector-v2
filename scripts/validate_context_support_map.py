#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a NATIONAL_CTX context support map (NC-ERRATUM-1 revision).

H2-CANARY-FIX1 item 4: the duplicate rule is now PER-HYPOTHESIS — the
same context record MAY legitimately support several hypotheses (one
stock record backs rt_H01/rt_H02/rt_H05/rt_H06); duplicates are only
forbidden within a single hypothesis reference list.  The ordinal
binding is generic (map.ordinal == sidecar.ordinal); the sealed
ordinal-4 map (partitioned refs, market-only) remains valid under both
the old and the new rule.
"""
import argparse, hashlib, json, re
from pathlib import Path

SUPPORT_MAP_VERSION = 'csr8-national-context-support-v1'
HYPOTHESES = {'rt_H01', 'rt_H02', 'rt_H03', 'rt_H04', 'rt_H05', 'rt_H06'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('map')
    ap.add_argument('--sidecar', required=True)
    ap.add_argument('--packet', required=True)
    a = ap.parse_args()
    m = json.loads(Path(a.map).read_text())
    s = json.loads(Path(a.sidecar).read_text())
    assert set(m) == {'version', 'ordinal', 'packet_sha256',
                      'context_sha256', 'judgments'} \
        and m['version'] == SUPPORT_MAP_VERSION \
        and isinstance(m['ordinal'], int) and isinstance(s['ordinal'], int) \
        and m['ordinal'] == s['ordinal'] \
        and set(m['judgments']) == HYPOTHESES \
        and re.fullmatch(r'[0-9a-f]{64}', m['packet_sha256']) \
        and re.fullmatch(r'[0-9a-f]{64}', m['context_sha256'])
    assert m['packet_sha256'] == sha(a.packet) \
        and m['context_sha256'] == s['context_commitment_sha256']
    ids = {r['context_record_id'] for r in
           s['stock_capital_records'] + s['market_etf_records']}
    refs = [x for j in m['judgments'].values() for x in j]
    assert all(isinstance(x, str) and x in ids for x in refs)
    # NC-ERRATUM-1: per-hypothesis dedup (cross-hypothesis reuse allowed)
    for hid, jrefs in m['judgments'].items():
        assert len(jrefs) == len(set(jrefs)), \
            f'duplicate references within {hid}'
    print(json.dumps({'status': 'PASS', 'references': len(refs),
                      'ordinal': m['ordinal']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
