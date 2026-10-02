#!/usr/bin/env python3
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser();ap.add_argument('path');a=ap.parse_args();m=json.loads(Path(a.path).read_text());assert m.get('version')=='csr8-national-context-support-v1' and m.get('ordinal')==4 and set(m.get('judgments',{}))=={'rt_H01','rt_H02','rt_H03','rt_H04','rt_H05','rt_H06'}; side=Path(m.get('sidecar_path','')); ids=set()
 if side.exists():
  x=json.loads(side.read_text());ids={r['context_record_id'] for r in x.get('stock_capital_records',[])+x.get('market_etf_records',[])}
 bad=[r for j in m['judgments'].values() for r in j if r.get('context_record_id') not in ids]; print(json.dumps({'status':'PASS' if not bad else 'FAIL','bad_references':bad},ensure_ascii=False));raise SystemExit(0 if not bad else 1)
if __name__=='__main__':main()
