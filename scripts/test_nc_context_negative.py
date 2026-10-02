#!/usr/bin/env python3
"""Negative proof: a latest UNAVAILABLE holdings cell must not fall back to stale actor state.

Drives the REAL builder main() against synthetic sources (patched module import +
temp OUT tree) and asserts the sidecar exposes exactly one UNKNOWN/SOURCE_UNAVAILABLE
stock-capital record for the latest unavailable cell.
"""
import builtins,importlib.util,json,sys,tempfile,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load_builder():
 spec=importlib.util.spec_from_file_location('bnc_real',ROOT/'scripts/build_national_capital_context.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def main():
 m=load_builder();d=Path(tempfile.mkdtemp())
 (d/'holdings_coverage_ledger.csv').write_text("stock_code,report_period,source_status\nsh.TEST,2021-06-30,SUCCESS_NONEMPTY\nsh.TEST,2021-09-30,SUCCESS_EMPTY\n")
 (d/'national_holdings_pit.csv').write_text("stock_code,report_period,actor_id,holding_ratio,available_date,publication_date,table_complete,source_grade\nsh.TEST,2021-06-30,A1-HUIJIN,1.0,2021-08-31,2021-08-30,True,g\n")
 (d/'publication_dates.csv').write_text("stock_code,report_period,publication_date\nsh.TEST,2021-06-30,2021-08-30\nsh.TEST,2021-09-30,2021-10-30\n")
 (d/'etf_share_daily_sse.csv').write_text("etf_code,trade_date,total_shares,available_date,availability_status\n")
 class FakeC1:
  PLAN_FILE=d/'plan.json'
  def load_salt(self):return 'salt'
  def opaque_case_id(self,salt,key):return 'OCID-'+key
  def packet_id(self,ocid,T):return f'PID-{ocid}-{T}'
 FakeC1.PLAN_FILE.write_text(json.dumps({'entries':[{'case_key':'G|sh.TEST|2021-11-01|2026-06-24','T':'2021-11-01'}]}))
 fake_c4d=types.ModuleType('csr8_phase_c_annotation_seal')
 fake_c4d.c1=FakeC1();fake_c4d.candidate_for_ordinal=lambda n:{'opaque_case_id':'OCID-G|sh.TEST|2021-11-01|2026-06-24','T':'2021-11-01','t_rank':0,'case_rank':3}
 real_import=builtins.__import__
 def guarded(name,*a,**k):return fake_c4d if name=='csr8_phase_c_annotation_seal' else real_import(name,*a,**k)
 real_argv=sys.argv;sys.argv=['bnc','--ordinal','4','--out',str(d/'ctx.json')]
 builtins.__import__=guarded
 try:
  m.OUT=d;m.main()
 finally:
  builtins.__import__=real_import;sys.argv=real_argv
 ctx=json.loads((d/'ctx.json').read_text());recs=ctx['stock_capital_records']
 assert len(recs)==1,f'expected exactly one stock-capital record for unavailable latest cell, got {len(recs)}'
 r=recs[0];assert r['state']=='UNKNOWN' and r['evidence_grade']=='SOURCE_UNAVAILABLE' and r['source_status']=='UNAVAILABLE',r
 assert r['current_report_period']=='2021-09-30',r
 assert r['current_holding_ratio']=='' and not r['actor_id'],'stale actor must not be attributed'
 print(json.dumps({'status':'PASS','negative':'no stale fallback','record':r},ensure_ascii=False))
if __name__=='__main__':main()
