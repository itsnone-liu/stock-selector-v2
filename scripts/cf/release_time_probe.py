#!/usr/bin/env python3
"""CF-1A release-time probe — 五时点采样脚本 (G2/G3 证据采集)

Usage: PYTHONPATH=/tmp/aksy python3 scripts/cf/release_time_probe.py --trade-date 20261016 --label morning_0830
Output: docs/cf/cf1a_probes/release_time/{T}_{label}.json
"""
import argparse, datetime, hashlib, json, os, struct, sys, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'docs', 'cf', 'cf1a_probes', 'release_time')
TDX_LDAY = '/root/tdx_data/vipdoc/sh/lday'


def h16(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def probe_sse_etf(ak, d):
    try:
        df = ak.fund_etf_scale_sse(date=d)
        recs = {str(r['基金代码']): float(r['基金份额']) for _, r in df.iterrows()}
        return {'ok': True, 'rows': len(df), 'hash16': h16(recs), 'total_shares': sum(recs.values())}
    except Exception as e:
        return {'ok': False, 'err': f'{type(e).__name__}: {str(e)[:80]}'}


def probe_sse_margin(ak, d):
    try:
        df = ak.stock_margin_sse(start_date=d, end_date=d)
        if len(df) == 0:
            return {'ok': True, 'rows': 0}
        rec = {k: str(v) for k, v in df.iloc[0].to_dict().items()}
        return {'ok': True, 'rows': 1, 'hash16': h16(rec), 'zye': rec.get('融资余额')}
    except Exception as e:
        return {'ok': False, 'err': f'{type(e).__name__}: {str(e)[:80]}'}


def probe_szse_margin(ak, d):
    try:
        df = ak.stock_margin_szse(date=d)
        if len(df) == 0:
            return {'ok': True, 'rows': 0}
        rec = {k: str(v) for k, v in df.iloc[0].to_dict().items()}
        return {'ok': True, 'rows': 1, 'hash16': h16(rec), 'rzye': rec.get('融资余额')}
    except Exception as e:
        return {'ok': False, 'err': f'{type(e).__name__}: {str(e)[:80]}'}


def probe_szse_etf(ak, d):
    try:
        df = ak.fund_scale_daily_szse(start_date=d, end_date=d, symbol='ETF')
        recs = {str(r.get('基金代码', i)): str(r.get('当日份额', r.get('份额', ''))) for i, r in df.iterrows()}
        return {'ok': True, 'rows': len(df), 'hash16': h16(recs)}
    except Exception as e:
        return {'ok': False, 'err': f'{type(e).__name__}: {str(e)[:80]}'}


def probe_legu(ak):
    try:
        df = ak.stock_market_activity_legu()
        return {'ok': True, 'items': {str(r['item']): str(r['value']) for _, r in df.iterrows()}}
    except Exception as e:
        return {'ok': False, 'err': f'{type(e).__name__}: {str(e)[:80]}'}


def probe_tdx880(codes=('880005', '880006')):
    out = {}
    for c in codes:
        p = os.path.join(TDX_LDAY, f'sh{c}.day')
        try:
            data = open(p, 'rb').read()
            r = struct.unpack('<IIIIIfII', data[-32:])
            d = f"{r[0]//10000}-{r[0]//100%100:02d}-{r[0]%100:02d}"
            out[c] = {'ok': True, 'date': d, 'close': r[4] / 100, 'amount': r[5]}
        except Exception as e:
            out[c] = {'ok': False, 'err': str(e)[:80]}
    return out


def prev_trade_date(d: str) -> str:
    dt = datetime.datetime.strptime(d, '%Y%m%d')
    dt -= datetime.timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= datetime.timedelta(days=1)
    return dt.strftime('%Y%m%d')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trade-date', required=True, help='T, e.g. 20261016')
    ap.add_argument('--label', required=True, help='morning_0830 / intraday_1100 / tail_1430 / post_1530 / evening / adhoc')
    args = ap.parse_args()
    T, Tm1 = args.trade_date, prev_trade_date(args.trade_date)

    res = {
        '_meta': {'probe': 'release_time', 'T': T, 'T_minus_1': Tm1, 'label': args.label,
                  'queried_at': datetime.datetime.now().isoformat(timespec='seconds')},
        'sse_etf_T': None, 'sse_etf_Tm1': None,
        'sse_margin_T': None, 'sse_margin_Tm1': None,
        'szse_margin_T': None, 'szse_margin_Tm1': None,
        'szse_etf_T': None,
        'legu_now': None, 'tdx880': None,
    }
    try:
        import akshare as ak
        res['sse_etf_T'] = probe_sse_etf(ak, T)
        res['sse_etf_Tm1'] = probe_sse_etf(ak, Tm1)
        res['sse_margin_T'] = probe_sse_margin(ak, T)
        res['sse_margin_Tm1'] = probe_sse_margin(ak, Tm1)
        res['szse_margin_T'] = probe_szse_margin(ak, T)
        res['szse_margin_Tm1'] = probe_szse_margin(ak, Tm1)
        res['szse_etf_T'] = probe_szse_etf(ak, T)
        res['legu_now'] = probe_legu(ak)
    except Exception:
        res['_meta']['akshare_fatal'] = traceback.format_exc(limit=2)
    res['tdx880'] = probe_tdx880()

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f'{T}_{args.label}.json')
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print('saved:', out)


if __name__ == '__main__':
    main()
