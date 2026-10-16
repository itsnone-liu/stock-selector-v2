#!/usr/bin/env python3
"""R5 OOS-B daily increment (Pipeline A). Run AFTER ~19:30 CST on trading days.
Steps: 1) TDX 052d incremental 5m + raw daily for 84 frozen stocks;
2) qfq close from the existing daily_fullmarket layer (missing => fail closed), and
   the same R4 contract validation (48 bars, Σ5m/daily amount∈[0.95,1.05]);
3) append new shadow_daily rows (same formulas as backfill; matured cols=null);
4) append maturity records when lambda_next_5/20 become computable;
5) append-only: existing lines NEVER modified. Fail-closed per stock/day.
Pure stdlib acquisition; no baostock/akshare runtime dependency."""
import gzip,json,math,statistics,sys,os,signal,datetime
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from stock_selector.data.tdx_r4 import fetch_r4_days
M5=ROOT/'data/cl_radar/r4_opening/per_stock'
DAILY=ROOT/'data/cd/daily_fullmarket'
DA=ROOT/'data/cl_radar/r4_opening/daily_amounts';DA.mkdir(parents=True,exist_ok=True)
SHADOW=ROOT/'data/cl_radar/opening_impact_state/shadow_daily.jsonl.gz'
MAT=ROOT/'data/cl_radar/opening_impact_state/maturity_updates.jsonl.gz'
EPS=ROOT/'data/cd/l4_episodes.json.gz';SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
FREEZE='2026-10-14'
def load_jsonl_gz(p):
    return [json.loads(l) for l in gzip.open(p,'rt')] if p.exists() else []
def lam5(bars,lo,hi,prev_close=None):
    seg=[b for b in bars if lo<b[0]<=hi]
    if not seg:return None,None
    pc=prev_close if prev_close is not None else seg[0][4]
    if pc is None or pc<=0:return None,None
    n=d=0.0
    for b in seg:
        dc=b[4]-pc
        of=0.0 if(abs(b[2]-b[3])<1e-9 and b[2]>0) else b[6]*(1 if dc>0 else -1 if dc<0 else 0)
        n+=of*dc;d+=of*of;pc=b[4]
    return (n/d if d>0 else None),seg[0][4]
def _alarm_handler(signum, frame):
    raise TimeoutError('TDX stock operation timeout')
def timed(call, seconds):
    signal.signal(signal.SIGALRM,_alarm_handler); signal.alarm(seconds)
    try: return call()
    except TimeoutError: return None
    finally: signal.alarm(0)
def load_daily_contract(six):
    """Return frozen/current daily rows without any remote fallback."""
    dp=DAILY/f'{six}.json.gz';ep=ROOT/'data/r2/market_ext'/f'{six}.json'
    if not dp.exists():return {}
    rec=json.load(gzip.open(dp,'rt'))
    ext={r['date']:r for r in json.load(open(ep))['rows']} if ep.exists() else {}
    q={r[0]:r for r in rec.get('qfq',[])};u={r[0]:r for r in rec.get('unadj',[])}
    out={}
    for d in rec.get('dates',[]):
        if d in q and d in u:
            amount=float(ext.get(d,{}).get('amount') or 0)
            out[d]={'amount':amount,'close':float(u[d][2]),'qfq':float(q[d][2]),
                    'qhigh':float(q[d][3]),'qlow':float(q[d][4])}
    return out
def main():
    cs=[r['code'] for g in json.load(open(SAMPLE))['groups'].values() for r in g['chosen']]
    off=int(os.environ.get('R5B_OFFSET','0')); lim=os.environ.get('R5B_LIMIT')
    cs=cs[off:off+int(lim)] if lim else cs[off:]
    shadow=load_jsonl_gz(SHADOW)
    last_global=max(r['date'] for r in shadow)
    eps=json.load(gzip.open(EPS,'rt'))['episodes']
    epset=defaultdict(list)
    for e in eps:epset[e['stock']].append((e['start'],e['end']))
    new_rows=[];pending=[];n_new_days=0;stats={'stocks':0,'no_new_trade_day':0,'query_failed':0,'new_rows':0}
    try:
        per_stock_timeout=int(os.environ.get('R5B_STOCK_TIMEOUT','45'))
        tdx_host=os.environ.get('TDX_HOST') or None
        for code in cs:
            stats['stocks']+=1
            signal.signal(signal.SIGALRM,_alarm_handler);signal.alarm(per_stock_timeout)
            six=code.split('.')[1];m5p=M5/f'{six}.json.gz'
            m=json.load(gzip.open(m5p,'rt')) if m5p.exists() else None
            if not m or not m.get('dates'):continue
            contract=load_daily_contract(six)
            if not contract:stats['query_failed']+=1;continue
            dap=DA/f'{six}.json.gz'
            dstore=json.load(gzip.open(dap,'rt')) if dap.exists() else {'dates':[],'amount':[],'close':[],'qfq':[]}
            last_m5=m['dates'][-1]
            if len(dstore['dates'])<20:
                have=set(dstore['dates'])
                for dd in sorted(d for d in contract if d<=last_m5)[-35:]:
                    if dd not in have:
                        row=contract[dd];dstore['dates'].append(dd);dstore['close'].append(row['close']);dstore['amount'].append(row['amount']);dstore['qfq'].append(row['qfq'])
            hist_d=dict(zip(m['dates'],m['bars']))
            through=max(contract)
            if through<=last_m5:stats['no_new_trade_day']+=1;continue
            got=fetch_r4_days(code,last_m5,through,DAILY/f'{six}.json.gz',host=tdx_host)
            if not got:stats['query_failed']+=1;continue
            oam_hist=[sum(b[6] for b in hist_d[d] if '0935'<=b[0]<='1000') for d in m['dates']]
            prev_close=dstore['close'][-1] if dstore['close'] else None
            for d in sorted(got):
                bd,amt,uc,qc,source_id=got[d]
                m['dates'].append(d);m['bars'].append(bd)
                dstore['dates'].append(d);dstore['amount'].append(amt);dstore['close'].append(uc);dstore['qfq'].append(qc)
                oam=sum(b[6] for b in bd if '0935'<=b[0]<='1000');oam_hist.append(oam)
                prev20=[a for a in oam_hist[:-1] if a>0][-20:];adv=dstore['amount'][-21:-1]
                if len(prev20)<20 or len(adv)<20 or any(a<=0 for a in adv) or prev_close is None or prev_close<=0:prev_close=uc;continue
                base=statistics.fmean(prev20);advv=statistics.fmean(adv)
                lam_o,fc=lam5(bd,'0930','1000',prev_close=prev_close);lam_post,_=lam5(bd,'1000','1500')
                c10=[b[4] for b in bd if b[0]=='1000'];oc=[b[4] for b in bd if '0935'<=b[0]<='1000'];pe=None
                if len(oc)>=2:
                    net=abs(oc[-1]-oc[0]);path=sum(abs(oc[i+1]-oc[i]) for i in range(len(oc)-1));pe=net/path if path>0 else None
                if lam_o is None or lam_post is None or not c10 or base<=0 or oam<=0:prev_close=uc;continue
                ep=1 if any(s<=d<=t for s,t in epset.get(six,())) else 0
                row={'code':code,'date':d,'in_model_period':d<=FREEZE,'source_id':source_id,
                     'opening_amount':oam,'expected_opening_amount':base,'expected_daily_amount_adv20':advv,
                     'e_open':math.log(oam/base),'share_open_pit':oam/advv,'opening_return':c10[0]/prev_close-1,
                     'opening_path_efficiency':pe,'lambda_open':lam_o,
                     'lambda_open_dim':lam_o*advv/float(dstore['qfq'][-2] if len(dstore['qfq'])>1 else qc),
                     'episode_state':ep,'daily_amount':amt,'daily_effort':math.log(amt/advv),
                     'opening_share_actual':oam/amt if amt>0 else None,'post_open_lambda':lam_post,
                     'post_open_lambda_dim':lam_post*advv/qc,'close_retention':uc/c10[0]-1,
                     'lambda_next_5':None,'lambda_next_20':None}
                new_rows.append(row);n_new_days+=1;prev_close=uc
            pending.append((m5p,m,dap,dstore))
        signal.alarm(0)
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
    have={(r['code'],r['date']) for r in shadow}
    kept=[r for r in new_rows if (r['code'],r['date']) not in have]
    stats['dup_skipped']=len(new_rows)-len(kept)
    new_rows=kept
    if new_rows:
        with gzip.open(SHADOW,'at') as f:
            for r in new_rows:f.write(json.dumps(r,separators=(',',':'))+'\n')
    # Per-stock M5/DA caches flush ONLY AFTER the permanent shadow rows land.
    # Old order (caches first, shadow at shard end) is what produced the 19 permanent
    # shadow holes on 2026-10-16: a kill/timeout mid-shard advanced the watermark but
    # dropped the rows, so the next run saw no_new_trade_day and never refetched them.
    # Now a crash only loses cache progress (refetched next run; dedup keeps shadow unique).
    for m5p,m,dap,dstore in pending:
        with gzip.open(m5p,'wt') as f:json.dump(m,f)
        with gzip.open(dap,'wt') as f:json.dump(dstore,f)
    stats['new_rows']=len(new_rows)
    # Maturity backfill: lambda_next_5/20 for shadow rows whose forward window now exists.
    mat_have={(r['code'],r['date']) for r in load_jsonl_gz(MAT)}
    all_rows=shadow+new_rows
    mat_new=[]
    try:
        mat_to=int(os.environ.get('R5B_STOCK_TIMEOUT','45'))
        by_stock=defaultdict(list)
        for r in all_rows: by_stock[r['code']].append(r['date'])
        for code,dates in by_stock.items():
          # 每股独立计时 + finally 清零：既防单股挂死，也防前一阶段的计时器漏到这里
          # （旧行为：主循环遗留的 alarm 在 maturity 中途触发 → TimeoutError 被下面
          #  的 except 吞掉 → maturity 当轮静默截断，只写进一部分，无任何日志报警）。
          signal.signal(signal.SIGALRM,_alarm_handler);signal.alarm(mat_to)
          try:
            # only rows whose maturity was NOT already written into shadow by the backfill
            dates=[r['date'] for r in all_rows if r['code']==code and r.get('lambda_next_20') is None]
            six=code.split('.')[1]
            dap=DA/f'{six}.json.gz'
            if not dap.exists():continue
            dstore=json.load(gzip.open(dap,'rt'))
            dd=dstore['dates'];amts=dict(zip(dd,dstore['amount']))
            need_dates=[d for d in dates if (code,d) not in mat_have]
            if not need_dates:continue
            span_lo=min(need_dates);contract=load_daily_contract(six)
            qlist=[(d,contract[d]['qfq'],contract[d]['qhigh'],contract[d]['qlow'])
                   for d in dd if d>=span_lo and d in contract]
            if len(qlist)<2:continue
            qpos={row[0]:i for i,row in enumerate(qlist)}
            for d in need_dates:
                if d not in qpos:continue
                j=qpos[d]
                for w,key in ((5,'lambda_next_5'),(20,'lambda_next_20')):
                    if j+w>=len(qlist):continue
                    ln=ld=0.0
                    for k in range(j+1,j+w+1):
                        dc=qlist[k][1]-qlist[k-1][1]
                        of=0.0 if (qlist[k][2]==qlist[k][3] and qlist[k][2]>0) else amts.get(qlist[k][0],0.0)*(1 if dc>0 else -1 if dc<0 else 0)
                        ln+=of*dc;ld+=of*of
                    if ld>0 and (code,d) not in mat_have:
                        mat_have.add((code,d))
                        mat_new.append({'code':code,'date':d,key:ln/ld})
          except TimeoutError:
            stats['maturity_timeout']=stats.get('maturity_timeout',0)+1
            print(f'MATURITY_TIMEOUT {code} (>{mat_to}s, 当轮跳过, 下次运行续算)',flush=True)
          finally:
            signal.alarm(0)
    except Exception:
        import traceback;traceback.print_exc()
    if mat_new:
        with gzip.open(MAT,'at') as f:
            for r in mat_new:f.write(json.dumps(r,separators=(',',':'))+'\n')
    stats['maturity_new']=len(mat_new)
    print(f'APPEND rows={len(new_rows)} new_days={n_new_days} shadow_last={last_global}->'+(new_rows[-1]["date"] if new_rows else last_global))
    print('STATS '+json.dumps(stats,separators=(',',':')))
if __name__=='__main__':main()
