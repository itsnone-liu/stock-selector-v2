import json
from pathlib import Path
from scripts.cd_shadow_daily import run_shadow_day

def stages():
    return {name: (lambda n=name: {'decisions':[{'decision_id':'d1','episode_id':'e1','decision':'ENTER'}], 'terminals':[], 'positions':[{'episode_id':'e1'}], 'opened_positions':1, 'closed_positions':0, 'current_open_positions':1}) for name in ('ingest','pit','l1','l2','l3','l4','primary_zone','decision')}

def test_valid_snapshot_and_idempotence(tmp_path):
    r=run_shadow_day('2026-10-05',tmp_path,stages=stages())
    assert r['status']=='SHADOW_VALID'
    assert (tmp_path/'2026-10-05'/'artifact_manifest.json').exists()
    r2=run_shadow_day('2026-10-05',tmp_path,stages=stages())
    assert r2['status']=='SHADOW_VALID'

def test_missing_stage_is_invalid(tmp_path):
    r=run_shadow_day('2026-10-05',tmp_path,stages={})
    assert r['status']=='SHADOW_INVALID'
    assert json.loads((tmp_path/'2026-10-05'/'accounting_report.json').read_text())['status']=='SHADOW_INVALID'
