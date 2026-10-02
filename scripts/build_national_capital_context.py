#!/usr/bin/env python3
"""Build blinded NATIONAL_CTX_V1 for a supplied ordinal-4 candidate fixture."""
import argparse,csv,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'
FORBIDDEN={'stock_code','stock_name','ticker','symbol','case_key','group','identity','outcome','analysis_labeled'}
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--ordinal',type=int,required=True);ap.add_argument('--packet-id',required=True);ap.add_argument('--as-of',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();assert a.ordinal==4
 h=list(csv.DictReader((OUT/'national_holdings_pit.csv').open()));e=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open())); stock=[]
 for i,r in enumerate(h):
  if r.get('actor_id') and r.get('available_date') not in ('','UNKNOWN') and r.get('available_date')<=a.as_of:
   stock.append({'context_record_id':f'S-{i:06d}','capital_layer':'STOCK','evidence_type':'NATIONAL_ACTOR_HOLDING','actor_id':r['actor_id'],'report_period':r['report_period'],'publication_date':r['publication_date'],'available_date':r['available_date'],'holding_ratio':r['holding_ratio'],'shares':r['shares'],'state':'FIRST_DISCLOSED','evidence_grade':r['source_grade']})
 market=[]
 for i,r in enumerate(e):
  if r.get('availability_status')=='AVAILABLE_PIT' and r.get('available_date')<=a.as_of: market.append({'context_record_id':f'E-{i:06d}','capital_layer':'MARKET','evidence_type':'ETF_TOTAL_SHARES','etf_code_hash':hashlib.sha256(r['etf_code'].encode()).hexdigest(),'trade_date':r['trade_date'],'available_date':r['available_date'],'total_shares':r['total_shares'],'actor_attribution':'FORBIDDEN','evidence_grade':'OFFICIAL_SSE'})
 ctx={'context_version':'csr8-national-capital-v1','evidence_profile':'BASE_V1+NATIONAL_CTX_V1','ordinal':4,'packet_id':a.packet_id,'as_of':{'T':a.as_of,'availability_rule':'available_date<=T'},'stock_capital_records':stock,'market_etf_records':market,'limitations':[{'status':'UNAVAILABLE','scope':'SZSE_ETF_HISTORY'}],'source_commitments':{'holdings_sha256':hashlib.sha256((OUT/'national_holdings_pit.csv').read_bytes()).hexdigest(),'etf_sha256':hashlib.sha256((OUT/'etf_share_daily_sse.csv').read_bytes()).hexdigest()},'context_commitment_sha256':''}; ctx['context_commitment_sha256']=hashlib.sha256(canon({k:v for k,v in ctx.items() if k!='context_commitment_sha256'}).encode()).hexdigest(); Path(a.out).write_text(json.dumps(ctx,ensure_ascii=False,indent=2)+'\n'); print(json.dumps({'out':a.out,'records':len(stock)+len(market),'context_commitment_sha256':ctx['context_commitment_sha256']},ensure_ascii=False))
if __name__=='__main__':main()
