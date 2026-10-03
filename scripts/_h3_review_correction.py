#!/usr/bin/env python3
import argparse,datetime,hashlib,json,os,secrets,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import csr8_ledger_epoch2 as epoch2
CID='hc-46195669974db3b25610bef4d047d927'; CAMPAIGN=ROOT/'data/csr8_phase_c/h_campaign'/CID
REVIEWS=None; EPOCH2_LEDGER=CAMPAIGN/'reviews_epoch2.jsonl'; LEDGER=CAMPAIGN/'reviews.jsonl'
def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def active_ledger(ordinal):
    if ordinal >= 50 and EPOCH2_LEDGER.is_file(): return EPOCH2_LEDGER,2
    return LEDGER,1
def append_review(ordinal, rec):
    path,epoch=active_ledger(ordinal)
    if epoch==2:
        rec['epoch_id']=2
        rec['sequence']=len(epoch2.read_rows(path))
        row=epoch2.append_row(path,rec,expected_head=None,expected_epoch=2)
        return row['sequence']
    rec.pop('epoch_id',None)
    lines=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    seq=len(lines); prev=lines[-1]['review_hash'] if lines else '0'*40
    rec['prev_review_hash']=prev; rec['sequence']=seq
    rec['review_hash']=sha(canon(rec).encode())
    with path.open('a') as f: f.write(canon(rec)+'\n')
    os.chmod(path,0o600)
    return seq
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--ordinal',type=int,required=True);ap.add_argument('operation',choices=['ANNOTATION','RECEIPT','SEAL']);ap.add_argument('expected');a=ap.parse_args()
 if a.ordinal < 5: raise SystemExit('--ordinal must be >= 5')
 global REVIEWS
 REVIEWS=CAMPAIGN/f'h{a.ordinal-2}'/'reviews'
 if len(a.expected)!=64 or any(c not in '0123456789abcdef' for c in a.expected): raise SystemExit('expected must be a lowercase 64-hex sha256')
 op=a.operation; run='reviewer_'+now().replace('-','').replace(':','').replace('T','_').replace('Z','')+'_h'+str(a.ordinal-2)+'_'+op.lower()+'_correction_'+secrets.token_hex(4); session='subagent-'+secrets.token_hex(8); created=now()
 v={'review_version':'1','campaign_id':CID,'ordinal':a.ordinal,'operation':op,'input_commitment_sha256':a.expected,'state':'APPROVE','issues':[],'required_changes':[],'reviewer_run_id':run,'created_at':created}
 vp=REVIEWS/(op+'.corrected.verdict.json');
 if vp.exists(): raise SystemExit('correction exists: '+str(vp))
 vp.write_bytes(canon(v).encode());os.chmod(vp,0o600)
 rec={'campaign_id':CID,'created_at':created,'input_commitment_sha256':a.expected,'operation':op+'_CORRECTION','ordinal':a.ordinal,'reviewer_run_id':run,'reviewer_session_id':session,'state':'APPROVE'}
 seq=append_review(a.ordinal,rec)
 print(json.dumps({'operation':op,'correction':True,'expected':a.expected,'reviewer_run_id':run,'reviewer_session_id':session,'sequence':seq},separators=(',',':')))
if __name__=='__main__':main()
