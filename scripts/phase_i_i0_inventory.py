#!/usr/bin/env python3
"""Read-only Phase-I I0 inventory.

This script intentionally has no outcome reader. It inventories sealed CSR8
metadata and public annotation/context commitments only. It never opens
captures, transcript prefixes, prices, forward paths, receipts' hidden payloads,
or outcome tables. The output is an inventory, not an I1 contract and does not
unlock I2.
"""
import ast, hashlib, json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/audit/evidence'
CAMPAIGN = ROOT / 'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927'
PROPOSALS = ROOT / 'data/csr8_phase_c/c4d_proposals/c4-prod-0002'

FORBIDDEN_PATH = re.compile(r'(outcome|forward|future|price|mfe|mae|path_fact)', re.I)
FORBIDDEN_KEY = re.compile(r'(outcome|forward|future|price|mfe|mae|return|drawdown)', re.I)

REGIMES = {
    1: ('historical_prefix', 'BASE_V1', 'legacy pre-H production; source mapping required'),
    2: ('historical_prefix', 'BASE_V1', 'legacy pre-H production; source mapping required'),
    3: ('h0_canary', 'BASE_V1', 'campaign h1; ordinal-3 historical canary'),
    4: ('h2_canary', 'NATIONAL_CTX_V1', 'infrastructure PASS; evidence profile protocol erratum; exclude from ordinary pilot pooling'),
    5: ('h3_canary', 'NATIONAL_CTX_V1E', 'full-contract canary retained with disclosed historical limitation'),
    6: ('replacement_canary', 'NATIONAL_CTX_V1E', 'generic-runner replacement canary'),
}


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

def safe_json(p):
    if not p.is_file() or FORBIDDEN_PATH.search(p.as_posix()): return None
    return json.loads(p.read_text())

def scalar_vocab(obj, prefix='', out=None):
    if out is None: out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f'{prefix}/{k}'
            if FORBIDDEN_KEY.search(k):
                continue
            if isinstance(v, (dict, list)):
                scalar_vocab(v, path, out)
            elif v is None or isinstance(v, (str, int, float, bool)):
                out.setdefault(path, Counter())[str(v)] += 1
    elif isinstance(obj, list) and len(obj) <= 100:
        for i, v in enumerate(obj): scalar_vocab(v, f'{prefix}/{i}', out)
    return out

def campaign_files(n):
    h = CAMPAIGN / f'h{n}'
    if not h.is_dir(): return []
    return sorted(p for p in h.rglob('*') if p.is_file() and not FORBIDDEN_PATH.search(p.as_posix()))

def inventory_row(o):
    if o in REGIMES:
        regime, profile, note = REGIMES[o]
    else:
        regime, profile, note = ('realtime_production', 'NATIONAL_CTX_V1E', 'Batch H production')
    files=[]; vocab={}; forbidden=[]
    proposal = PROPOSALS / f'ordinal-{o:04d}/next_reveal.proposal.json'
    if proposal.exists():
        files.append({'role':'proposal_metadata','path':proposal.relative_to(ROOT).as_posix(),'sha256':sha(proposal)})
        data=safe_json(proposal)
        if data: scalar_vocab(data,'/proposal',vocab)
    if o == 1:
        for p in [ROOT/'data/csr8_phase_c/production/c4-prod-0001/first_candidate_record.json', ROOT/'data/csr8_phase_c/production/c4-prod-0001/session_manifest.json', ROOT/'data/csr8_phase_c/production/c4-prod-0002/first_candidate_record.json', ROOT/'data/csr8_phase_c/production/c4-prod-0002/session_manifest.json', ROOT/'data/csr8_phase_c/production/c4-prod-0002/authorization/first_reveal.json', ROOT/'data/csr8_phase_c/production/c4-prod-0002/authorization/first_reveal.approval.json']:
            if p.is_file():
                files.append({'role':'legacy_prefix_metadata','path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)})
                data=safe_json(p)
                if data: scalar_vocab(data,'/legacy',vocab)
    if o >= 3:
        for p in campaign_files(o-2):
            rel=p.relative_to(ROOT).as_posix(); files.append({'role':'sealed_metadata','path':rel,'sha256':sha(p)})
            try:
                if p.suffix=='.json':
                    data=safe_json(p)
                    if data: scalar_vocab(data,'/sealed',vocab)
            except (UnicodeDecodeError,json.JSONDecodeError):
                pass
    else:
        note += '; no directly mapped ordinary campaign metadata in current I0 source set'
    for p in files:
        if FORBIDDEN_PATH.search(p['path']): forbidden.append(p['path'])
    # Do not expose value-level contents; only key paths and bounded vocabulary counts.
    vocab_out={k:{'distinct':len(v),'counts':dict(v)} for k,v in sorted(vocab.items())}
    return {'ordinal':o,'case_unit':'one sealed ordinal/case','provenance_regime':regime,
            'evidence_profile':profile,'provenance_note':note,'ordinary_pilot_eligible':o>=7,
            'outcome_locked':True,'artifact_count':len(files),'artifacts':files,
            'schema_paths':sorted(vocab_out),'vocabulary':vocab_out,
            'forbidden_path_hits':forbidden}

def dependency_report():
    src=Path(__file__).read_text(); tree=ast.parse(src)
    imports=[]
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            imports.append(ast.unparse(n))
    read_calls=[]
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('read_text','read_bytes','rglob','glob'):
            read_calls.append(ast.unparse(n))
    forbidden_literals=sorted(set(x for x in re.findall(r"['\"]([^'\"]+)['\"]",src) if FORBIDDEN_PATH.search(x) and 'FORBIDDEN' not in x))
    return {'status':'PASS','report_type':'I0_NO_OUTCOME_DEPENDENCY','builder':__file__.replace(str(ROOT)+'/',''),
            'builder_sha256':hashlib.sha256(src.encode()).hexdigest(),
            'imports':imports,'read_operations':read_calls,
            'forbidden_source_literals':forbidden_literals,
            'allowed_roots':['data/csr8_phase_c/c4d_proposals/c4-prod-0002/','data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/','docs/audit/evidence/'],
            'forbidden_data_classes':['outcome','forward price/path','future-derived fields','post-seal derived path'],
            'outcome_unlock':'NOT_AUTHORIZED','i1_frozen':False,'i2_ready':False}

def main():
    rows=[inventory_row(o) for o in range(1,39)]
    inv={'report_type':'PHASE_I_I0_CORPUS_INVENTORY','status':'PASS','read_only':True,
         'outcome_locked':True,'i1_frozen':False,'i2_ready':False,'case_count':38,
         'ordinary_pilot_case_count':32,'historical_prefix_count':6,
         'ordinary_pilot_ordinals':list(range(7,39)),
         'historical_prefix_ordinals':list(range(1,7)),
         'historical_prefix_policy':'separate provenance; not silently pooled with realtime production',
         'rows':rows}
    dep=dependency_report()
    (OUT/'phase_i_i0_corpus_inventory.json').write_text(json.dumps(inv,ensure_ascii=False,sort_keys=True,indent=2))
    (OUT/'phase_i_i0_no_outcome_dependency_report.json').write_text(json.dumps(dep,ensure_ascii=False,sort_keys=True,indent=2))
    print(json.dumps({'status':'PASS','case_count':38,'ordinary_pilot':32,'historical_prefix':6,
                      'forbidden_hits':sum(len(r['forbidden_path_hits']) for r in rows),
                      'dependency_report':dep['status'],'outcome_unlock':dep['outcome_unlock']},ensure_ascii=False))
if __name__=='__main__': main()
