#!/usr/bin/env python3
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/audit/evidence';DATA=ROOT/'output/research/csr/national_capital'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def main():
 audit=OUT/'national_capital_context_extension_final_audit.json';pre=OUT/'national_capital_context_preflight.json';inv=OUT/'national_capital_production_invariance.json';anchor=OUT/'national_capital_extension_pause_anchor.json';packet={'review_version':'csr8-nc-final-review-v1','operation':'NC_FINAL','audit_target_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'base_infra_freeze':'NC-FIX3_REVIEW_TARGET','nc0_pause_head':json.loads(anchor.read_text())['production_head'],'final_audit_sha256':sha(audit),'context_preflight_sha256':sha(pre),'support_contract_report_sha256':'PENDING_SUPPORT_CONTRACT_TEST','artifact_commitments':{x:sha(ROOT/x) for x in ['config/csr/national_actor_registry_v1.json','output/research/csr/national_capital/holdings_coverage_ledger.csv','output/research/csr/national_capital/national_holdings_pit.csv','output/research/csr/national_capital/etf_share_daily_sse.csv']},'production_invariance':json.loads(inv.read_text()),'no_r4_s4':json.loads(inv.read_text())['checks']['no_r4_s4']};packet['review_packet_sha256']=hashlib.sha256(canon(packet).encode()).hexdigest();(OUT.parent.parent.parent/'docs/audit/evidence/nc_final_review_packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n');print(json.dumps(packet,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
