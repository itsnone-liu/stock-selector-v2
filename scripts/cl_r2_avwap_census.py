#!/usr/bin/env python3
"""CL-R2 Support-First census: event/data-contract audit for Event-Anchored AVWAP.
Census only — no outcome variables are computed or inspected."""
import gzip,json,math,statistics,hashlib
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'
EPS=ROOT/'data/cd/l4_episodes.json.gz'; SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUT=ROOT/'data/cl_radar/r2_avwap/census.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R2_AVWAP_CENSUS.md'
def q(xs,p):
 xs=sorted(xs);k=(len(xs)-1)*p;f=int(k);c=min(f+1,len(xs)-1);return xs[f]+(xs[c]-xs[f])*(k-f)
def med(xs):return statistics.median(xs) if xs else None
def codes():
 x=json.load(open(SAMPLE));c=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 return c,hashlib.sha256(('\n'.join(c)+'\n').encode()).hexdigest()
def main():
 cs,sha=codes();eps=json.load(gzip.open(EPS,'rt'))['episodes']
 by=defaultdict(list)
 for e in eps:
  if e['stock'] in {c.split('.')[1] for c in cs}:by[e['stock']].append(e)
 stat={'sample_n':len(cs),'sample_sha':sha,'episodes_total_in_file':len(eps),'episodes_in_sample':sum(len(v) for v in by.values()),'stocks_with_episodes':len(by),'per_stock':{'episodes':{'median':med([len(v) for v in by.values()]),'min':min((len(v) for v in by.values()),default=0),'max':max((len(v) for v in by.values()),default=0)}}}
 dur=[];cov_amt=[];cov_vol=[];fbreak=[];avdev=[];n_ep=0;n_ep_amt_bad=0;n_ep_vol_bad=0;n_ep_fbreak=0;win_min=6
 fails=[]
 for code in cs:
  six=code.split('.')[1]
  try:
   rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  except FileNotFoundError as ex:
   fails.append(f'{code}:missing:{ex.filename}');continue
  ds=rec['dates'];idx={d:i for i,d in enumerate(ds)};qfq=rec['qfq'];unadj=rec['unadj']
  for e in by[six]:
   s,t=e['start'],e['end']
   if s not in idx or t not in idx:continue
   i0,i1=idx[s],idx[t];n=i1-i0+1;n_ep+=1;dur.append(n)
   a_ok=v_ok=fac_change=0;fac0=None;devs=[]
   for j in range(i0,i1+1):
    d=ds[j];a=float(ext.get(d,{}).get('amount') or 0);v=float(unadj[j][5] or 0)
    if a>0:a_ok+=1
    if v>0:v_ok+=1
    u=float(unadj[j][2]);qq=float(qfq[j][2])
    if u>0 and qq>0:
     fac=qq/u
     if fac0 is None:fac0=fac
     if abs(fac-fac0)/fac0>1e-6:fac_change+=1
     if a>0 and v>0:devs.append(abs(a/v/((float(unadj[j][1])+u+float(unadj[j][3])+float(unadj[j][4]))/4)-1))
   cov_amt.append(a_ok/n);cov_vol.append(v_ok/n)
   fbreak.append(fac_change/n)
   if devs:avdev.append(statistics.fmean(devs))
   if a_ok/n<0.95:n_ep_amt_bad+=1
   if v_ok/n<0.95:n_ep_vol_bad+=1
   if fac_change>0:n_ep_fbreak+=1
 stat.update({
  'episodes_audited':n_ep,'files_unreadable':fails,
  'duration_days':{'median':med(dur),'p10':q(dur,.1),'p90':q(dur,.9),'min':min(dur,default=0),'max':max(dur,default=0),'below_min_window_6':sum(1 for x in dur if x<win_min)},
  'amount_coverage':{'median':med(cov_amt),'p10':q(cov_amt,.1),'episodes_below_0.95':n_ep_amt_bad},
  'volume_coverage':{'median':med(cov_vol),'p10':q(cov_vol,.1),'episodes_below_0.95':n_ep_vol_bad},
  'adjustment_factor_breaks':{'episodes_with_any_break':n_ep_fbreak,'break_frac_median':med(fbreak),'break_frac_p90':q(fbreak,.9)},
  'avwap_vs_unadj_ohlc4_deviation':{'median':med(avdev),'p90':q(avdev,.9),'n_episodes_measured':len(avdev)},
 })
 # G1-style verdict inputs, no outcome data touched.
 ok = (n_ep>0 and med(cov_amt) and med(cov_amt)>=0.99 and med(cov_vol)>=0.99 and n_ep_fbreak/n_ep<=0.05 and med(avdev)<0.05)
 stat['census_verdict']='SUFFICIENT_SUPPORT' if ok else 'INSUFFICIENT_SUPPORT_REVIEW'
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(stat,ensure_ascii=False,indent=2))
 L=['# CL-R2 AVWAP Support-First 普查（census only）','',f"- sample: {stat['sample_n']} stocks, sha {stat['sample_sha'][:12]}…",f"- episodes audited: {n_ep}（CD-5 L4, 冻结文件）",f"- census verdict: **{stat['census_verdict']}**",'', '| 项 | 值 |','|---|---|']
 for k in ('duration_days','amount_coverage','volume_coverage','adjustment_factor_breaks','avwap_vs_unadj_ohlc4_deviation'):
  v=stat[k];L.append(f"| {k} | "+"；".join(f"{kk}={vv:.4f}" if isinstance(vv,float) else f"{kk}={vv}" for kk,vv in v.items())+" |")
 L+=['','判定规则（预注册）：amount/volume 覆盖中位≥0.99，episode 内复权因子断裂 episode 占比≤5%，AVWAP vs 未复权 OHLC4 偏离中位<5%。普查未读任何结果变量。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(stat,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
