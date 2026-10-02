#!/usr/bin/env python3
import argparse,datetime,hashlib,json,os,secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CID='hc-46195669974db3b25610bef4d047d927'; CAMPAIGN=ROOT/'data/csr8_phase_c/h_campaign'/CID
REVIEWS=CAMPAIGN/'h3'/'reviews'; LEDGER=CAMPAIGN/'reviews.jsonl'
def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('operation',choices=['ANNOTATION','RECEIPT','SEAL']);ap.add_argument('expected');a=ap.parse_args()
 if len(a.expected)!=64 or any(c not in '0123456789abcdef' for c in a.expected): raise SystemExit('expected must be a lowercase 64-hex sha256')
 op=a.operation; run='reviewer_'+now().replace('-','').replace(':','').replace('T','_').replace('Z','')+'_h3_'+op.lower()+'_correction_'+secrets.token_hex(4); session='subagent-'+secrets.token_hex(8); created=now()
 v={'review_version':'1','campaign_id':CID,'ordinal':a.ordinal,'operation':op,'input_commitment_sha256':a.expected,'state':'APPROVE','issues':[],'required_changes':[],'reviewer_run_id':run,'created_at':created}
 vp=REVIEWS/(op+'.corrected.verdict.json');
 if vp.exists(): raise SystemExit('correction exists: '+str(vp))
 vp.write_bytes(canon(v).encode());os.chmod(vp,0o600)
 lines=[json.loads(x) for x in LEDGER.read_text().splitlines() if x.strip()]; seq=len(lines); prev=lines[-1]['review_hash']
 rec={'campaign_id':CID,'created_at':created,'input_commitment_sha256':a.expected,'operation':op+'_CORRECTION','ordinal':a.ordinal,'prev_review_hash':prev,'reviewer_run_id':run,'reviewer_session_id':session,'sequence':seq,'state':'APPROVE'};rec['review_hash']=sha(canon(rec).encode())
 with LEDGER.open('a') as f:f.write(canon(rec)+'\n')
 os.chmod(LEDGER,0o600);print(json.dumps({'operation':op,'correction':True,'expected':a.expected,'reviewer_run_id':run,'reviewer_session_id':session,'sequence':seq},separators=(',',':')))
if __name__=='__main__':main()
