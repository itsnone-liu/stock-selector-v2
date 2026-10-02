#!/usr/bin/env python3
"""Build candidate-specific blinded NATIONAL_CTX_V1 (selector-side resolution)."""
import argparse,csv,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/research/csr/national_capital';FORBIDDEN={'stock_code','stock_name','ticker','symbol','case_key','group','identity','outcome','analysis_labeled'}
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def num(x):
 try:return float(x) if x not in ('',None) else None
 except:return None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--ordinal',type=int,required=True);ap.add_argument('--packet-id');ap.add_argument('--as-of');ap.add_argument('--out',required=True);a=ap.parse_args();sys.path.insert(0,str(ROOT/'scripts'));import csr8_phase_c_annotation_seal as c4d
 cand=c4d.candidate_for_ordinal(a.ordinal);T=cand['T']; packet=cand['opaque_case_id'];
 if a.packet_id and a.packet_id!=packet:raise SystemExit('packet-id does not match candidate_for_ordinal')
 if a.as_of and a.as_of!=T:raise SystemExit('as-of does not match candidate_for_ordinal')
 salt=c4d.c1.load_salt(); plan=json.loads(c4d.c1.PLAN_FILE.read_text());matches=[e for e in plan['entries'] if c4d.c1.opaque_case_id(salt,e['case_key'])==packet and e['T']==T]
 if len(matches)!=1:raise SystemExit('candidate identity resolution is not unique')
 stock_code=matches[0]['case_key'].split('|')[1]
 h=list(csv.DictReader((OUT/'national_holdings_pit.csv').open())); rows=[r for r in h if r['stock_code']==stock_code and r.get('available_date') not in ('','UNKNOWN') and r['available_date']<=T]; by={}
 for r in rows:
  if r.get('actor_id'):by.setdefault(r['actor_id'],[]).append(r)
 stock=[]
 for i,(actor,rs) in enumerate(sorted(by.items())):
  rs.sort(key=lambda x:(x['available_date'],x['report_period']));latest=rs[-1];prev=rs[-2] if len(rs)>1 else None; a1=num(latest.get('holding_ratio'));a0=num(prev.get('holding_ratio')) if prev else None;state='FIRST_DISCLOSED' if prev is None else ('UNKNOWN' if a1 is None or a0 is None else 'INCREASE' if a1>a0 else 'DECREASE' if a1<a0 else 'STABLE')
  stock.append({'context_record_id':f'S-{i:06d}','capital_layer':'STOCK','evidence_type':'NATIONAL_ACTOR_HOLDING_STATE','actor_id':actor,'csr_actor_class':next((x.get('csr_actor_class') for x in json.loads((ROOT/'config/csr/national_actor_registry_v1.json').read_text())['actors'] if x['actor_id']==actor),''),'state':state,'current_report_period':latest['report_period'],'current_publication_date':latest['publication_date'],'current_available_date':latest['available_date'],'current_holding_ratio':latest['holding_ratio'],'previous_report_period':prev['report_period'] if prev else '','previous_holding_ratio':prev['holding_ratio'] if prev else '','evidence_grade':latest['source_grade']})
 e=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open()));market=[]
 for code in sorted({r['etf_code'] for r in e}):
  rs=sorted([r for r in e if r['etf_code']==code and r.get('availability_status')=='AVAILABLE_PIT' and r.get('available_date')<=T],key=lambda x:x['trade_date'])
  if not rs:continue
  latest=rs[-1];prev=rs[-2] if len(rs)>1 else None;v=num(latest.get('total_shares'));p=num(prev.get('total_shares')) if prev else None;state='STABLE' if prev is None or v==p else 'EXPANSION' if v>p else 'CONTRACTION';market.append({'context_record_id':f'E-{len(market):06d}','capital_layer':'MARKET','evidence_type':'ETF_TOTAL_SHARES','etf_code_hash':hashlib.sha256(code.encode()).hexdigest(),'latest_trade_date':latest['trade_date'],'latest_available_date':latest['available_date'],'latest_total_shares':latest['total_shares'],'previous_trade_date':prev['trade_date'] if prev else '','previous_total_shares':prev['total_shares'] if prev else '','share_change':str(v-p) if prev and v is not None and p is not None else '','share_change_ratio':str((v-p)/p) if prev and v is not None and p else '','state':state,'actor_attribution':'FORBIDDEN'})
 ctx={'context_version':'csr8-national-capital-v1','evidence_profile':'BASE_V1+NATIONAL_CTX_V1','ordinal':a.ordinal,'packet_id':packet,'as_of':{'T':T,'availability_rule':'available_date<=T'},'stock_capital_records':stock,'market_etf_records':market,'limitations':[{'status':'UNAVAILABLE','scope':'SZSE_ETF_HISTORY'}],'source_commitments':{'holdings_sha256':hashlib.sha256((OUT/'national_holdings_pit.csv').read_bytes()).hexdigest(),'etf_sha256':hashlib.sha256((OUT/'etf_share_daily_sse.csv').read_bytes()).hexdigest()},'context_commitment_sha256':''};ctx['context_commitment_sha256']=hashlib.sha256(canon({k:v for k,v in ctx.items() if k!='context_commitment_sha256'}).encode()).hexdigest();Path(a.out).write_text(json.dumps(ctx,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'out':a.out,'packet_id':packet,'stock_code_selector_only':stock_code,'records':len(stock)+len(market),'context_commitment_sha256':ctx['context_commitment_sha256']},ensure_ascii=False))
if __name__=='__main__':main()
