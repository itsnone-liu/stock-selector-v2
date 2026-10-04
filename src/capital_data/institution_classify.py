#!/usr/bin/env python3
"""R2 §6: NATIONAL_TEAM_ENTITY_REGISTRY + holder-type classification
from csr8_national_capital holdings disclosures (top-10 float holders).
Outputs per stock-quarter institutional profile + registry JSON.
"""
from __future__ import annotations
import json,re
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SRC=ROOT/'data/csr8_national_capital/raw/holdings'; OUT=ROOT/'data/r2/institutional'
REGISTRY={
 'NATIONAL_TEAM':['中央汇金','汇金投资','汇金资产管理','中国证券金融','证金资产管理','国家集成电路产业投资基金','国新投资','中央汇金资产管理','梧桐树投资','凤山投资','坤藤投资'],
 'SOCIAL_SECURITY':['全国社保基金','社保基金']}
def classify(name):
 n=name or ''
 if any(k in n for k in REGISTRY['NATIONAL_TEAM']): return 'NATIONAL_TEAM'
 if any(k in n for k in REGISTRY['SOCIAL_SECURITY']): return 'SOCIAL_SECURITY'
 if '香港中央结算' in n: return 'HKSCC'
 if '社保' in n: return 'SOCIAL_SECURITY'
 if re.search(r'(基金|资管|资产管理|集合资金信托)',n): return 'FUND'
 if re.search(r'(保险|人寿|财险|养老)',n): return 'INSURANCE'
 if re.search(r'(证券公司|证券股份|证券有限)',n): return 'BROKER'
 if re.search(r'(QFII|银行|海外|UBS|摩根|高盛|瑞银|美林|花旗|施罗德|惠理)',n): return 'QFII_FOREIGN'
 if re.search(r'(集团|有限公司|有限责任公司|控股|实业|投资)',n): return 'CORPORATE'
 return 'OTHER'
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 per=defaultdict(dict); stats=defaultdict(int); cov_stocks=set(); cov_periods=set()
 for f in sorted(SRC.glob('*.json')):
  if f.name.endswith('.meta.json'): continue
  stem=f.name[:-5]
  try: code=stem.split('__')[0].split('_')[1]; period=stem.split('__')[1]
  except Exception: continue
  try:
   _o=json.loads(f.read_text()); resp=_o.get('response') if isinstance(_o,dict) else None
  except Exception: continue
  if not isinstance(resp,dict): continue
  rows=[r for r in (resp.get('sdltgd') or []) if isinstance(r,dict)]
  if not rows: continue
  cov_stocks.add(code); cov_periods.add(period)
  top10_ratio=0.0; nt=[]; byt=defaultdict(lambda:[0,0.0])
  for r in rows:
   t=classify(r.get('HOLDER_NAME')); stats[t]+=1
   ratio=r.get('FREE_HOLDNUM_RATIO') or 0
   top10_ratio+=ratio or 0
   byt[t][0]+=1; byt[t][1]+=ratio or 0
   if t in ('NATIONAL_TEAM','SOCIAL_SECURITY'):
    nt.append({'name':r.get('HOLDER_NAME'),'ratio':ratio,'change':r.get('HOLD_NUM_CHANGE')})
  per[code][period]={'top10_float_ratio':round(top10_ratio,3),
   'by_type':{k:{'n':v[0],'ratio':round(v[1],3)} for k,v in byt.items()},
   'national_team':nt}
 for code,d in per.items():
  (OUT/f'{code}.json').write_text(json.dumps({'meta':{'source':'csr8_national_capital/raw/holdings(sdltgd)','holder_classifier':'institution_classify.v1'},'quarters':dict(sorted(d.items()))},ensure_ascii=False,indent=1))
 reg={'NATIONAL_TEAM_ENTITY_REGISTRY':{'confirmed_entities':REGISTRY['NATIONAL_TEAM'],'long_term_state_capital':REGISTRY['SOCIAL_SECURITY'],'note':'账户级身份以公开披露名称匹配；POLICY_CAPITAL_PROXY(宽基ETF行为代理)与之严格分离,见 snapshot_current.json'},
  'POLICY_CAPITAL_PROXY':{'definition':'不能确认最终账户所有者,但资金行为集中于政策相关宽基ETF/大型指数工具','implementation':'data/r2/snapshot_current.json national_team_policy_proxy'},
  'holder_type_distribution':dict(stats),
  'coverage':{'stocks':len(cov_stocks),'stock_quarters':sum(len(v) for v in per.values()),'periods':sorted(cov_periods)[:2]+['...']+sorted(cov_periods)[-2:]}}
 (ROOT/'data/r2/NATIONAL_TEAM_REGISTRY.json').write_text(json.dumps(reg,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'stocks':len(cov_stocks),'stock_quarters':sum(len(v) for v in per.values()),'type_dist':dict(stats)},ensure_ascii=False))
if __name__=='__main__':main()
