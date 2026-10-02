#!/usr/bin/env python3
"""Precision follow-up for the NC-ERRATUM-1.1 disappearance fixture.

Unlike the frozen v2_1 report, this fixture supplies an explicit publication
row for the latest period and asserts stock_layer_summary_report_period. It
must not rewrite the v2_1 historical report.
"""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_national_capital_context_v1e1 as b
import csr8_phase_c_annotation_seal as c4d

def main():
    cand=c4d.candidate_for_ordinal(4); salt=c4d.c1.load_salt()
    plan=json.loads(c4d.c1.PLAN_FILE.read_text())
    m=[e for e in plan['entries'] if c4d.c1.opaque_case_id(salt,e['case_key'])==cand['opaque_case_id'] and e['T']==cand['T']]
    assert len(m)==1; sc=m[0]['case_key'].split('|')[1]
    fixture={
      'pit':[{'stock_code':sc,'report_period':'2020-12-31','actor_id':'A-TEST-FIXTURE','holding_ratio':'1.23','available_date':'2021-03-30','publication_date':'20210329','source_grade':'GRADE_A'}],
      'ledger':[{'stock_code':sc,'report_period':'2020-12-31','source_status':'SUCCESS_NONEMPTY'},{'stock_code':sc,'report_period':'2021-03-31','source_status':'SUCCESS_NONEMPTY'}],
      'pub':[{'stock_code':sc,'report_period':'2021-03-31','publication_date':'20210430'}],
      'calendar':['2021-03-30','2021-05-06'], 'etf':[]}
    ctx=b.build(4,data=fixture)
    assert ctx['stock_layer_summary']=='NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'
    assert ctx['stock_layer_summary_report_period']=='2021-03-31',ctx['stock_layer_summary_report_period']
    assert len(ctx['stock_capital_records'])==1
    r=ctx['stock_capital_records'][0]
    assert r['actor_id']=='A-TEST-FIXTURE' and r['state']=='NOT_DISCLOSED_IN_TOP10'
    assert r['current_holding_ratio']==''
    report={'status':'PASS','test':'disappearance fixture precision v2_2',
            'latest_publication_row':{'report_period':'2021-03-31','publication_date':'20210430'},
            'calendar_fallback_date':'2021-05-06',
            'assertions':{'summary':'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10','summary_not_present':True,'summary_report_period':'2021-03-31','records':1,'record_state':'NOT_DISCLOSED_IN_TOP10','current_ratio_empty':True}}
    out=ROOT/'docs/audit/evidence/support_contract_test_report_v2_2.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
