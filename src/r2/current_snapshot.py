#!/usr/bin/env python3
"""R2-1: Current Capital/Chip Snapshot v1 (market / sector / key stocks / policy proxy)."""
from __future__ import annotations
import gzip,json,statistics
from collections import defaultdict,Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.capital_inference.features import snapshot as fsnap
from src.capital_inference.state_engine import infer
POLICY_ETF={'510050','510300','510500','510180','510330','510510','588000','588080','159915','159919','159949','510880','512100','510630'}
def policy_proxy():
 d=ROOT/'data/csr8_national_capital/raw/etf_shares'
 fs=sorted(x for x in d.glob('*.json') if not x.name.endswith('meta.json'))
 days=[x for x in fs if x.name>='2026-01-01']
 tot=defaultdict(float); alltot=defaultdict(float)
 for f in days:
  try: r=json.load(open(f)).get('result') or []
  except Exception: continue
  for row in r:
   c=row.get('SEC_CODE'); v=float(row.get('TOT_VOL') or 0)
   alltot[f.name[:10]]+=v
   if c in POLICY_ETF: tot[f.name[:10]]+=v
 ks=sorted(tot); rec=sorted(alltot)
 rec=[k for k in rec if k in tot]
 if len(ks)<40: return {'state':'不可判断','reason':f'insufficient days {len(ks)}'}
 recent=statistics.mean([tot[k] for k in ks[-20:]]); prior=statistics.mean([tot[k] for k in ks[-60:-20]])
 chg=recent/prior-1 if prior else None
 ar=statistics.mean([alltot[k] for k in rec[-20:]])/max(1e-9,statistics.mean([alltot[k] for k in rec[-60:-20]]))-1
 state='增持' if chg and chg>0.03 else ('减持' if chg and chg<-0.03 else '稳定')
 return {'policy_etf_share_chg_60d':round(chg,4) if chg is not None else None,'all_etf_share_chg_60d':round(ar,4),'state':state,'n_days':len(ks),'asof':ks[-1],'confidence':'MEDIUM','note':'POLICY_CAPITAL_PROXY via curated broad-index ETF set; not account-level truth'}
def margin_signal():
 d=ROOT/'data/r2/margin'; rows=[]
 for f in sorted(d.glob('sse_*.json')):
  rows+=json.loads(f.read_text())['rows']
 rows.sort(key=lambda r:r['date'])
 if len(rows)<60: return {'state':'不可判断'}
 r20=[r['rzye'] for r in rows[-20:]]; p60=[r['rzye'] for r in rows[-60:-20]]
 chg=(sum(r20)/len(r20))/(sum(p60)/len(p60))-1
 return {'sse_rzye_chg_60d':round(chg,4),'asof':rows[-1]['date'],'state':'融资增加' if chg>0.01 else ('融资减少' if chg<-0.01 else '平稳'),'scope':'SSE_ONLY(szse被墙)'}
def holders_aggregate():
 import glob as g
 rows=[]
 for f in sorted((ROOT/'data/r2/holders').glob('*.json')):
  d=json.loads(f.read_text())['rows']
  ch=[r['holders_chg_pct'] for r in d if r.get('holders_chg_pct') is not None]
  if ch: rows.append({'date':f.stem,'median_chg':sorted(ch)[len(ch)//2]})
 rows.sort(key=lambda x:x['date'])
 return {'latest':rows[-1] if rows else None,'trend_4q':[r['median_chg'] for r in rows[-4:]],'read':'户数扩散中' if rows and rows[-1]['median_chg']>2 else ('户数收敛中' if rows and rows[-1]['median_chg']<-2 else '平稳')}
def national_team_stocks():
 out=[]
 for f in sorted((ROOT/'data/r2/institutional').glob('*.json')):
  q=json.loads(f.read_text())['quarters']; ks=sorted(q)
  if not ks: continue
  v=q[ks[-1]]; prev=q[ks[-2]] if len(ks)>1 else None
  nt=sum(x['ratio'] for x in v['national_team']); pnt=sum(x['ratio'] for x in prev['national_team']) if prev else None
  out.append({'stock':f.stem,'quarter':ks[-1],'nt_ratio':round(nt,2),'nt_prev_ratio':round(pnt,2) if pnt is not None else None,'state':'在场增持' if pnt is not None and nt>pnt+0.05 else ('在场减持' if pnt is not None and nt<pnt-0.05 else ('在场稳定' if nt>0.05 else '不在场')),'top10_ratio':v['top10_float_ratio']})
 return sorted(out,key=lambda x:-(x['nt_ratio'] or 0))
def market_and_sectors():
 panel=ROOT/'data/r2/panel_monthly.jsonl'
 last={}
 with open(panel) as f:
  for line in f:
   r=json.loads(line); last[r['stock']]=r
 members={m['code']:m.get('L2') for m in json.load(open(ROOT/'data/cd/sector_seeds/csrc_v1.json'))['members']}
 cnt=Counter(r['state'] for r in last.values())
 prof=[r['profit_vs_cost'] for r in last.values() if r.get('profit_vs_cost') is not None]
 pos=[r['pos250'] for r in last.values() if r.get('pos250') is not None]
 mkt={'asof_ym':max(r['ym'] for r in last.values()),'n_stocks':len(last),'state_census':dict(cnt),
  'median_profit_vs_cost':round(statistics.median(prof),4) if prof else None,'pct_above_cost':round(sum(p>0 for p in prof)/len(prof),3) if prof else None,
  'median_pos250':round(statistics.median(pos),4) if pos else None,
  'market_chip_read':'套牢偏重' if statistics.median(prof)<-0.05 else ('成本附近' if statistics.median(prof)<0.05 else '获利偏重')}
 sec=defaultdict(list)
 for c,r in last.items():
  l2=members.get(c)
  if l2: sec[l2].append(r)
 smap={}
 for l2,rs in sec.items():
  if len(rs)<15: continue
  smap[l2]={'n':len(rs),'acc_plus_mature_share':round(sum(r['state'] in('ACCUMULATION','ACCUMULATION_MATURE') for r in rs)/len(rs),3),
   'markup_ready_share':round(sum(r['state']=='MARKUP_READY' for r in rs)/len(rs),3),
   'distribution_risk_share':round(sum(r['state']=='DISTRIBUTION_RISK' for r in rs)/len(rs),3),
   'median_pos250':round(statistics.median([r['pos250'] for r in rs if r.get('pos250') is not None]),3),
   'median_profit_vs_cost':round(statistics.median([r['profit_vs_cost'] for r in rs if r.get('profit_vs_cost') is not None]),4) if any(r.get('profit_vs_cost') is not None for r in rs) else None}
 return mkt,smap
def key_stocks(n=40):
 D=ROOT/'data/cd/daily_fullmarket'; rows=[]
 for p in sorted(D.glob('*.json.gz')):
  code=p.name[:-8]
  try: r=json.load(gzip.open(p,'rt'))
  except Exception: continue
  ds=r['dates']
  if len(ds)<260: continue
  cl=[float(x[2]) for x in r['qfq']]; hi=[float(x[3]) for x in r['qfq']]; lo=[float(x[4]) for x in r['qfq']]; vol=[float(x[5]) for x in r['unadj']]
  rows.append((sum(vol[-20:]),code,ds,cl,hi,lo,vol))
 rows.sort(reverse=True)
 out=[]
 for v,code,ds,cl,hi,lo,vol in rows[:n]:
  f=fsnap(cl,hi,lo,vol,None,len(ds)-1)
  if f is None: continue
  st=infer(f); c=cl[-1]
  out.append({'stock':code,'close':c,'cost_band':[f['p25'],f['p50'],f['p75']],'dist_to_cost_center':round(c/f['p50']-1,4) if f['p50'] else None,'band_width':f['band_width'],'chip_locking':f['chip_locking'],'floating_supply':f['floating_supply'],'state':st['state'],'confidence':st['confidence']})
 return out
def main():
 pp=policy_proxy(); mkt,smap=market_and_sectors(); ks=key_stocks(); ms=margin_signal(); ha=holders_aggregate(); nt=national_team_stocks()
 strong=sorted(smap.items(),key=lambda kv:-(kv[1]['acc_plus_mature_share']+kv[1]['markup_ready_share']))[:5]
 weak=sorted(smap.items(),key=lambda kv:-kv[1]['distribution_risk_share'])[:5]
 snap={'generated':'2026-10-05','national_team_policy_proxy':pp,'margin_market':ms,'holders_market':ha,'national_team_stocks_present':[x for x in nt if x['nt_ratio']>0.05],
  'sector_top_accumulation_ready':{k:v for k,v in strong},'sector_top_distribution_risk':{k:v for k,v in weak},
  'key_stocks_cost_bands':ks,
  'missing_data_markers':{'E4_ownership':'not yet ingested','E5_public_signals':'not yet ingested','free_float':'fetch in progress (background)','contradictions':[]}}
 out=ROOT/'data/r2/snapshot_current.json'; out.write_text(json.dumps(snap,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'policy':pp['state'],'chg':pp.get('policy_etf_share_chg_60d'),'margin':ms.get('state'),'holders':ha.get('read'),'nt_stocks':len(snap_missing) if False else len([x for x in nt if x['nt_ratio']>0.05]),'market':mkt['market_chip_read'],'sectors':len(smap),'key_stocks':len(ks)},ensure_ascii=False))
if __name__=='__main__':main()
