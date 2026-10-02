#!/usr/bin/env python3
import argparse,hashlib,json,re
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('map');ap.add_argument('--sidecar',required=True);ap.add_argument('--packet',required=True);a=ap.parse_args();m=json.loads(Path(a.map).read_text());s=json.loads(Path(a.sidecar).read_text());assert set(m)=={'version','ordinal','packet_sha256','context_sha256','judgments'} and m['version']=='csr8-national-context-support-v1' and m['ordinal']==s['ordinal']==4 and set(m['judgments'])=={'rt_H01','rt_H02','rt_H03','rt_H04','rt_H05','rt_H06'} and re.fullmatch(r'[0-9a-f]{64}',m['packet_sha256']) and re.fullmatch(r'[0-9a-f]{64}',m['context_sha256']);assert m['packet_sha256']==sha(a.packet) and m['context_sha256']==s['context_commitment_sha256']; ids={r['context_record_id'] for r in s['stock_capital_records']+s['market_etf_records']};refs=[x for j in m['judgments'].values() for x in j];assert all(isinstance(x,str) and x in ids for x in refs) and len(refs)==len(set(refs));print(json.dumps({'status':'PASS','references':len(refs)},ensure_ascii=False))
if __name__=='__main__':main()
