#!/usr/bin/env python3
"""R2-DU(G): daily update orchestrator — ONE command from TDX mirror to report.

Chain (fail-closed, idempotent per step; logs to data/r2/daily_update/):
  0. preconditions: TDX mirror has bars for --day; repo clean-ish
  A. daily_price_update  — tencent fqkline append + TDX cross-validate
  C. axes roll           — cd1b(L2) → cd45(L1) → cd2bc → cd4v2 → cd5a
                          with subset-equality check (history rows must survive)
  E. current_scan        — full rerun → data/r2/scans/current_scan_<day>.json
  F. daily_report        — migration diff + cross stats + BROKEN queue

Usage: .venv/bin/python src/r2/daily_update.py --day 2026-10-08 [--skip A,C,E,F]
Exit code !=0 on any failure; manifest at data/r2/daily_update/update_<day>.json
"""
from __future__ import annotations
import argparse,fcntl,gzip,json,math,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'data'; OUTD=ROOT/'data/r2/daily_update'
PY=str(ROOT/'.venv/bin/python')
BUILDERS=[('C1','scripts/cd1b_four_axis_engine.py'),('C2','scripts/cd45_market_regime.py'),
          # 2026-10-21: cd2a 原本没挂任何调度 → bands 自 10-04 起冻结在节前 09-30，
          # 导致 C3(l2_state_table) 每日「OK 3s」却只写到 09-30（典型静默不完整）。
          # 它读 C1 的 l2_four_axes、产 C3 的 l2_axis_bands，实测 4.8s 且确定性自检 PASS，故并入日更链。
          ('C1A','scripts/cd2a_census_and_bands.py'),
          ('C3','scripts/cd2bc_state_engine.py'),('C4','scripts/cd4v2_multi_source.py'),
          ('C5','scripts/cd5a_episodes.py')]
ARTS={'l2_four_axes':'data/cd/sector_axes/l2_four_axes.json.gz','l1_market_axes':'data/cd/sector_axes/l1_market_axes.json.gz',
      'l2_state_table':'data/cd/sector_axes/l2_state_table.json.gz','l3_pool':'data/cd/l3_candidate_pool_v2.json.gz',
      'l4_episodes':'data/cd/l4_episodes.json.gz'}
# lifecycle tables: open rows legitimately extend (end/seq mutate) -> check KEY survival, not serialization
KEYED={'l4_episodes':lambda r:(r.get('episode_id'),)}
# l3_pool is NOT a row list: pools = {monthly snapshot key 'YYYY-MM-DD' -> {L,M,S,U_list}}, one key per
# calendar month (key date = that month's last refresh). Generic rows_of() iterates the dict -> yields
# snapshot KEYS, so the old KEYED check compared key survival and false-fired on every in-month re-key
# (2026-10-09 -> 2026-10-12). Dedicated check_l3_pool() enforces the real invariants instead.

def rows_of(p):
 x=json.loads(gzip.decompress(Path(p).read_bytes()))
 for k in ('rows','states','pools','episodes'):
  if k in x: return x[k]
 return x

MASKED_FIELDS={'l1_market_axes':frozenset({'b_conc','b_disp','b_part'})}
# ^ thresholded band READOUTS (conc50/disp quantised): rebase micro-perturbation may legitimately flip a band
 # at the threshold edge. True states (status/n) and all other artifacts stay strict.

# 2026-10-21 user ruling 「不要冻结」+「阈值随慢频更新重推」: cd2a CARRYs thresholds on the daily chain
# (step C1A) and only re-derives them when a slow-frequency data update event is announced, so a carried
# band table is stable in normal operation. A refit day may still legitimately relabel historical rows in
# l2_state_table (base/mods). Tolerate up to a bound and report WARN — but losing the row IDENTITY
# (l2,date,n) still aborts, so a truncated/rebuilt-from-wrong-input catastrophe cannot pass silently.
# A slow-data refit can honestly exceed the default bound: raise it for that single run, explicitly, via
#   R2_L2_RELABEL_BUDGET=<n>   (logged loudly; the identity-loss check is never affected)
LABEL_DRIFT_MAX_FRAC=0.002; LABEL_DRIFT_MAX_ABS=500
LABEL_DRIFT_BUDGET_ENV='R2_L2_RELABEL_BUDGET'
def check_l2_state(old,newr,recent,day):
 newix={}
 for r in newr:
  if r.get('date') in recent: continue
  newix[(r.get('l2'),r.get('date'))]=(r.get('n'),r.get('base'),json.dumps(r.get('mods'),sort_keys=True))
 compared=drift=missing=0; bydate={}
 for x in old:
  ro=json.loads(x)
  if ro.get('date') in recent: continue
  compared+=1
  cur=newix.get((ro.get('l2'),ro.get('date')))
  if cur is None or cur[0]!=ro.get('n'): missing+=1; continue
  if cur[1]!=ro.get('base') or cur[2]!=json.dumps(ro.get('mods'),sort_keys=True):
   drift+=1; bydate[ro.get('date')]=bydate.get(ro.get('date'),0)+1
 if missing:
  raise SystemExit(f'HISTORY LOST in l2_state_table: {missing}/{compared} rows lost (identity l2/date/n gone) — aborting (backup: data/cd/sector_axes/backup_*)')
 bound=max(LABEL_DRIFT_MAX_ABS,LABEL_DRIFT_MAX_FRAC*compared)
 _ovr=os.environ.get(LABEL_DRIFT_BUDGET_ENV)
 if _ovr:
  try: _ovrn=int(_ovr)
  except ValueError: _ovrn=0
  if _ovrn>bound:
   print(f'NOTE l2_state_table relabel budget OVERRIDDEN {bound:.0f} -> {_ovrn} via {LABEL_DRIFT_BUDGET_ENV} (slow-data refit window)',flush=True)
   bound=float(_ovrn)
 if drift>bound:
  raise SystemExit(f'HISTORY LOST in l2_state_table: {drift}/{compared} rows relabelled (bound {bound:.0f}) — aborting (backup: data/cd/sector_axes/backup_*)')
 if drift:
  top=sorted(bydate.items(),key=lambda kv:-kv[1])[:5]
  print(f'WARN l2_state_table 标签迁移(阈值重推/carry漂移) tolerated: {drift}/{compared} rows, top dates {top}',flush=True)

def fingerprint(x,mask=frozenset()):
 # structure + non-numeric + INTEGER counts stay strict; floats are masked (tolerated separately)
 if isinstance(x,bool) or x is None or isinstance(x,str): return json.dumps(x)
 if isinstance(x,int): return str(x)
 if isinstance(x,float): return '#'
 if isinstance(x,list): return '['+','.join(fingerprint(v,mask) for v in x)+']'
 if isinstance(x,dict): return '{'+','.join(f'{json.dumps(k)}:{"#M" if k in mask else fingerprint(v,mask)}' for k,v in sorted(x.items()))+'}'
 return repr(x)

def floats_of(x,mask=frozenset()):
 if isinstance(x,bool) or x is None or isinstance(x,str) or isinstance(x,int): return []
 if isinstance(x,float): return [x]
 if isinstance(x,list):
  out=[]
  for v in x: out+=floats_of(v,mask)
  return out
 if isinstance(x,dict):
  out=[]
  for k,v in sorted(x.items()):
   if k not in mask: out+=floats_of(v,mask)
  return out
 return []

def rows_tolerance_pass(lost,newr,recent,mask=frozenset()):
 # P2 fix 2026-10-13: qfq segment-wide rebasing (exdiv_refetch; runbook §6 source trait, NOT history rewrite)
 # propagates micro-perturbations through market/sector-layer rolling stats into history rows
 # (observed 2026-10-13: p50~1e-5, p99.9~7e-2 rel, near-zero ratios up to ~2 rel; band readouts may flip).
 # Tolerance: fingerprint (structure+non-numeric+int counts, minus masked band fields) EXACT;
 # floats |a-b|<=1e-3 OR rel<=1e-2. Observed rebase propagation ceiling ~5e-4 abs (top5_mean_ret:
 # an ex-div stock inside a sector's top-5 weights shifts that day's mean by ~0.1%/5).
 buckets={}
 for r in newr:
  if r.get('date') in recent: continue
  buckets.setdefault(fingerprint(r,mask),[]).append(floats_of(r,mask))
 still=set()
 for x in lost:
  ro=json.loads(x); fs=floats_of(ro,mask)
  if not any(len(cf)==len(fs) and all(abs(p-q)<=1e-3 or math.isclose(p,q,rel_tol=1e-2)
             for p,q in zip(fs,cf)) for cf in buckets.get(fingerprint(ro,mask),[])):
   still.add(x)
 return still

def check_l3_pool(oldp,newp,day):
 # Invariants for pools (monthly snapshots, ~65-month sliding window, one key per calendar month):
 #  1) past-month snapshots are byte-frozen (L/M/S/U_list lists must not change);
 #  2) the CURRENT month may re-key (refresh date moves, e.g. 2026-10-09 -> 2026-10-12) and recompute freely;
 #  3) a full window may evict months ONLY as a contiguous prefix from the OLDEST end, paired 1:1 with new months.
 cur=day[:7]
 ymo={k[:7]:k for k in oldp}; ymn={k[:7]:k for k in newp}
 lost=[m for m in sorted(ymo) if m not in ymn and m!=cur]
 added=[m for m in sorted(ymn) if m not in ymo and m!=cur]
 if lost:
  if sorted(ymo)[:len(lost)]!=lost or len(added)!=len(lost):
   raise SystemExit(f'HISTORY LOST in l3_pool: months {lost} vanished (not oldest-end window eviction; added={added}) — aborting (backup: data/cd/sector_axes/backup_*)')
 for m,k in sorted(ymo.items()):
  if m==cur or m not in ymn: continue
  if json.dumps(oldp[k],sort_keys=True)!=json.dumps(newp[ymn[m]],sort_keys=True):
   raise SystemExit(f'HISTORY LOST in l3_pool: past-month snapshot {m} mutated — aborting (backup: data/cd/sector_axes/backup_*)')

def tdx_has_day(day):
 import struct
 p=Path('/root/tdx_data/vipdoc/sz/lday/sz000001.day')
 b=p.read_bytes(); return any(struct.unpack('<I',b[i*32:i*32+4])[0]==int(day.replace('-','')) for i in range(len(b)//32-3,len(b)//32))

def run(step,cmd):
 t0=time.time()
 r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
 el=time.time()-t0; ok=r.returncode==0
 # 2026-10-21: 退出码/信号必须留痕 — 进程被 SIGKILL/段错误带走时 stderr 为空，
 # 只看 OK/FAIL 会误判成「静默退 1」（本次 5 只科创票事故的排障盲区）
 sig=f' signal={-r.returncode}' if r.returncode<0 else ''
 print(f'[{step}] {"OK" if ok else "FAIL"} {el:.0f}s rc={r.returncode}{sig}',flush=True)
 (OUTD/f'step_{step}.log').write_text(f'# cmd={" ".join(cmd)}\n# rc={r.returncode}{sig} elapsed={el:.0f}s\n'+r.stdout[-20000:]+r.stderr[-8000:])
 return ok

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--day',required=True)
 ap.add_argument('--skip',default='',help='comma list of A,C,E,F')
 a=ap.parse_args(); skip=set(a.skip.split(','))
 OUTD.mkdir(parents=True,exist_ok=True)
 # 2026-10-21: 单实例锁 — 防两个 daily_update/daily_price_update 并发抢写同一批 json.gz
 # （并发曾导致 A 步 ~3800/5430 中途 FAIL、C1 被连带杀；也被老刘称为「拥堵」）
 lk=open('/tmp/r2_daily_update.lock','w')
 try: fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except OSError: raise SystemExit('另一个 daily_update 正在运行（锁 /tmp/r2_daily_update.lock）——拒绝并发，避免抢写')
 day=a.day
 if not tdx_has_day(day): raise SystemExit(f'TDX mirror has no bars for {day} — sync not done?')
 # snapshot axes for subset-equality check
 old={}
 l1rows=rows_of(ROOT/ARTS['l1_market_axes']) if (ROOT/ARTS['l1_market_axes']).exists() else []
 dts=sorted({r['date'] for r in l1rows if r['date']<a.day})
 prev_day=dts[-1] if dts else a.day
 for k,rel in ARTS.items():
  p=ROOT/rel
  if p.exists():
   if k=='l3_pool': old[k]=json.loads(gzip.decompress(p.read_bytes())).get('pools',{})
   else: old[k]={json.dumps(r,sort_keys=True) for r in rows_of(p)}
 if 'A' not in skip:
  if not run('A',[PY,'src/r2/daily_price_update.py','--day',day]): raise SystemExit('A failed')
 if 'C' not in skip:
  bk=ROOT/'data/cd/sector_axes'/f'backup_{a.day.replace("-","")}'
  bk.mkdir(parents=True,exist_ok=True)
  for rel in ARTS.values():
   src=ROOT/rel
   if src.exists(): shutil.copy(src,bk/src.name)
  for tag,script in BUILDERS:
   if not run(tag,[PY,script]): raise SystemExit(f'{tag} failed')
  for k,rel in ARTS.items():
   if k=='l3_pool':
    newp=json.loads(gzip.decompress((ROOT/rel).read_bytes())).get('pools',{})
    check_l3_pool(old.get(k,{}),newp,a.day)
    continue
   newr=rows_of(ROOT/rel)
   if k=='l2_state_table':
    check_l2_state(old.get(k,set()),newr,{a.day,prev_day},a.day)   # 2026-10-21: 标签迁移容忍(有界+WARN)，身份丢失仍中断
    continue
   if k in KEYED:
    kf=KEYED[k]; lost={kf(json.loads(x)) for x in old[k]}-{kf(r) for r in newr}
    kind='keys'
   else:
    # P1 fix 2026-10-09: 近2交易日行允许重算(TDX盘后补齐/迟到bar)——早于昨日的历史仍逐字节严查
    recent={a.day,prev_day}
    olds={x for x in old[k] if json.loads(x).get('date') not in recent}
    lost=olds-{json.dumps(r,sort_keys=True) for r in newr if r.get('date') not in recent}; kind='rows'
    if lost: lost=rows_tolerance_pass(lost,newr,recent,MASKED_FIELDS.get(k,frozenset()))   # P2 2026-10-13: rebase micro-perturbation tolerance
   if lost: raise SystemExit(f'HISTORY LOST in {k}: {len(lost)} {kind} vanished — aborting (backup: data/cd/sector_axes/backup_*)')
 if 'E' not in skip:
  if not run('E',[PY,'src/r2/current_scan.py']): raise SystemExit('E failed')
 if 'F' not in skip:
  if not run('F',[PY,'src/r2/daily_report.py','--day',day]): raise SystemExit('F failed')
 print('DAILY UPDATE COMPLETE',day)
if __name__=='__main__':main()
