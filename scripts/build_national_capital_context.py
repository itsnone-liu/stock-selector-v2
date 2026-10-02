#!/usr/bin/env python3
"""Build candidate-specific blinded NATIONAL_CTX_V1 with fail-closed empty-cell PIT."""
import argparse,csv,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/research/csr/national_capital'
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def num(x):
 try:return float(x) if x not in ('',None) else None
 except:return None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--ordinal',type=int,required=True);ap.add_argument('--packet-id');ap.add_argument('--as-of');ap.add_argument('--out',required=True);a=ap.parse_args();sys.path.insert(0,str(ROOT/'scripts'));import csr8_phase_c_annotation_seal as c4d
 cand=c4d.candidate_for_ordinal(a.ordinal);T=cand['T'];ocid=cand['opaque_case_id'];packet=c4d.c1.packet_id(ocid,T)
 if a.packet_id and a.packet_id!=packet:raise SystemExit('packet-id does not match candidate_for_ordinal')
 if a.as_of and a.as_of!=T:raise SystemExit('as-of does not match candidate_for_ordinal')
 salt=c4d.c1.load_salt();plan=json.loads(c4d.c1.PLAN_FILE.read_text());matches=[e for e in plan['entries'] if c4d.c1.opaque_case_id(salt,e['case_key'])==ocid and e['T']==T]
 if len(matches)!=1:raise SystemExit('candidate identity resolution is not unique')
 stock_code=matches[0]['case_key'].split('|')[1];h=list(csv.DictReader((OUT/'national_holdings_pit.csv').open()));all_rows=[r for r in h if r['stock_code']==stock_code];ledger=list(csv.DictReader((OUT/'holdings_coverage_ledger.csv').open()));pub={(r['stock_code'],r['report_period']):r for r in csv.DictReader((OUT/'publication_dates.csv').open())};cal=sorted(x.strip() for x in (ROOT/'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv').read_text().splitlines()[3:] if x.strip())
 def avail(period):
  rs=[r for r in all_rows if r['report_period']==period and r.get('available_date') not in ('','UNKNOWN')];
  if rs:return min(r['available_date'] for r in rs)
  p=pub.get((stock_code,period),{}).get('publication_date','');p=f'{p[:4]}-{p[4:6]}-{p[6:]}' if len(p)==8 else p
  return next((d for d in cal if d>p),'')
 cells=[r for r in ledger if r['stock_code']==stock_code and avail(r['report_period']) and avail(r['report_period'])<=T]; cells.sort(key=lambda r:(avail(r['report_period']),r['report_period'])); latest_cell=cells[-1] if cells else None;prev_cell=cells[-2] if len(cells)>1 else None;latest_period=latest_cell['report_period'] if latest_cell else None;previous_period=prev_cell['report_period'] if prev_cell else None;latest=[r for r in all_rows if r['report_period']==latest_period] if latest_period and latest_cell['source_status']=='SUCCESS_NONEMPTY' else [];previous=[r for r in all_rows if r['report_period']==previous_period and prev_cell['source_status']=='SUCCESS_NONEMPTY'] if previous_period else [];latest_by={r.get('actor_id'):r for r in latest if r.get('actor_id')};previous_by={r.get('actor_id'):r for r in previous if r.get('actor_id')};actors=sorted(set(latest_by)|set(previous_by));stock=[];latest_unavailable=bool(latest_cell and latest_cell['source_status']!='SUCCESS_NONEMPTY')
 if latest_unavailable:
  up=latest_period;ua=avail(up);stock=[{'context_record_id':'S-000000','capital_layer':'STOCK','evidence_type':'NATIONAL_ACTOR_HOLDING_STATE','actor_id':'','state':'UNKNOWN','current_report_period':up,'current_publication_date':'','current_available_date':ua,'current_holding_ratio':'','previous_report_period':previous_period or '','previous_holding_ratio':'','evidence_grade':'SOURCE_UNAVAILABLE','source_status':'UNAVAILABLE'}]
 elif not actors:
  stock=[]
 else:
  for i,actor in enumerate(actors):
   cur=latest_by.get(actor);prev=previous_by.get(actor);state='UNKNOWN' if not latest_cell or latest_cell['source_status']!='SUCCESS_NONEMPTY' else ('FIRST_DISCLOSED' if cur and not prev else 'NOT_DISCLOSED_IN_TOP10' if not cur and prev else 'UNKNOWN' if not cur else 'INCREASE' if num(cur.get('holding_ratio'))>num(prev.get('holding_ratio')) else 'DECREASE' if num(cur.get('holding_ratio'))<num(prev.get('holding_ratio')) else 'STABLE');base=cur or prev;stock.append({'context_record_id':f'S-{i:06d}','capital_layer':'STOCK','evidence_type':'NATIONAL_ACTOR_HOLDING_STATE','actor_id':actor,'state':state,'current_report_period':latest_period or '','current_publication_date':cur.get('publication_date','') if cur else '','current_available_date':cur.get('available_date','') if cur else '','current_holding_ratio':cur.get('holding_ratio','') if cur and state not in ('UNKNOWN','NOT_DISCLOSED_IN_TOP10') else '','previous_report_period':prev['report_period'] if prev else '','previous_holding_ratio':prev.get('holding_ratio','') if prev else '','evidence_grade':base.get('source_grade','SOURCE_UNAVAILABLE') if base else 'SOURCE_UNAVAILABLE'})
 e=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open()));market=[]
 for code in sorted({r['etf_code'] for r in e}):
  rs=sorted([r for r in e if r['etf_code']==code and r.get('availability_status')=='AVAILABLE_PIT' and r.get('available_date')<=T],key=lambda x:x['trade_date'])
  if not rs:continue
  q=rs[-1];p=rs[-2] if len(rs)>1 else None;v=num(q.get('total_shares'));pv=num(p.get('total_shares')) if p else None;state='STABLE' if p is None or v==pv else 'EXPANSION' if v>pv else 'CONTRACTION';market.append({'context_record_id':f'E-{len(market):06d}','capital_layer':'MARKET','evidence_type':'ETF_TOTAL_SHARES','etf_code_hash':hashlib.sha256(code.encode()).hexdigest(),'latest_trade_date':q['trade_date'],'latest_available_date':q['available_date'],'latest_total_shares':q['total_shares'],'previous_trade_date':p['trade_date'] if p else '','previous_total_shares':p['total_shares'] if p else '','share_change':str(v-pv) if p and v is not None and pv is not None else '','share_change_ratio':str((v-pv)/pv) if p and v is not None and pv else '','state':state,'actor_attribution':'FORBIDDEN'})
 ctx={'context_version':'csr8-national-capital-v1','evidence_profile':'BASE_V1+NATIONAL_CTX_V1','ordinal':a.ordinal,'packet_id':packet,'as_of':{'T':T,'availability_rule':'available_date<=T'},'stock_capital_records':stock,'market_etf_records':market,'limitations':[{'status':'UNAVAILABLE','scope':'SZSE_ETF_HISTORY'}],'source_commitments':{'holdings_sha256':hashlib.sha256((OUT/'national_holdings_pit.csv').read_bytes()).hexdigest(),'etf_sha256':hashlib.sha256((OUT/'etf_share_daily_sse.csv').read_bytes()).hexdigest()},'context_commitment_sha256':''};ctx['context_commitment_sha256']=hashlib.sha256(canon({k:v for k,v in ctx.items() if k!='context_commitment_sha256'}).encode()).hexdigest();Path(a.out).write_text(json.dumps(ctx,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'out':a.out,'packet_id':packet,'records':len(stock)+len(market),'context_commitment_sha256':ctx['context_commitment_sha256']},ensure_ascii=False))
if __name__=='__main__':main()
