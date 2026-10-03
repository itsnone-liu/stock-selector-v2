#!/usr/bin/env python3
"""Build the closed-world baostock price-store manifest (outcome-free).

Hashes every per-stock file without parsing, decoding, mapping, or
semantically inspecting any price series, and derives the union trading
calendar as a hash-only commitment over session-date strings extracted from
the fetch manifest metadata (first/last bounds only; no per-case prices).
"""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'data/adjustment_baostock'
OUT = ROOT / 'docs/audit/evidence/phase_i_price_store_manifest.json'


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def main():
    fetch = json.loads((STORE / 'fetch_manifest.json').read_text())
    entries = []
    mismatches = []
    per_stock = STORE / 'per_stock'
    files = sorted(per_stock.glob('*.json.gz'))
    declared = fetch.get('stocks', {})
    for f in files:
        code = f.name[:-len('.json.gz')]
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        size = f.stat().st_size
        entries.append({'relative_path': f'per_stock/{f.name}', 'code': code, 'bytes': size, 'sha256': h})
        d = declared.get(code)
        if not isinstance(d, dict) or d.get('sha256') != h:
            mismatches.append({'code': code, 'declared': d.get('sha256') if isinstance(d, dict) else None, 'actual': h})
    undeclared = sorted(set(declared) - {e['code'] for e in entries})
    manifest = {
        'report_type': 'PHASE_I_PRICE_STORE_CLOSED_WORLD_MANIFEST',
        'store_root': 'data/adjustment_baostock/per_stock/',
        'fetch_manifest_sha256': hashlib.sha256((STORE / 'fetch_manifest.json').read_bytes()).hexdigest(),
        'file_count': len(entries),
        'entries': entries,
        'closed_world': (not mismatches) and (not undeclared) and len(entries) == len(declared),
        'declared_stock_count': len(declared),
        'undeclared_codes': undeclared,
        'hash_mismatches_vs_fetch_manifest': mismatches,
        'coverage_bounds': {
            'any_first': min((declared[c].get('first') for c in declared if isinstance(declared[c], dict)), default=None),
            'any_last': max((declared[c].get('last') for c in declared if isinstance(declared[c], dict)), default=None),
        },
        'calendar_commitment': {
            'definition': 'union of per-stock session-date sets across the 5,240-file store; materialized only at I2 unlock from file contents, hashed then; I1 pins the file set it derives from',
            'derivation_input_closed_world_sha256': None,
        },
        'outcome_read': 'none; per-stock bytes hashed only, not parsed, decoded, mapped, or semantically inspected',
    }
    # closed-world sha over the entry list itself (path+bytes+sha256 tuples)
    manifest['calendar_commitment']['derivation_input_closed_world_sha256'] = hashlib.sha256(canon(entries).encode()).hexdigest()
    # canonical self-digest: sha256 of the complete manifest (all fields present) with manifest_sha256 set to ""
    manifest['manifest_sha256'] = ''
    manifest['canonicalization_rule'] = 'manifest_sha256 = sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",",":")) with manifest_sha256 set to ""); verification replaces the field with "" and recomputes'
    digest = hashlib.sha256(canon(manifest).encode()).hexdigest()
    manifest['manifest_sha256'] = digest
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': digest, 'file_count': len(entries), 'closed_world': manifest['closed_world'], 'mismatches': len(mismatches), 'undeclared': len(undeclared)}))


if __name__ == '__main__':
    main()
