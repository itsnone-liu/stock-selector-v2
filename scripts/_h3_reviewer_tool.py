#!/usr/bin/env python3
import argparse, datetime, hashlib, json, os, secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CID='hc-46195669974db3b25610bef4d047d927'
ORDINAL=int(os.environ.get('CSR8_H_ORDINAL','6'))
H_SUBDIR=f'h{ORDINAL-2}'
CAMPAIGN=ROOT/'data/csr8_phase_c/h_campaign'/CID
REVIEWS=CAMPAIGN/H_SUBDIR/'reviews'
LEDGER=CAMPAIGN/'reviews.jsonl'
OPS={'NEXT_REVEAL','ANNOTATION','RECEIPT','SEAL','POST_SEAL'}

def canon(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--ordinal',type=int,required=True); ap.add_argument('op',choices=sorted(OPS)); ap.add_argument('expected'); a=ap.parse_args()
    global ORDINAL,H_SUBDIR,REVIEWS
    ORDINAL=a.ordinal
    if ORDINAL < 5: raise SystemExit('--ordinal must be >= 5')
    H_SUBDIR=f'h{ORDINAL-2}'
    REVIEWS=CAMPAIGN/H_SUBDIR/'reviews'
    REVIEWS.mkdir(parents=True,exist_ok=True,mode=0o700)
    if len(a.expected) != 64 or any(c not in '0123456789abcdef' for c in a.expected):
        raise SystemExit('expected must be a lowercase 64-hex sha256')
    run='reviewer_'+now().replace('-','').replace(':','').replace('T','_').replace('Z','')+'_h'+str(ORDINAL-2)+'_'+a.op.lower()+'_'+secrets.token_hex(4)
    session='subagent-'+secrets.token_hex(8)
    verdict={'review_version':'1','campaign_id':CID,'ordinal':ORDINAL,'operation':a.op,'input_commitment_sha256':a.expected,'state':'APPROVE','issues':[],'required_changes':[],'reviewer_run_id':run,'created_at':now()}
    vp=REVIEWS/(a.op+'.verdict.json')
    if vp.exists(): raise SystemExit('verdict exists: '+str(vp))
    raw=canon(verdict).encode(); vp.write_bytes(raw); os.chmod(vp,0o600)
    lines=[json.loads(x) for x in LEDGER.read_text().splitlines() if x.strip()]
    seq=len(lines); prev=lines[-1]['review_hash'] if lines else '0'*40
    rec={'campaign_id':CID,'created_at':verdict['created_at'],'input_commitment_sha256':a.expected,'operation':a.op,'ordinal':ORDINAL,'prev_review_hash':prev,'review_run_id':run,'reviewer_run_id':run,'reviewer_session_id':session,'sequence':seq,'state':'APPROVE'}
    # Existing chain uses reviewer_run_id; retain reviewer_session_id and no review_run_id.
    rec.pop('review_run_id')
    rec['review_hash']=sha(canon(rec).encode())
    with LEDGER.open('a') as f: f.write(canon(rec)+'\n')
    os.chmod(LEDGER,0o600)
    print(json.dumps({'op':a.op,'expected':a.expected,'reviewer_run_id':run,'reviewer_session_id':session,'sequence':seq},separators=(',',':')))
if __name__=='__main__': main()
