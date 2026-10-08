#!/usr/bin/env python3
"""Rebuild LHB stock-day from lhb_raw (v2, correct semantics).
SSE: pageHelp rows = stock×side×reason; secTxAmount = side total; seats = branchName(S|B) list.
SZSE detail: file {date}_{code}_{ref}.json page[1].data = seat rows (mmlb/zsmc/mrje/mcje).
Output e5.db lhb(code,date,buy,sell,inst_net,nb_net,nseats).
"""
from __future__ import annotations
import json,re,sqlite3,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; E=ROOT/'data/r2/e5'; DB=E/'e5.db'
INST=re.compile(r'机构专用'); NB=re.compile(r'(沪股通|深股通|港股通|香港中央结算)')
def f(x):
 try: return float(str(x).replace(',','').replace('&nbsp;','').split(' ')[0])
 except Exception: return 0.0
def main():
 con=sqlite3.connect(DB)
 con.execute('DROP TABLE IF EXISTS lhb')
 con.execute('CREATE TABLE lhb(code TEXT,date TEXT,buy REAL,sell REAL,inst_net REAL,nb_net REAL,nseats INT)')
 for tb in sorted((E/'lhb_raw').glob('lhb_raw_*.tar.gz')):
  t0=time.time(); acc={}
  tf=tarfile.open(tb)
  for mem in tf:
   if not mem.name.endswith('.json'): continue
   full=mem.name; fn=full.split('/')[-1]
   try: j=json.load(tf.extractfile(mem))
   except Exception: continue
   if full.startswith('sse_'):
    date=fn[:8]  # sse_main/20230103.json
    seen=set()
    for r in ((j.get('pageHelp') or {}).get('data') or []):
     code=str(r.get('secCode') or '').zfill(6)
     if not code.isdigit(): continue
     side=r.get('bsType'); amt=f(r.get('secTxAmount'))
     key=(code,date,side,r.get('refType'),r.get('abnormalStart'),r.get('abnormalEnd'))
     if key in seen: continue
     seen.add(key)
     d=acc.setdefault((code,date),{'b':0.,'s':0.,'ib':0.,'is':0.,'nb':0.,'n':0})
     names=[x for x in re.split('[，,；;]',str(r.get('branchNameS') or '')+str(r.get('branchNameB') or '')) if x.strip()]
     d['n']+=len(names)
     if side=='B':
      d['b']+=amt
      if any(INST.search(x) for x in names): d['ib']+=amt
      if any(NB.search(x) for x in names): d['nb']+=amt
     else:
      d['s']+=amt
      if any(INST.search(x) for x in names): d['is']+=amt
      if any(NB.search(x) for x in names): d['nb']-=amt
   elif full.startswith('szse_detail/'):
    parts=fn.replace('.json','').split('_')
    if len(parts)<3: continue
    date=parts[0]; code=parts[1].zfill(6)
    if not code.isdigit(): continue
    pages=j if isinstance(j,list) else [j]
    d=acc.setdefault((code,date),{'b':0.,'s':0.,'ib':0.,'is':0.,'nb':0.,'n':0})
    for pg in pages:
     for r in pg.get('data') or []:
      if not isinstance(r,dict) or 'mmlb' not in r: continue
      buy=f(r.get('mrje')); sell=f(r.get('mcje')); nm=str(r.get('zsmc') or '')
      d['n']+=1
      d['b']+=buy if str(r.get('mmlb','')).startswith('买') else 0
      d['s']+=sell if str(r.get('mmlb','')).startswith('卖') else 0
      if INST.search(nm):
       d['ib']+=buy if str(r.get('mmlb','')).startswith('买') else 0
       d['is']+=sell if str(r.get('mmlb','')).startswith('卖') else 0
      if NB.search(nm): d['nb']+=buy-sell
   elif full.startswith('szse_list/'):
    continue  # summary only; detail covers seats
  for (code,date),d in acc.items():
   con.execute('INSERT OR REPLACE INTO lhb VALUES (?,?,?,?,?,?,?)',(code,date,d['b'],d['s'],d['ib']-d['is'],d['nb'],d['n']))
  con.commit(); print(tb.name,len(acc),round(time.time()-t0,1),'s',flush=True)
 print('lhb',con.execute('SELECT COUNT(*),COUNT(DISTINCT code),MIN(date),MAX(date) FROM lhb').fetchone())
 con.execute('CREATE INDEX IF NOT EXISTS ix_l ON lhb(code,date)'); con.commit(); con.close()
if __name__=='__main__':main()
