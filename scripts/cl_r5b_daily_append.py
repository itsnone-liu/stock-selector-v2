#!/usr/bin/env python3
"""R5 OOS-B daily increment (Pipeline A). Run AFTER ~19:30 CST on trading days.
Steps: 1) incremental baostock 5m + daily fetch for 84 frozen stocks (dates > last stored);
2) same contract validation as R4 (48 bars, Σ5m/daily amount∈[0.95,1.05]);
3) append new shadow_daily rows (same formulas as backfill; matured cols=null);
4) append maturity records when lambda_next_5/20 become computable;
5) append-only: existing lines NEVER modified. Fail-closed per stock/day.
Env: PYTHONPATH=/tmp/bspy (baostock needs pandas 2.3.x)."""
import gzip,json,math,statistics,sys,os,signal,datetime
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
M5=ROOT/'data/cl_radar/r4_opening/per_stock'
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
def query_retry(bs, code, fields, start_date, end_date, frequency, adjustflag, attempts=3):
    import time
    for attempt in range(attempts):
        try:
            rs=bs.query_history_k_data_plus(code,fields,start_date=start_date,end_date=end_date,frequency=frequency,adjustflag=adjustflag)
            if rs.error_code!='0':
                print(f'QUERY_FAIL {code} {start_date}:{end_date} {rs.error_msg[:80]}',flush=True)
                time.sleep(3+3*attempt);continue
            rows=[]
            while rs.next(): rows.append(rs.get_row_data())
            return rows
        except Exception as exc:
            print(f'QUERY_RETRY {code} {start_date}:{end_date} {type(exc).__name__}',flush=True)
            time.sleep(3+3*attempt)
    return None

def fetch_stock(bs,code,dates_needed):
    """returns {date: (bars48, amount, unadj_close, qfq_close)} for OK days"""
    out={}
    raw=query_retry(bs,code,'date,time,open,high,low,close,volume,amount',dates_needed[0],dates_needed[-1],'5','3')
    if raw is None:return out
    # Query only the newly needed date interval; never request a full year.
    rows=raw
    byday=defaultdict(list)
    for r in rows:
        ts=r[1] if len(r)>1 else ''
        if r[0] in dates_needed and len(ts)>=12:
            byday[r[0]].append([ts[8:12],float(r[2]),float(r[3]),float(r[4]),float(r[5]),float(r[6]),float(r[7])])
    for d in dates_needed:
        bd=byday.get(d,[])
        if len(bd)==48:out[d]=bd
    # daily qfq/unadj/amount for needed dates
    daily={r[0]:r for r in (query_retry(bs,code,'date,close,amount',dates_needed[0],dates_needed[-1],'d','3') or []) if len(r)>=3}
    qfq={r[0]:r for r in (query_retry(bs,code,'date,close',dates_needed[0],dates_needed[-1],'d','2') or []) if len(r)>=2}
    for d in list(out):
        if d in daily and d in qfq:
            bd=out[d];amt=float(daily[d][2])
            s5=sum(b[6] for b in bd)
            if amt<=0 or not(0.95<=s5/amt<=1.05):out.pop(d);continue
            out[d]=(bd,amt,float(daily[d][1]),float(qfq[d][1]))
        else:out.pop(d)
    return out
def _alarm_handler(signum, frame):
    raise TimeoutError('baostock stock operation timeout')
def timed(call, seconds):
    signal.signal(signal.SIGALRM,_alarm_handler); signal.alarm(seconds)
    try: return call()
    except TimeoutError: return None
    finally: signal.alarm(0)
def main():
    cs=[r['code'] for g in json.load(open(SAMPLE))['groups'].values() for r in g['chosen']]
    off=int(os.environ.get('R5B_OFFSET','0')); lim=os.environ.get('R5B_LIMIT')
    cs=cs[off:off+int(lim)] if lim else cs[off:]
    shadow=load_jsonl_gz(SHADOW)
    last_global=max(r['date'] for r in shadow)
    eps=json.load(gzip.open(EPS,'rt'))['episodes']
    epset=defaultdict(list)
    for e in eps:epset[e['stock']].append((e['start'],e['end']))
    new_rows=[];n_new_days=0;stats={'stocks':0,'no_new_trade_day':0,'query_failed':0,'new_rows':0}
    try:
        import baostock as bs
        lg=bs.login()
        if lg.error_code!='0':
            print('LOGIN FAIL',lg.error_msg);sys.exit(1)
        per_stock_timeout=int(os.environ.get('R5B_STOCK_TIMEOUT','45'))
        for code in cs:
            stats['stocks']+=1
            signal.signal(signal.SIGALRM,_alarm_handler)
            signal.alarm(per_stock_timeout)
            six=code.split('.')[1]
            m5p=M5/f'{six}.json.gz'
            m=json.load(gzip.open(m5p,'rt')) if m5p.exists() else None
            if not m:continue
            dap=DA/f'{six}.json.gz'
            dstore=json.load(gzip.open(dap,'rt')) if dap.exists() else {'dates':[],'amount':[],'close':[],'qfq':[]}
            # Seed the 20-day baseline from official daily data on first run; without
            # this, a fresh dstore would silently skip every new row until 20 days accrue.
            if len(dstore['dates']) < 20:
                seed_start=m['dates'][max(0,len(m['dates'])-35)]
                q=bs.query_history_k_data_plus(code,'date,close,amount',start_date=seed_start,end_date=last_global,frequency='d',adjustflag='3')
                seed={}
                while q.error_code=='0' and q.next():
                    rr=q.get_row_data()
                    if len(rr)>=3: seed[rr[0]]=(float(rr[1]),float(rr[2]))
                q2=bs.query_history_k_data_plus(code,'date,close',start_date=seed_start,end_date=last_global,frequency='d',adjustflag='2')
                seedq={}
                while q2.error_code=='0' and q2.next():
                    rr=q2.get_row_data()
                    if len(rr)>=2: seedq[rr[0]]=float(rr[1])
                for dd in sorted(seed):
                    if dd in seedq:
                        dstore['dates'].append(dd);dstore['close'].append(seed[dd][0]);dstore['amount'].append(seed[dd][1]);dstore['qfq'].append(seedq[dd])
            hist_d=dict(zip(m['dates'],m['bars']))
            last_m5=m['dates'][-1]
            start=max(last_m5,last_global)
            # determine candidate dates: after max(last_m5, last_global) up to today via baostock trade days
            start=max(last_m5,last_global)
            today=datetime.date.today().isoformat()
            rs=bs.query_trade_dates(start_date=start,end_date=today)
            td=[]
            while rs.error_code=='0' and rs.next():
                r=rs.get_row_data()
                if r[1]=='1':td.append(r[0])
            need=[d for d in td if d>start and d>last_global]
            if not need:
                stats['no_new_trade_day']+=1;continue
            got=fetch_stock(bs,code,need)
            if not got:
                stats['query_failed']+=1;continue
            oam_hist=[]
            for d in m['dates']:
                oam_hist.append(sum(b[6] for b in hist_d[d] if '0935'<=b[0]<='1000'))
            prev_close=None  # unadjusted close of day before 'need[0]' = last stored daily close
            prev_close=dstore['close'][-1] if dstore['close'] else None
            # also qfq_prev for opening_return denominator uses unadj prev close
            for d in sorted(got):
                bd,amt,uc,qc=got[d]
                m['dates'].append(d);m['bars'].append(bd)
                dstore['dates'].append(d);dstore['amount'].append(amt);dstore['close'].append(uc);dstore['qfq'].append(qc)
                oam=sum(b[6] for b in bd if '0935'<=b[0]<='1000')
                oam_hist.append(oam)
                prev20=[a for a in oam_hist[:-1] if a>0][-20:]
                adv=dstore['amount'][-21:-1]
                if len(prev20)<20 or len(adv)<20 or any(a<=0 for a in adv) or prev_close is None or prev_close<=0:prev_close=uc;continue
                base=statistics.fmean(prev20);advv=statistics.fmean(adv)
                lam_o,fc=lam5(bd,'0930','1000',prev_close=prev_close)
                lam_post,_=lam5(bd,'1000','1500')
                c10=[b[4] for b in bd if b[0]=='1000']
                oc=[b[4] for b in bd if '0935'<=b[0]<='1000']
                pe=None
                if len(oc)>=2:
                    net=abs(oc[-1]-oc[0]);path=sum(abs(oc[i+1]-oc[i]) for i in range(len(oc)-1));pe=net/path if path>0 else None
                if lam_o is None or lam_post is None or not c10 or base<=0 or oam<=0:prev_close=uc;continue
                ep=1 if any(s<=d<=t for s,t in epset.get(six,())) else 0
                row={'code':code,'date':d,'in_model_period':d<=FREEZE,'opening_amount':oam,'expected_opening_amount':base,
                     'expected_daily_amount_adv20':advv,'e_open':math.log(oam/base),'share_open_pit':oam/advv,
                     'opening_return':c10[0]/prev_close-1,'opening_path_efficiency':pe,
                     'lambda_open':lam_o,'lambda_open_dim':lam_o*advv/float(dstore['qfq'][-2] if len(dstore['qfq'])>1 else qc),
                     'episode_state':ep,'daily_amount':amt,'daily_effort':math.log(amt/advv),
                     'opening_share_actual':oam/amt if amt>0 else None,
                     'post_open_lambda':lam_post,'post_open_lambda_dim':lam_post*advv/qc,
                     'close_retention':uc/c10[0]-1,'lambda_next_5':None,'lambda_next_20':None}
                new_rows.append(row);n_new_days+=1
                prev_close=uc
            with gzip.open(m5p,'wt') as f:json.dump(m,f)
            with gzip.open(dap,'wt') as f:json.dump(dstore,f)
        bs.logout()
    except Exception as e:
        import traceback;traceback.print_exc();sys.exit(1)
    if new_rows:
        with gzip.open(SHADOW,'at') as f:
            for r in new_rows:f.write(json.dumps(r,separators=(',',':'))+'\n')
    stats['new_rows']=len(new_rows)
    # Maturity backfill: lambda_next_5/20 for shadow rows whose forward window now exists.
    mat_have={(r['code'],r['date']) for r in load_jsonl_gz(MAT)}
    all_rows=shadow+new_rows
    mat_new=[]
    try:
        import baostock as bs
        bs.login()
        by_stock=defaultdict(list)
        for r in all_rows: by_stock[r['code']].append(r['date'])
        for code,dates in by_stock.items():
            # only rows whose maturity was NOT already written into shadow by the backfill
            dates=[r['date'] for r in all_rows if r['code']==code and r.get('lambda_next_20') is None]
            six=code.split('.')[1]
            dap=DA/f'{six}.json.gz'
            if not dap.exists():continue
            dstore=json.load(gzip.open(dap,'rt'))
            dd=dstore['dates'];amts=dict(zip(dd,dstore['amount']))
            need_dates=[d for d in dates if (code,d) not in mat_have]
            if not need_dates:continue
            span_lo=min(need_dates);span_hi=max(need_dates)
            i_lo=dd.index(span_lo) if span_lo in dd else 0
            # need qfq closes + h/l from ~span_lo to latest stored date
            qrows=query_retry(bs,code,'date,close,high,low',span_lo,dd[-1],'d','2') or []
            q=[(r[0],float(r[1]),float(r[2]),float(r[3])) for r in qrows if len(r)>=4]
            qd={x[0]:x for x in q};qlist=[qd[d] for d in dd if d in qd and d>=span_lo]
            if len(qlist)<2:continue
            qpos={d:i for i,d in enumerate([d for d in dd if d in qd and d>=span_lo])}
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
        bs.logout()
    except Exception:
        import traceback;traceback.print_exc()
    if mat_new:
        with gzip.open(MAT,'at') as f:
            for r in mat_new:f.write(json.dumps(r,separators=(',',':'))+'\n')
    stats['maturity_new']=len(mat_new)
    print(f'APPEND rows={len(new_rows)} new_days={n_new_days} shadow_last={last_global}->'+(new_rows[-1]["date"] if new_rows else last_global))
    print('STATS '+json.dumps(stats,separators=(',',':')))
if __name__=='__main__':main()
