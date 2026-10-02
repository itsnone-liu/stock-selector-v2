#!/usr/bin/env python3
"""Closed-world support-map contract and negative-fixture audit."""
import json,tempfile,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/audit/evidence';
def main():
 side=Path('/tmp/nc4-context.json'); packet=ROOT/'docs/audit/evidence/nc_final_review_packet.json'; refs=json.loads(side.read_text()); valid={'version':'csr8-national-context-support-v1','ordinal':4,'packet_sha256':hashlib.sha256(packet.read_bytes()).hexdigest(),'context_sha256':refs['context_commitment_sha256'],'judgments':{f'rt_H0{i}':[] for i in range(1,7)}};p=Path('/tmp/support-map.json');p.write_text(json.dumps(valid));r=subprocess.run(['python3',str(ROOT/'scripts/validate_context_support_map.py'),str(p),'--sidecar',str(side),'--packet',str(packet)],capture_output=True,text=True);checks={'valid_map':r.returncode==0};
 for name,mut in [('wrong_context',lambda x:x.update(context_sha256='0'*64)),('extra_key',lambda x:x.update(extra=True)),('missing_hypothesis',lambda x:x['judgments'].pop('rt_H06')),('duplicate_ref',lambda x:x['judgments']['rt_H01'].append('S-000000'))]:
  x=json.loads(json.dumps(valid));mut(x);q=Path('/tmp/'+name+'.json');q.write_text(json.dumps(x));checks[name]=subprocess.run(['python3',str(ROOT/'scripts/validate_context_support_map.py'),str(q),'--sidecar',str(side),'--packet',str(packet)]).returncode!=0
 report={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks};(OUT/'support_contract_test_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['status']=='PASS' else 1)
if __name__=='__main__':main()
