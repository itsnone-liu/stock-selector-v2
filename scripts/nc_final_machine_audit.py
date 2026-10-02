#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NC final prerequisite audit; never declares independent approval or
appends H events.

H2-CANARY-FIX1 item 6: the H-PRE frozen audit record
(docs/audit/evidence/national_capital_context_extension_final_audit.json)
is IMMUTABLE at HEAD — its bytes are bound by the freeze marker's
final_audit_sha256 and must never be rewritten by re-running audits
(the H2 canary review found the R4-append had silently flipped its
no_r4_s4 flag, breaking HEAD-level exact binding).

This script now:
* verifies the frozen audit file still hashes to the freeze marker's
  final_audit_sha256 (fail-closed on drift), and
* writes live post-resume status to a SEPARATE file:
  docs/audit/evidence/national_capital_context_post_resume_status.json
"""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/audit/evidence'
DATA = ROOT / 'output/research/csr/national_capital'
FROZEN_AUDIT = OUT / 'national_capital_context_extension_final_audit.json'
FREEZE_MARKER = OUT / 'national_capital_context_extension_frozen.json'
POST_RESUME = OUT / 'national_capital_context_post_resume_status.json'


def h(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    marker = json.loads(FREEZE_MARKER.read_text())
    frozen_sha = h(FROZEN_AUDIT)
    if frozen_sha != marker['final_audit_sha256']:
        raise SystemExit(
            'FROZEN AUDIT BYTES DRIFTED: '
            f'{FROZEN_AUDIT} hashes to {frozen_sha}, freeze marker binds '
            f"{marker['final_audit_sha256']} — refusing to proceed")
    checks = {
        'frozen_audit_bytes_bound': True,
        'actor_registry_deterministic':
            json.loads((DATA / 'actor_registry_audit.json').read_text())
            ['status'] == 'PASS',
        'raw_provenance_exact':
            json.loads((DATA / 'holdings_coverage_ledger_report.json')
                       .read_text())['status'] == 'PASS',
        'publication_provenance_pass':
            json.loads((DATA / 'publication_provenance_audit.json')
                       .read_text())['status'] == 'PASS',
        'strict_available_date':
            all(x['available_date'] > x['publication_date']
                for x in __import__('csv').DictReader(
                    (DATA / 'national_holdings_pit.csv').open())),
        'empty_unavailable':
            json.loads((DATA / 'empty_resolution_report.json')
                       .read_text())['not_disclosed_cells'] == 0,
        'etf_attribution_forbidden':
            all(r.get('actor_attribution') == 'FORBIDDEN'
                for r in json.loads(
                    Path('/tmp/nc4-context.json').read_text())
                .get('market_etf_records', [])),
        'nc0_invariance':
            json.loads((OUT / 'national_capital_production_invariance.json')
                       .read_text())['passed'],
        'context_preflight':
            json.loads((OUT / 'national_capital_context_preflight.json')
                       .read_text()).get('status') == 'PASS',
        'support_contract':
            json.loads((OUT / 'support_contract_test_report.json')
                       .read_text()).get('status') == 'PASS',
        'support_contract_v2':
            json.loads((OUT / 'support_contract_test_report_v2.json')
                       .read_text()).get('status') == 'PASS',
    }
    files = [
        'config/csr/national_actor_registry_v1.json',
        'output/research/csr/national_capital/holdings_coverage_ledger.csv',
        'output/research/csr/national_capital/national_holdings_pit.csv',
        'output/research/csr/national_capital/'
        'publication_provenance_audit.json',
        'output/research/csr/national_capital/'
        'empty_resolution_report.json',
        'output/research/csr/national_capital/etf_share_daily_sse.csv',
        'output/research/csr/national_capital/etf_lineage_report.json',
        'docs/audit/evidence/national_capital_extension_pause_anchor.json',
        'docs/audit/evidence/national_capital_production_invariance.json']
    chain_events = [
        x for x in
        (ROOT / 'data/csr8_phase_c/production/c4-prod-0002/sealing/'
         'sealing_log.jsonl').read_text().splitlines() if x.strip()]
    report = {
        'record_kind': 'POST_RESUME_STATUS',
        'note': 'live status after the NC freeze; the frozen H-PRE audit '
                'record stays byte-identical to the freeze marker '
                'binding and is verified, never rewritten',
        'checks': checks,
        'passed': all(checks.values()),
        'state': ('PREREQUISITES_COMPLETE' if all(checks.values())
                  else 'INCOMPLETE'),
        'independent_approval': 'NOT_DECLARED',
        'artifact_sha256': {x: h(ROOT / x) for x in files
                            if (ROOT / x).exists()},
        'production_chain_events': len(chain_events),
        'no_r4_s4': len(chain_events) == 6,
    }
    POST_RESUME.write_text(json.dumps(report, ensure_ascii=False,
                                      indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
