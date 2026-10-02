#!/usr/bin/env python3
"""Build the authoritative 84x22 request-cell ledger from raw metadata."""
import csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'; RAW=ROOT/'data/csr8_national_capital/raw/holdings'; OUT=ROOT/'output/research/csr/national_capital/holdings_coverage_ledger.csv'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 d=json.loads(SAMPLE.read_text()); codes=sorted({x['code'] for g in d['groups'].values() for x in g['chosen']}); periods=[f'{y}-{m:02d}-{day}' for y in range(2021,2027) for m,day in ((3,31),(6,30),(9,30),(12,31)) if y<2026 or m<=6]; by={}
 for p in RAW.glob('*.meta.json'):
  x=json.loads(p.read_text()); q=x.get('request',{}); code=q.get('code',''); code=(code[:2]+'.'+code[2:]).lower(); by[(code,q.get('date'))]=(p,x)
 rows=[]
 for code in codes:
  req=('sh.' if code.startswith('sh.') else 'sz.')+code.split('.')[1]
  for period in periods:
   p,x=by.get((req,period),(None,None)); outcome=x.get('outcome') if x else 'MISSING'; status='UNKNOWN' if outcome=='SUCCESS_EMPTY' else ('AVAILABLE' if outcome=='SUCCESS_NONEMPTY' else outcome)
   rows.append({'stock_code':code,'report_period':period,'request_meta':str(p.relative_to(ROOT)) if p else '','source_status':outcome,'absence_semantics':status,'sha_verified':bool(p and x.get('sha256')),'cell_status':'COMPLETE' if outcome in ('SUCCESS_NONEMPTY','SUCCESS_EMPTY') else 'INCOMPLETE'})
 OUT.parent.mkdir(parents=True,exist_ok=True)
 with OUT.open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=rows[0]); w.writeheader();w.writerows(rows)
 report={'expected_cells':len(codes)*len(periods),'ledger_cells':len(rows),'missing':sum(x['source_status']=='MISSING' for x in rows),'failed':sum(x['source_status']=='FAILED' for x in rows),'empty_unknown':sum(x['source_status']=='SUCCESS_EMPTY' for x in rows),'nonempty':sum(x['source_status']=='SUCCESS_NONEMPTY' for x in rows),'status':'PASS' if all(x['cell_status']=='COMPLETE' and x['sha_verified'] for x in rows) else 'FAIL','sample_sha256':sha(SAMPLE)}
 (OUT.parent/'holdings_coverage_ledger_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
