#!/usr/bin/env python3
"""R2 当天(盘中)市场口径 —— 2026-10-22 老刘指令：「盘中轻扫要用当天数据」。

链路（全部只读现有资产，不改冻层）：
  1) 全市场实时快照(TDX) → 当日 eq_ret / 上涨占比
  2) 当日单日轴：ret20d / trend(MA250) 按 cd45 frozen bands 同口径打档 → 当日 regime
  3) 5 日窗口多数票（规则不动，与 current_scan/shadow 同）→ rgrp → 乘数
  4) 当日 breadth50（live px > MA50，与 shadow_portfolio.breadth50 同口径）→ 闸门
  5) 当天档位 = T-1 shadow 档位 × (乘数_今/乘数_T1) × (闸门_今/闸门_T1)   ← 精确比值，不复制公式

产物：data/r2/live_axis/live_axis_<YYYYMMDD>_<HHMM>.json
用法：.venv/bin/python src/r2/live_market_axis.py [--quiet]
失败安全：任何异常都不影响轻扫主链（调用方 try/except）。
"""
from __future__ import annotations
import argparse, gzip, json, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D_FM = ROOT / 'data' / 'cd' / 'daily_fullmarket'
SCANS = ROOT / 'data' / 'r2' / 'scans'
SHADOW = ROOT / 'data' / 'r2' / 'shadow'
AXES = ROOT / 'data' / 'cd' / 'sector_axes' / 'l1_market_axes.json.gz'
BANDS = ROOT / 'docs' / 'cd' / 'cd45_regime_results.json'
CACHE = ROOT / 'data' / 'r2' / 'cache'
OUTD = ROOT / 'data' / 'r2' / 'live_axis'

BASE_P3 = {'CONFIRM_CANDIDATE': 0.5, 'RISK_HOLD': 0.25, 'BUILD': 0.2}
MULT = {'BULL': 1.0, 'BEAR': 0.5}
GATE_B50 = 0.50          # breadth50 < 0.50 → 闸门 ON（×0.75）
Q5_REDUCE = 0.75


def rgrp(g):
    """与 current_scan.py:84 / ei1_breadth.rgrp 同口径。"""
    if not g: return 'OTHER'
    return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED', 'RISK_OFF', 'R_RISK_OFF')) else 'OTHER')


def mult_of(g):
    return MULT.get(rgrp(g), 0.75)


def _approx(v):
    if v is None: return 1.0 if v is not None else 1.0


def gate_mult(label):
    return 0.75 if (label or '').upper() == 'ON' else 1.0


# ---------- 1. 全市场日线尾（close / MA50），带缓存 ----------
def ma50_map():
    files = sorted(D_FM.glob('*.json.gz'))
    probe = None
    p0 = D_FM / '000001.json.gz'
    if p0.exists():
        try:
            probe = json.loads(gzip.decompress(p0.read_bytes()))['dates'][-1]
        except Exception:
            probe = None
    cache = CACHE / f'ma50_{probe or "na"}.json'
    if cache.exists():
        try:
            o = json.loads(cache.read_text())
            if o.get('n') == len(files) and o.get('latest') == probe:
                return probe, o['m'], 'cache'
        except Exception:
            pass
    m = {}
    for f in files:
        c = f.name.split('.')[0]
        if c.startswith('_'):
            continue
        try:
            rec = json.loads(gzip.decompress(f.read_bytes()))
            cl = [float(r[2]) for r in rec['qfq']]
        except Exception:
            continue
        if len(cl) < 50:
            continue
        m[c] = [cl[-1], sum(cl[-50:]) / 50]
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'n': len(files), 'latest': probe, 'm': m}, separators=(',', ':')))
    return probe, m, 'build'


# ---------- 2. 全市场实时快照（含 duplicate chunk 二分绕行） ----------
def snapshot_all(codes, batch=80):
    import sys
    sys.path.insert(0, str(ROOT / 'src'))
    from r2.tdx_quotes import quotes as _q

    out = {}

    def fetch(ch):
        if not ch:
            return
        try:
            r = _q(ch, with_name=False, batch=min(batch, len(ch)))
        except Exception:
            if len(ch) <= 1:
                return
            h = len(ch) // 2
            fetch(ch[:h]); fetch(ch[h:])
            return
        for k, v in r.items():
            out.setdefault(str(k)[-6:], v)

    for i in range(0, len(codes), batch):
        fetch(codes[i:i + batch])
    return out


def index_pct_safe():
    try:
        import sys
        sys.path.insert(0, str(ROOT / 'src'))
        from r2.tdx_quotes import index_pct
        return round(float(index_pct('sh000001')), 2)
    except Exception:
        return None


def latest_base():
    snap = sorted(SCANS.glob('current_scan_*.json'))
    if not snap:
        return None, None
    p = snap[-1]
    return p.stem[-10:], json.loads(p.read_text())


def t1_side(base_day):
    """T-1 冻结口径：regime_grp / 闸门 / 各 tier 档位。"""
    p = SHADOW / f'shadow_{base_day}.json'
    if not p.exists():
        return None
    s = json.loads(p.read_text())
    lv = {}
    for r in s.get('rows', []):
        t = r.get('tier')
        if t not in BASE_P3 or not r.get('p3_final'):
            continue
        lv.setdefault((t, bool(r.get('q5'))), round(r['p3_final'], 4))
    return {'day': s.get('day'), 'regime_5d': s.get('regime_5d'), 'regime_grp': s.get('regime_grp'),
            'breadth50': s.get('breadth50'), 'gate': s.get('breadth50_gate'),
            'tiers': {f'{t}|{"q5" if q else "base"}': v for (t, q), v in sorted(lv.items())}}


def compute():
    t0 = time.time()
    base_day, _scan = latest_base()
    t1 = t1_side(base_day) if base_day else None

    latest_date, m50, src = ma50_map()
    codes = sorted(m50)
    # 当日 breadth50 的 T-1 基线（同口径复算，用于展示；与 shadow 存值比对）
    t1_b50 = None
    if m50:
        t1_b50 = round(sum(1 for c in codes if m50[c][0] > m50[c][1]) / len(codes), 6)

    snap = snapshot_all(codes)
    pcts = []
    b50_up = 0
    b50_tot = 0
    for c in codes:
        q = snap.get(c)
        if not q:
            continue
        px = float(q.get('price') or 0)
        if px <= 0:
            continue
        p = q.get('pct')
        if p is not None:
            pcts.append(float(p) / 100.0)
        b50_tot += 1
        if px > m50[c][1]:
            b50_up += 1
    n = len(pcts)
    eq_ret = round(sum(pcts) / n, 6) if n else None
    adv = round(sum(1 for x in pcts if x > 0) / n, 6) if n else None
    b50_live = round(b50_up / b50_tot, 6) if b50_tot else None

    # ---------- 当日单日轴 ----------
    bands = json.loads(BANDS.read_text())['frozen_bands_dev']
    rows = json.loads(gzip.decompress(AXES.read_bytes()))['rows']

    def b(ax, v):
        if v is None: return None
        lo, hi = bands[ax]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'

    ret20 = round(sum(r['eq_ret'] for r in rows[-19:]) + (eq_ret or 0.0), 6)
    cum = 1.0
    cums = []
    for r in rows:
        cum *= (1 + r['eq_ret'])
        cums.append(cum)
    cum_live = cums[-1] * (1 + (eq_ret or 0.0))
    ma250 = (sum(cums[-249:]) + cum_live) / 250
    trend = 'ABOVE' if cum_live >= ma250 else 'BELOW'
    br_b, rt_b = b('breadth', adv), b('ret20d', ret20)
    if trend == 'ABOVE':
        live_regime = 'R_RISK_ON_BROAD' if (br_b != 'LOW' and rt_b != 'LOW') else 'R_RISK_ON_NARROW'
    elif rt_b == 'LOW' and br_b == 'LOW':
        live_regime = 'R_RISK_OFF'
    elif rt_b == 'LOW' and br_b == 'MID':
        live_regime = 'R_DEPRESSED'
    elif br_b == 'LOW' and rt_b == 'MID':
        live_regime = 'R_DEPRESSED'
    else:
        live_regime = 'R_REBOUND_MIXED'

    tail5 = [r['regime'] for r in rows[-4:]] + [live_regime]
    vote = Counter(tail5).most_common(1)[0][0]
    rg2 = rgrp(vote)
    m2 = MULT.get(rg2, 0.75)
    gate_on = bool(b50_live is not None and b50_live < GATE_B50)
    g2 = 0.75 if gate_on else 1.0

    o = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'day': time.strftime('%Y-%m-%d'),
         'base_day': base_day, 'idx_pct': index_pct_safe(),
         'snapshot': {'n': n, 'coverage': f'{b50_tot}/{len(codes)}', 'eq_ret': eq_ret, 'adv': adv},
         'axis': {'ret20d': ret20, 'trend': trend, 'bands': {'breadth': br_b, 'ret20d': rt_b},
                  'regime': live_regime},
         'window': {'tail5': tail5, 'vote': vote, 'rgrp': rg2, 'mult': m2},
         'gate': {'b50_live': b50_live, 'b50_t1_recalc': t1_b50, 'b50_t1_shadow': (t1 or {}).get('breadth50'),
                  'on': gate_on, 'mult': g2, 'b50_src': src, 'fm_latest_date': latest_date},
         't1': t1}
    factor = 1.0
    if t1:
        factor = (m2 / mult_of(t1.get('regime_5d'))) * (g2 / gate_mult(t1.get('gate')))
    o['t1_to_live_factor'] = round(factor, 6)
    lv = {}
    for t, base in BASE_P3.items():
        for q5 in (False, True):
            v = base * m2 * g2 * (Q5_REDUCE if q5 else 1.0)
            lv[f'{t}|{"q5" if q5 else "base"}'] = round(v, 4)
    o['tiers_live'] = lv
    o['elapsed_s'] = round(time.time() - t0, 1)
    return o


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    try:
        o = compute()
    except Exception as e:
        print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False))
        raise SystemExit(2)
    OUTD.mkdir(parents=True, exist_ok=True)
    p = OUTD / f"live_axis_{time.strftime('%Y%m%d_%H%M')}.json"
    p.write_text(json.dumps(o, ensure_ascii=False, indent=1))
    o['ok'] = True; o['out'] = str(p)
    if not a.quiet:
        print(json.dumps(o, ensure_ascii=False))
    return o


if __name__ == '__main__':
    main()