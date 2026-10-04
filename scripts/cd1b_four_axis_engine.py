#!/usr/bin/env python3
"""CD-1B four-axis observables engine (preregistered: docs/cd/cd1b_preregistration.json).
Per (L2_csrc sector, date): Relative Performance / Participation / Breadth / Concentration.
Pure function of (DATA-1, csrc_v1 membership). Determinism check: dual-run rows-sha identical.
NO composite score, NO ranking, trailing windows only. Usage: [--verify]"""
import json, gzip, sys, hashlib, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / 'data' / 'cd' / 'daily_fullmarket'
SEED = ROOT / 'data' / 'cd' / 'sector_seeds' / 'csrc_v1.json'
OUTDIR = ROOT / 'data' / 'cd' / 'sector_axes'
MIN_PART = 5      # preregistered participation floor
VOL_WIN = 20      # volume-confirmation window (strictly prior sessions)
NH_WIN = 60       # new-high window (trailing, inclusive of T)
SHARE_WIN = 20    # participation share trailing mean (inclusive of T)

def load_membership():
    members_l2, members_l1 = defaultdict(list), defaultdict(list)
    l1_of_l2 = {}
    for m in json.load(open(SEED))['members']:
        if m.get('L2'):
            members_l2[m['L2']].append(m['code'])
            members_l1[m['L1']].append(m['code'])
            l1_of_l2[m['L2']] = m['L1']
    return dict(members_l2), dict(members_l1), l1_of_l2

def load_market():
    """per-stock: {code: (date->idx map, qfq closes, raw vols, returns, prior-vol-mean, new-high flags)}"""
    stocks = {}
    cal_set = set()
    files = sorted(f for f in D.glob('*.json.gz') if not f.name.startswith('_'))
    for f in files:
        rec = json.loads(gzip.decompress(f.read_bytes()))
        if not rec['dates']: continue
        ds = rec['dates']
        closes = [float(r[2]) for r in rec['qfq']]
        vols = [float(r[5]) for r in rec['unadj']]
        n = len(ds)
        ret = [None]*n
        for i in range(1, n):
            pc = closes[i-1]
            if pc > 0: ret[i] = (closes[i]-pc)/pc
        pvm = [None]*n
        for i in range(VOL_WIN, n):
            w = vols[i-VOL_WIN:i]
            s = sum(w)
            if s > 0 or all(v == 0 for v in w): pvm[i] = s/VOL_WIN
        nh = [False]*n
        for i in range(NH_WIN-1, n):
            if closes[i] >= max(closes[i-NH_WIN+1:i+1]): nh[i] = True
        stocks[f.name.split('.')[0]] = ({d: i for i, d in enumerate(ds)}, closes, vols, ret, pvm, nh)
        cal_set.update(ds)
    cal = sorted(cal_set)
    return stocks, cal

def rnd(x): return round(x, 8) if x is not None else None
def rnd6(x): return round(x, 6) if x is not None else None
def sub(a, b): return (a-b) if (a is not None and b is not None) else None

def build(stocks, cal, code_l2, l1_of_l2):
    rows = []
    share_hist = defaultdict(list)
    for d in cal:
        m_rets, m_wts, m_vol = [], [], 0.0
        acc = defaultdict(lambda: {'rets': [], 'vols': [], 'adv': 0, 'vc': 0, 'nh': 0, 'pos': []})
        l1_acc = defaultdict(lambda: {'rets': [], 'vols': []})
        for code, (ix, closes, vols, ret, pvm, nh) in stocks.items():
            i = ix.get(d)
            if i is None: continue
            v = vols[i]; r = ret[i]
            m_vol += v
            if r is not None:
                m_rets.append(r); m_wts.append(v)
            l2 = code_l2.get(code)
            if l2 is None: continue
            a = acc[l2]; la = l1_acc[l1_of_l2[l2]]
            if r is not None:
                a['rets'].append(r); a['vols'].append(v)
                la['rets'].append(r); la['vols'].append(v)
                if r > 0: a['adv'] += 1
                a['pos'].append((max(r, 0.0)*v, code))
            if pvm[i] is not None and v > pvm[i]: a['vc'] += 1
            if nh[i]: a['nh'] += 1
        mkt_eq = sum(m_rets)/len(m_rets) if m_rets else None
        mkt_w = sum(m_wts)
        mkt_vw = (sum(a*b for a, b in zip(m_rets, m_wts))/mkt_w) if m_rets and mkt_w > 0 else None
        for lab in sorted(acc):
            a = acc[lab]
            n_part = len(a['vols'])
            if n_part < MIN_PART:
                rows.append({'l2': lab, 'date': d, 'status': 'INSUFFICIENT_PARTICIPATION', 'n': n_part})
                continue
            s_eq = sum(a['rets'])/len(a['rets']) if a['rets'] else None
            sv = sum(a['vols'])
            s_vw = (sum(r*v for r, v in zip(a['rets'], a['vols']))/sv) if a['rets'] and sv > 0 else None
            la = l1_acc.get(l1_of_l2[lab])
            p_eq = (sum(la['rets'])/len(la['rets'])) if la and la['rets'] else None
            pw = sum(la['vols']) if la else 0.0
            p_vw = (sum(r*v for r, v in zip(la['rets'], la['vols']))/pw) if la and la['rets'] and pw > 0 else None
            pos_total = sum(c for c, _ in a['pos'])
            pos_sorted = sorted((c for c, _ in a['pos']), reverse=True)
            top3 = (sum(pos_sorted[:3])/pos_total) if pos_total > 0 else None
            top5 = (sum(pos_sorted[:5])/pos_total) if pos_total > 0 else None
            vol_sorted = sorted(a['vols'], reverse=True)
            by_vol = sorted(zip(a['rets'], a['vols']), key=lambda x: -x[1])
            if len(by_vol) >= 6:
                t5m = sum(r for r, _ in by_vol[:5])/5.0
                rm = sum(r for r, _ in by_vol[5:])/len(by_vol[5:])
            else:
                t5m = rm = None
            share = sv/m_vol if m_vol > 0 else None
            share_hist[lab].append(share)
            shw = share_hist[lab][-SHARE_WIN:]
            sh_mean = (sum(shw)/len(shw)) if shw and all(x is not None for x in shw) else None
            rows.append({'l2': lab, 'date': d, 'status': 'OK', 'n': n_part,
                'sector_eq': rnd(s_eq), 'sector_vw': rnd(s_vw),
                'mkt_eq': rnd(mkt_eq), 'mkt_vw': rnd(mkt_vw),
                'rel_eq_mkt': rnd(sub(s_eq, mkt_eq)), 'rel_vw_mkt': rnd(sub(s_vw, mkt_vw)),
                'rel_eq_parent': rnd(sub(s_eq, p_eq)), 'rel_vw_parent': rnd(sub(s_vw, p_vw)),
                'vol_share': rnd6(share), 'vol_share_20d': rnd6(sh_mean),
                'advance_frac': rnd6(a['adv']/n_part),
                'vol_confirmed_frac': rnd6(a['vc']/n_part),
                'new_high_frac': rnd6(a['nh']/n_part),
                'ret_contrib_top3': rnd6(top3), 'ret_contrib_top5': rnd6(top5),
                'vol_top3': rnd6(sum(vol_sorted[:3])/sv if sv > 0 else None),
                'vol_top5': rnd6(sum(vol_sorted[:5])/sv if sv > 0 else None),
                'top5_mean_ret': rnd(t5m), 'rest_mean_ret': rnd(rm)})
        # fail-closed: sectors whose entire membership was suspended on d emit explicit row
        emitted = {r['l2'] for r in rows if r['date'] == d}
        for lab in sorted(set(code_l2.values()) - emitted):
            rows.append({'l2': lab, 'date': d, 'status': 'NO_TRADING_MEMBERS', 'n': 0})
    return rows

def main():
    t0 = time.time()
    members_l2, members_l1, l1_of_l2 = load_membership()
    code_l2 = {c: lab for lab, cs in members_l2.items() for c in cs}
    stocks, cal = load_market()
    print(f'loaded {len(stocks)} stocks, {len(cal)} dates ({time.time()-t0:.0f}s)', flush=True)
    rows = build(stocks, cal, code_l2, l1_of_l2)
    sha_rows = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / 'l2_four_axes.json.gz').write_bytes(
        gzip.compress(json.dumps({'n_rows': len(rows), 'rows': rows}, separators=(',', ':')).encode(), 6))
    ok = sum(1 for r in rows if r['status'] == 'OK')
    by_l2 = defaultdict(lambda: [0, 0])
    for r in rows:
        by_l2[r['l2']][0 if r['status'] == 'OK' else 1] += 1
    json.dump({'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'n_rows': len(rows), 'ok': ok, 'insufficient': len(rows)-ok,
               'sha256_rows': sha_rows, 'sectors': len(by_l2), 'dates': len(cal),
               'per_sector_ok_insufficient': {k: v for k, v in sorted(by_l2.items())}},
              open(ROOT / 'docs' / 'cd' / 'cd1b_axes_run.json', 'w'), indent=1)
    print(f'rows={len(rows)} ok={ok} insufficient={len(rows)-ok} sectors={len(by_l2)} sha_rows={sha_rows[:16]} ({time.time()-t0:.0f}s)', flush=True)

if __name__ == '__main__':
    main()
