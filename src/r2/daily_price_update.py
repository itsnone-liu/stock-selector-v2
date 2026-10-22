#!/usr/bin/env python3
"""R2-DU(A): daily incremental price update for data/cd/daily_fullmarket.

Per stock: append-only extension from the **TDX 通道**（老刘逆向 tdx-protocol；复权基准
cat1-affine-c2，与真客户端逐 bar 一致。2026-10-21 起腾讯/新浪/东财退役），
交叉校验本机 TDX 镜像 (/root/tdx_data)。
Fail-closed: any mismatch skips the stock and is reported explicitly.
停牌占位根口径（2026-10-22 定）：TDX 对「当日无成交」（停牌/退市整理）的票会给一根
O=H=L=C=前收、量=0 的占位根，且不留历史占位根；占位根零信息量，写成存量会把 last 推到次日
就落在窗口外的日期（每日复发 window_too_short）。故：① 当日根为占位 → 归良性桶 tdx_no_daily
（已登记桶，不新增口径、不计 hard_fail、不写盘）；② 存量尾部已有的占位根在落盘时剥除。
--source tencent 保留旧腾讯 fqkline 路径作应急回退（默认 tdx）。

Usage:
  daily_price_update.py --day 2026-10-08 [--limit 20] [--shard i/n]
Manifest: data/r2/daily_update/update_<day>.json
"""
from __future__ import annotations
import argparse,gzip,json,os,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
# r2.* 导入引导：脚本直跑时 sys.path[0]=src/r2，`import r2.tdx_client` 会 ModuleNotFoundError
# （cron/编排器 subprocess 环境同样无 PYTHONPATH）。缺此引导 → 全票失败但退出码 0 = 假 OK。
if str(ROOT/'src') not in sys.path:
 sys.path.insert(0,str(ROOT/'src'))
DAILY=ROOT/'data/cd/daily_fullmarket'; TDX=Path('/root/tdx_data/vipdoc')
OUTD=ROOT/'data/r2/daily_update'
# 主域 proxy.finance.qq.com 会把本机 IP 拉进 WAF 封禁（501 跳转页，惩罚升级型）；
# 备用域 web.ifzq.gtimg.cn 响应逐字节兼容但同样会封（2026-10-20 实测，两域惩罚独立计时）。
# 默认备用域；可用环境变量 TDX_KLINE_URL 临时切主域（如 A 步 cron 探测后选择）。
URL=os.getenv('TDX_KLINE_URL','https://web.ifzq.gtimg.cn/appstock/app/fqkline/get')
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64)'}
try:
 import requests
except ImportError:
 os.system(f'{sys.executable} -m pip install -q requests'); import requests

def tx_full(c):
 return ('sh'+c) if c.startswith(('6','9')) else (('bj'+c) if c.startswith(('4','8')) else 'sz'+c)

def tdx_path(c):
 mkt='sh' if c[0] in '69' else ('bj' if c[0] in '48' else 'sz')
 return TDX/mkt/'lday'/f'{mkt}{c}.day'

_tdx_cache:dict[str,dict]={}
def tdx_closes(c):
 if c in _tdx_cache: return _tdx_cache[c]
 p=tdx_path(c)
 m={}
 if p.exists():
  b=p.read_bytes()
  for i in range(len(b)//32):
   d,o,h,l,cl,amt,vol,_r=struct.unpack('<IIIIIfII',b[i*32:(i+1)*32])  # vol=uint32（原写 'f' 会丢 >2^24 的尾数）
   m[str(d)]=(cl/100,vol/100)
 _tdx_cache[c]=m
 return m

_tdx_sess=None; _tdx_host=None
def tdx_session():
 """全市场共用一条 TDX 连接：with_session 每次调用都新建 socket（含 284B bootstrap 握手），
 逐票调用会开上万条连接，故此处持久复用，传输失败时重连一次。"""
 global _tdx_sess,_tdx_host
 if _tdx_sess is not None: return _tdx_sess
 from r2.tdx_client import Session,DEFAULT_HOSTS
 errs=[]
 for ep in DEFAULT_HOSTS:
  h,_,pt=ep.partition(':'); pt=int(pt or 7709)
  try:
   _tdx_sess=Session(h,pt); _tdx_host=ep
   return _tdx_sess
  except (OSError,ConnectionError,ValueError) as e:
   errs.append(f'{ep}:{type(e).__name__}'); _tdx_sess=None
 raise ConnectionError('tdx no host: '+', '.join(errs))

def tdx_reset():
 global _tdx_sess,_tdx_host
 try:
  if _tdx_sess: _tdx_sess.close()
 except Exception: pass
 _tdx_sess=None; _tdx_host=None

def _ph_bar(b):
 """停牌占位根判定（TDX bar 形态）：当日无成交 → O=H=L=C=前收 且量≈0。
 注意：量 0 在协议线上被反解成非规格化 float32（实测 5.877471754111438e-39，==0 为 False），
 故用绝对阈值 1e-6 判零；真实最小成交 1 手远高于此，不会误判一字板。"""
 return abs(b['volume_hand'])<1e-6 and b['open']==b['high']==b['low']==b['close']

def _ph_row(row):
 """停牌占位根判定（存量 row 形态 [date,open,close,high,low,volume]）。见 tdx_seg/update_stock 注。"""
 if not row or len(row)<6: return False
 try:
  o,c,h,l,v=float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5])
 except (TypeError,ValueError): return False
 return abs(v)<1e-6 and o==h==l==c

def _write(d,p):
 d['fetched_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ')
 tmp=p.with_suffix('.tmp.gz')
 tmp.write_bytes(gzip.compress(json.dumps(d,ensure_ascii=False).encode()))
 os.replace(tmp,p)

def tdx_seg(code,last,day,count=800,stored_last=None):
 """TDX 通道取 bar 窗口，输出与旧腾讯 fqkline 完全同构的 row：[date, open, close, high, low, volume]。

 实测映射：裸价 open/close/high/low 逐字段相同（.3f）；qfq 行走客户端 cat1-affine-c2
（与真客户端逐 bar 0.00000% 一致，抽样 40 票 qfq 水位 39/40 同日相等）。
 成交量单位存量不一致：主板/创业板存量=手（TDX volume_hand/100 取整），
 **科创板 688 存量=股**（TDX 原值）。故这里用存量最后一行做单位自校准，
 两种都对不上则 fail-closed，避免把单位搞错写进历史。
 返回 (seg, err)；err 非空 = fail-closed 原因。"""
 mkt=1 if code[0] in '69' else 0
 deg=''
 for attempt in (0,1):
  try:
   s=tdx_session()
   raw=s.daily(mkt,code,count=count)
   try:
    q=s.qfq_daily(mkt,code,count,day)
   except ValueError as e:
    # 老刘口径(2026-10-21)：个别事件无法精确复权时不纠结算术差，直接退化用现价（裸价），
    # 只要涨跌大趋势不变即可，分析风险由人工判断。仅当完全取不到日线时才 fail-closed。
    if 'unverified special category' in str(e): q=None; deg='rawfallback'
    elif 'daily baseline unavailable' in str(e):
     # 停牌/已退市/未覆盖：TDX 对该码返回 0 根 <=day 的日线 bar（如实测 000004 停牌于
     # 2026-07-13、000005 退市于 2024-03）。属良性跳过，不计入失败告警（否则每日固定假报错）。
     return None,'tdx_no_daily'
    else: raise
   break
  except (OSError,ConnectionError) as e:
   tdx_reset()
   if attempt==1: return None,f'tdx_transport:{type(e).__name__}'
  except Exception as e:
   return None,f'tdx_err:{type(e).__name__}:{e}'
 _rbar={b['date']:b for b in raw if b['date']<=day}
 # 当日停牌占位根（2026-10-22）：TDX 对当日无成交（停牌/退市整理）的票给一根
 # O=H=L=C=前收、量=0 的占位根，且**不留历史占位根**（只给查询当日一根）。占位根零信息量，
 # 写进存量会把 last 推到「次日就不在窗口里」的日期 → 每天必发 window_too_short（10-21 实测
 # 8 票复发、且会随停牌票增多扩散）。归入已登记的良性桶 tdx_no_daily（= 该码当日无有效日线），
 # 不新增桶名、不计 hard_fail。
 if _rbar and max(_rbar)==day and _ph_bar(_rbar[day]): return None,'tdx_no_daily'
 if q is None:
  _qbar={b['date']:b for b in raw if b['date']<=day}
 elif q.get('returned_count',0)<2: return None,'tdx_short_history'  # complete_history 恒为 False，改判覆盖度
 else:
  _qbar={r['date']:r for r in q['rows'] if r['date']<=day}
 if last not in _rbar or last not in _qbar: return None,'window_too_short'
 vol_div=100
 if stored_last and len(stored_last)>5:
  vh=_qbar[last]['volume_hand']; sv=float(stored_last[5])
  # 存量成交量与 TDX 存在「末位 1 手」进位口径差（实测 47104.5→47105、363566.48→363567、
  # 61622.5→61623，非单纯 round），故「手」口径容差 ±1 手。
  # 科创板 688 存量为股：协议线上的量本身是 float32 编码（pytdx get_volume 按指数+尾数重组），
  # 量 >2^24 尾数即失真（实测 688126 42138086→42138088、688825 432227162→432227168），
  # 「股」口径容差须按 2^-24 精度给；否则这批高量科创票会误落 volguess→按手写盘→接缝校验
  # 不匹配→永久卡死（2026-10-21 修，5 只硬错即此因）。
  if abs(round(vh/100)-sv)<=1: vol_div=100
  elif abs(round(vh)-sv)<=2*max(abs(vh),abs(sv))*2**-24+2: vol_div=1
  else: vol_div=100; deg=(deg+'+volguess') if deg else 'volguess'  # 兜底按手，显式标注
 def mk(b):
  return [b['date'],f"{b['open']:.3f}",f"{b['close']:.3f}",f"{b['high']:.3f}",
          f"{b['low']:.3f}",f"{round(b['volume_hand']/vol_div):.3f}"]
 return {'_r':{d:mk(b) for d,b in _rbar.items()},
         '_q':{d:mk(b) for d,b in _qbar.items()},'_vol_div':vol_div,'_deg':deg},None

def fetch(sess,full,last,day,back=7):
 """Return {date: (raw_row, qfq_row)} for one small window. end is exclusive (v3 convention).

 back: widen window start N days before `last`. Tencent's fqkline endpoint is cached
 per-param (TAPISIX); the shard keyed by start==last can still serve yesterday's qfq
 while a slightly wider window already returns the current day (observed 2026-10-14:
 start==last hit a stale shard, start=last-3d was fresh). Widening is otherwise a
 no-op -- update_stock only consumes rows > last.
 """
 import datetime as dt
 end=(dt.date.fromisoformat(day)+dt.timedelta(days=1)).isoformat()
 start=(dt.date.fromisoformat(last)-dt.timedelta(days=back)).isoformat()
 out={}
 for fq in ('','qfq'):
  field='qfqday' if fq else 'day'
  r=None
  for attempt in range(3):
   try:
    resp=sess.get(URL,params={'param':f'{full},day,{start},{end},640,{fq}'},timeout=12,headers=UA)
    j=resp.json()['data'][full]
    r=j.get(field) or j.get('day')
    break
   except Exception:
    if attempt==2: return None
    time.sleep(15)
  if r is None: r=[]
  m={row[0]:row for row in r}
  if fq:
   out['_q']=m
  else:
   out['_r']=m
  time.sleep(0.35)
 return out if '_r' in out and '_q' in out else None

def _rowmatch(a,b):
 """接缝比对：date/open/close/high/low 严格同构；volume 容差=float32 相对精度+1 手进位。
 TDX 协议线上的量是 float32 编码（pytdx get_volume 指数+尾数重组），量>2^24 时尾数失真
 （实测 42138086→42138088、432227162→432227168，差 2~8），故按 2*max*2^-24+1 判，单位错 100 倍仍会拦住。"""
 if a[:5]!=b[:5]: return False
 try:
  x=float(a[5]); y=float(b[5])
  return abs(x-y)<=2*max(abs(x),abs(y))*2**-24+1
 except (TypeError,ValueError): return a[5]==b[5]

def update_stock(sess,code,day,strict_tdx=True,source='tdx'):
 p=DAILY/f'{code}.json.gz'
 d=json.loads(gzip.decompress(p.read_bytes()))
 # 停牌占位根清理（2026-10-22）：存量末根若是占位根（量 0、四价相等，10-21 切 TDX 后误写），
 # 它是假数据且会让 last 停在「次日窗口外」的日期 → 每日复发 window_too_short。先只在内存里剥掉；
 # 仅当本次真的落盘（有新增真根 / 良性停牌修订）才写回。
 nph=0
 while len(d['dates'])>1 and _ph_row(d['unadj'][-1]):
  d['dates'].pop(); d['unadj'].pop(); d['qfq'].pop()
  af=d.get('adjust_factor_model_derived')
  if isinstance(af,list) and len(af)>len(d['dates']): af.pop()
  nph+=1
 last=d['dates'][-1]
 if nph: print(f'[{code}] trim 停牌占位根 {nph} 根 → 真根 {last}',flush=True)
 if last>=day:
  if nph: _write(d,p)
  return ('current',0)
 if source=='tdx':
  seg,err=tdx_seg(code,last,day,stored_last=d['unadj'][-1])
  if err=='tdx_no_daily':
   if nph: _write(d,p)          # 当日无成交：只修假根，不新增根；桶仍计入良性 tdx_no_daily
   return (err,0)
  if err: return (err,0)
  raw,qm=seg['_r'],seg['_q']
 else:
  seg=fetch(sess,tx_full(code),last,day)
  if seg is None: return ('fetch_fail',0)
  raw,qm=seg['_r'],seg['_q']
  if last not in raw or last not in qm:
   seg=fetch(sess,tx_full(code),last,day,back=0)  # widened window missed: retry original
   if seg is None: return ('fetch_fail',0)
   raw,qm=seg['_r'],seg['_q']
 if last not in raw or last not in qm: return ('overlap_missing',0)
 deg=seg.get('_deg','') if source=='tdx' else ''
 if not _rowmatch(raw[last],d['unadj'][-1]): return ('overlap_raw_mismatch',0)
 seam='' if _rowmatch(qm[last],d['qfq'][-1]) else 'seam'
 nds=sorted(x for x in raw if x>last and x in qm)
 tdx=tdx_closes(code); mism=[]
 for dt_ in nds:
  t=tdx.get(dt_.replace('-',''))
  tc=float(raw[dt_][2])
  if t is None:
   # 当日 bar 的镜像滞后豁免：tdx 主源已是服务器端，本机镜像通常只到 T-1（A 步在收盘后跑，
   # 镜像是否含当日取决于同步顺序）。仅豁免 dt_==day，其余日期缺 bar 仍从严判 mismatch。
   if dt_!=day: mism.append((dt_,'no_tdx_bar'))
   continue
  if abs(t[0]-tc)>0.011: mism.append((dt_,f'close {tc} vs tdx {t[0]}'))
 # bars present in TDX window but not returned by tencent (non-suspension)
 for k in tdx:
  ks=f'{k[:4]}-{k[4:6]}-{k[6:]}'
  if last<ks<=day and ks not in nds: mism.append((ks,'tdx_bar_not_fetched'))
 if mism and strict_tdx: return ('tdx_mismatch',mism)
 if not nds:
  if nph: _write(d,p)
  return ('no_change',0)
 newu=[raw[x][:6] for x in nds]; newq=[qm[x][:6] for x in nds]
 newf=[round(float(qm[x][2])/float(raw[x][2]),6) if float(raw[x][2]) else 1.0 for x in nds]
 d['dates']+=nds; d['unadj']+=newu; d['qfq']+=newq
 d.setdefault('adjust_factor_model_derived',[])
 if len(d['adjust_factor_model_derived'])==len(d['dates'])-len(nds):
  d['adjust_factor_model_derived']+=newf
 _write(d,p)
 return ('updated'+('_'+deg if deg else '')+('_'+seam if seam else ''),len(nds))

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--day',required=True); ap.add_argument('--limit',type=int,default=0)
 ap.add_argument('--shard',default='')
 ap.add_argument('--codes',default='',help='逗号分隔的指定票（定向修复用；留空=全量）')
 ap.add_argument('--source',default='tdx',choices=('tdx','tencent'),
                 help='行情源：tdx=老刘逆向通达信通道（默认），tencent=旧腾讯 fqkline 应急回退')
 ap.add_argument('--max-fail-ratio',type=float,default=0.02,
                 help='硬失败闸门：硬失败数 > max(20, ratio*票数) 时退出码 1（默认 2%%）。'
                      '停牌/退市(tdx_no_daily)属良性，不计入。')
 a=ap.parse_args()
 codes=sorted(p.name[:-8] for p in DAILY.glob('*.json.gz'))
 if a.shard: i,n=map(int,a.shard.split('/')); codes=[c for k,c in enumerate(codes) if k%n==i]
 if a.limit: codes=codes[:a.limit]
 if a.codes: codes=[c.strip() for c in a.codes.split(',') if c.strip()]  # 定向修复：只跑指定票
 day=a.day; sess=requests.Session()
 # 2026-10-21: 单实例锁 — 两个 A 步并发会抢写同一批 json.gz（曾致 3800/5430 中途 FAIL）。
 # 定向修复(--codes)同样受锁保护；锁随进程退出自动释放。
 import fcntl
 _lk=open('/tmp/r2_daily_price_update.lock','w')
 try: fcntl.flock(_lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except OSError: raise SystemExit('另一个 daily_price_update 正在运行（锁 /tmp/r2_daily_price_update.lock）——拒绝并发写盘')
 stats={}; fails=[]; mism=[]; susp=[]; nbars=0
 OUTD.mkdir(parents=True,exist_ok=True)
 t0=time.time()
 for i,code in enumerate(codes):
  st,extra=update_stock(sess,code,day,source=a.source)
  stats[st]=stats.get(st,0)+1
  if st.split('_')[0]=='updated' or st in ('no_change','current'): nbars+= extra if isinstance(extra,int) else 0
  elif st=='tdx_no_daily': susp.append(code)          # 停牌/退市：良性跳过
  elif st=='fetch_fail': fails.append((code,st,None))
  else: mism.append((code,st,None))
  if (i+1)%200==0: print(f'{i+1}/{len(codes)} elapsed {time.time()-t0:.0f}s {stats}',flush=True)
  time.sleep(0.0 if a.source=='tdx' else 0.15)  # TDX 单连接无 HTTP 限流，无需节流
 hard=len(fails)+len(mism)
 limit=max(20,int(len(codes)*a.max_fail_ratio))
 ok=hard<=limit and bool(codes)
 man={'day':day,'source':a.source,'n_codes':len(codes),'stats':stats,'new_bars':nbars,'elapsed_s':round(time.time()-t0),
     'suspended_benign':len(susp),'suspended_codes':susp[:500],
     'hard_fail':hard,'gate_limit':limit,'ok':ok,
     'fails':fails[:500],'tdx_mismatch':mism[:500],'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ')}
 (OUTD/f'update_{day}.json').write_text(json.dumps(man,ensure_ascii=False,indent=1))
 print(json.dumps({k:man[k] for k in ('day','n_codes','stats','new_bars','elapsed_s','suspended_benign','hard_fail','gate_limit','ok')},ensure_ascii=False))
 # 闸门（2026-10-21 修）：旧版无论如何都退 0 → 全票 ModuleNotFoundError 也被编排器判 "[A] OK"（假 OK）。
 if not ok:
  print(f'[A] GATE TRIPPED: hard_fail={hard} > limit={limit} '
        f'(benign suspended={len(susp)}); see {OUTD}/update_{day}.json',file=sys.stderr)
  sys.exit(1)
if __name__=='__main__': main()
