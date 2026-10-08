#!/usr/bin/env python3
"""E5 ingestion: stock-data repo tarballs -> sqlite e5.db (margin/block per stock-day).
Streaming, memory-light. LHB already CSV (used directly later).
"""
from __future__ import annotations
import json,sqlite3,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; E=ROOT/'data/r2/e5'; DB=E/'e5.db'
def num(x):
 if x is None: return None
 try:
  v=float(str(x).replace(',','').replace('&nbsp;',''))
  return v
 except Exception: return None
def margin(con):
 con.execute('CREATE TABLE IF NOT EXISTS margin(code TEXT,date TEXT,rzye REAL,rzbuy REAL)')
 for mkt,pat,unit in (('sse','margin/sse/sse_*.tar.gz',1.0),('szse','margin/szse/szse_*.tar.gz',1e8)):
  for tb in sorted((E/pat).parent.glob(tb_pat:=pat.split('/')[-1])):
   t0=time.time(); n=0
   tf=tarfile.open(tb)
   for mem in tf:
    if not mem.name.endswith('.json'): continue
    try: j=json.load(tf.extractfile(mem))
    except Exception: continue
    date=None; rows=[]
    if mkt=='sse':
     date=mem.name[:8]
     for r in (j.get('pageHelp') or {}).get('data') or []:
      code=str(r.get('securityCode') or r.get('stockCode') or r.get('stockid') or '').zfill(6)
      if not code or not code[:2].isdigit(): continue
      rows.append((code,date,num(r.get('rzye')),num(r.get('rzmre'))))
    else:
     date=mem.name[:8]
     pages=j if isinstance(j,list) else [j]
     for pg in pages:
      for r in pg.get('data') or []:
       code=str(r.get('zqdm') or '').zfill(6)
       if not code.isdigit(): continue
       v=num(r.get('jrrzye'))
       rows.append((code,date,(v*unit if v is not None else None),num(r.get('jrrzmr'))*unit if num(r.get('jrrzmr')) is not None else None))
    if rows:
     con.executemany('INSERT OR REPLACE INTO margin VALUES (?,?,?,?)',rows); n+=len(rows)
   con.commit()
   print(mkt,tb.name,n,'rows',round(time.time()-t0,1),'s',flush=True)
def block(con):
 con.execute('CREATE TABLE IF NOT EXISTS block(code TEXT,date TEXT,amount REAL,price REAL,qty REAL)')
 for pat in ('block/sse/sse_*.tar.gz','block/szse_detail/szse_detail_*.tar.gz'):
  for tb in sorted((E/pat).parent.glob(pat.split('/')[-1])):
   t0=time.time(); n=0
   tf=tarfile.open(tb)
   for mem in tf:
    if not mem.name.endswith('.json'): continue
    try: j=json.load(tf.extractfile(mem))
    except Exception: continue
    date=mem.name[:8]; rows=[]
    data=(j.get('pageHelp') or {}).get('data') if isinstance(j,dict) else None
    if data is None and isinstance(j,list): data=[r for pg in j for r in (pg.get('data') or [])]
    if data is None and isinstance(j,dict):
     data=j.get('data') or []
     if isinstance(data,dict): data=[data]
    for r in data or []:
     if not isinstance(r,dict): continue
     code=str(r.get('stockid') or r.get('zqdm') or r.get('securityCode') or '').zfill(6)
     if not code.isdigit(): continue
     amt=num(r.get('tradeamount'))
     if amt is None: amt=num(r.get('cjje'))
     qty=num(r.get('tradeqty')); 
     if qty is None: qty=num(r.get('cjsl'))
     price=num(r.get('tradeprice'));
     if price is None: price=num(r.get('cjjg'))
     rows.append((code,date,amt,price,qty))
    if rows: con.executemany('INSERT OR REPLACE INTO block VALUES (?,?,?,?,?)',rows); n+=len(rows)
   con.commit(); print('block',tb.name,n,'rows',round(time.time()-t0,1),'s',flush=True)
def main():
 con=sqlite3.connect(DB)
 margin(con); block(con)
 for t in ('margin','block'):
  print(t,con.execute(f'SELECT COUNT(*),COUNT(DISTINCT code),MIN(date),MAX(date) FROM {t}').fetchone())
 con.execute('CREATE INDEX IF NOT EXISTS ix_m ON margin(code,date)'); con.execute('CREATE INDEX IF NOT EXISTS ix_b ON block(code,date)')
 con.commit(); con.close()
if __name__=='__main__':main()
