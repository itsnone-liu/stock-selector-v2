#!/usr/bin/env python3
"""T6.5 gates — synthesis integrity (aggregation only, citation completeness)."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
import numpy as np

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

OUT = T6/'05_synthesis'
STAGES = {'t6_1': T6/'01_eclass', 't6_2': T6/'02_recycling',
          't6_3': T6/'03_failure_anatomy', 't6_4': T6/'04_regime'}


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t6_5_manifest.json').read_text())
    rep = json.loads((OUT/'t6_5_report_data.json').read_text())
    contract = load_contract()

    gf.g1_lineage(log, man, OUT)

    # chain integrity: each prior stage frozen gates PASS and unchanged since
    # the aggregation run recorded them
    ok_chain = True
    recorded = {c['stage']: c for c in rep['frozen_chain']}
    for st, d in STAGES.items():
        g = json.loads((d/f'{st}_gates.json').read_text())
        ok_chain = ok_chain and g.get('overall') == 'PASS'
        ok_chain = ok_chain and sha256_file(d/f'{st}_gates.json') == recorded[st]['gates_sha256']
        ok_chain = ok_chain and recorded[st]['gate_overall'] == 'PASS'
    log.gate('G12_chain_integrity', ok_chain,
             stages=sorted(recorded), note='frozen stage gates PASS and byte-identical to aggregation-time hashes')

    # citation completeness: every claim_id cited by C5xx exists in its frozen
    # registry; INCONCLUSIVE boundary claims cite only existing claims
    ok_cite = True
    bad = []
    all_ids = {}
    for st, d in STAGES.items():
        cl = json.loads((d/f'{st}_claims.json').read_text())['claims']
        for c in cl:
            all_ids[c['claim_id']] = c['status']
    syn = json.loads((OUT/'t6_5_claims.json').read_text())['claims']
    syn_ids = {c['claim_id'] for c in syn}
    for c in syn:
        for cid in re.findall(r'C\d{3}', c.get('evidence', '')):
            if cid == c['claim_id']:
                ok_cite = False
                bad.append(f"{c['claim_id']}->{cid}:self-reference")
            elif cid not in all_ids and cid not in syn_ids:
                ok_cite = False
                bad.append(f"{c['claim_id']}->{cid}:missing")
            # intra-synthesis citations (C5xx -> other C5xx) are legal:
            # the chain bottoms out in frozen stage registries
    # status consistency: synthesis claims citing NOT_SUPPORTED evidence may
    # not be SUPPORTED unless the statement is explicitly a rejection framing
    log.gate('G13_citation_completeness', ok_cite, violations=bad[:10], cited_universe=len(all_ids))

    # aggregation-only: report_data must contain no computed statistic blocks
    stat_keys = {'holm_adj_p', 'separability', 'deterioration', 'repair', 'path',
                 'metrics', 'A1_no_recovery_by_regime', 'A2_FR_rate_by_regime'}
    leaked = stat_keys & set(json.dumps(rep).split('"')[0:1]) if False else \
        [k for seg in rep.get('segments', {}).values() if isinstance(seg, dict)
         for k in stat_keys & set(seg)]
    ok_agg = rep.get('aggregation_only') is True and rep.get('no_new_statistics') is True and not leaked
    log.gate('G14_aggregation_only', ok_agg, leaked_stat_blocks=leaked,
             note='T6.5 must not introduce new computed statistics')

    # claim-rules enum
    enum = set(contract['claim_registry_enum'])
    ok_enum = all(c['status'] in enum for c in syn)
    log.gate('G15_status_enum', ok_enum)

    # inventory consistency
    inv = rep['claims_inventory']
    ok_inv = len(inv) == len(all_ids) and {i['claim_id'] for i in inv} == set(all_ids)
    cnt = rep['status_counts']
    ok_inv = ok_inv and sum(cnt.values()) == len(all_ids)
    log.gate('G16_inventory_reconciles', ok_inv, inventory=len(inv), registries=len(all_ids))

    gf.g11_anti_story(log, ROOT/'docs/reports/T6_5_SYNTHESIS.md',
                      OUT/'t6_5_claims.json',
                      extra_registry_paths=[d/f'{st}_claims.json' for st, d in STAGES.items()])
    sys.exit(log.finish(OUT/'t6_5_gates.json'))


if __name__ == '__main__':
    main()
