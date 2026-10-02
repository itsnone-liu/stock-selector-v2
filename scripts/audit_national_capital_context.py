#!/usr/bin/env python3
import argparse,hashlib,json,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/audit/evidence'
def canon(x):return json.dumps({k:v for k,v in x.items() if k!='context_commitment_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':'))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--packet-id',required=True);ap.add_argument('--as-of',required=True);a=ap.parse_args();
 with tempfile.TemporaryDirectory() as d:
  p1=Path(d)/'a.json';p2=Path(d)/'b.json'; cmd=['python3',str(ROOT/'scripts/build_national_capital_context.py'),'--ordinal','4','--packet-id',a.packet_id,'--as-of',a.as_of];subprocess.run(cmd+['--out',str(p1)],check=True,capture_output=True);subprocess.run(cmd+['--out',str(p2)],check=True,capture_output=True); x=p1.read_bytes();y=p2.read_bytes();ctx=json.loads(x); forbidden=any(k in ctx for k in ['stock_code','stock_name','ticker','symbol','case_key','group','identity','outcome','analysis_labeled']);commit=hashlib.sha256(canon(ctx).encode()).hexdigest(); report={'ordinal':4,'packet_id':a.packet_id,'deterministic':x==y,'commitment_exact':commit==ctx['context_commitment_sha256'],'forbidden_keys':forbidden,'no_r4_created':True,'status':'PASS' if x==y and commit==ctx['context_commitment_sha256'] and not forbidden else 'FAIL','context_commitment_sha256':ctx['context_commitment_sha256']};(OUT/'national_capital_context_preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['status']=='PASS' else 1)
if __name__=='__main__':main()
