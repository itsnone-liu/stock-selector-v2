#!/usr/bin/env python3
"""CF-1B data base backfill — official sources, resumable (backfill whitelist: coverage check)

Usage: PYTHONPATH=/tmp/aksy nohup python3 scripts/cf/backfill_official.py --module all &
Modules:
  sse_etf    : SSE ETF daily scale 2012+ (per-day query)
  sse_margin : SSE margin summary 2018+ (range query, single call)
  szse_etf   : SZSE ETF daily scale 2016-12+ (11-day range queries)
  szse_margin: SZSE margin 2018+ (per-day query)
Output: data/cf/raw/{module}/*.csv  (skip-if-exists resume)
"""
import argparse, datetime, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, 'data', 'cf', 'raw')
SLEEP = 0.6


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def trade_dates(start: str, end: str):
    d = datetime.datetime.strptime(start, '%Y%m%d')
    e = datetime.datetime.strptime(end, '%Y%m%d')
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime('%Y%m%d'))
        d += datetime.timedelta(days=1)
    return out



def fetch(fn):
    """KeyError('None of ...')=官方空数据直通返回 None; 其他异常才 retry。"""
    try:
        return fn()
    except (KeyError, ValueError) as ke:
        s = str(ke)
        if 'None of' in s or 'columns' in s or 'Length mismatch' in s:
            return None  # 空表特征(KeyError/ValueError 两类)都直通
        raise
    except Exception:
        return retry(fn)

def retry(fn, n=3):
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            if i == n - 1:
                raise
            time.sleep(2 * (i + 1))


def m_sse_etf(ak):
    out = os.path.join(RAW, 'sse_etf_scale')
    os.makedirs(out, exist_ok=True)
    for d in trade_dates('20120101', '20261015'):
        f = os.path.join(out, f'{d}.csv')
        if os.path.exists(f) or os.path.exists(f + '.EMPTY'):
            continue
        df = fetch(lambda: ak.fund_etf_scale_sse(date=d))
        if df is None or len(df) == 0:
            open(f + '.EMPTY', 'w').close()
        else:
            df.to_csv(f, index=False)
        time.sleep(SLEEP)
    log('sse_etf DONE')


def m_sse_margin(ak):
    out = os.path.join(RAW, 'sse_margin')
    os.makedirs(out, exist_ok=True)
    f = os.path.join(out, 'summary_20180102_20261015.csv')
    if not os.path.exists(f):
        df = retry(lambda: ak.stock_margin_sse(start_date='20180102', end_date='20261015'))
        df.to_csv(f, index=False)
    log(f'sse_margin DONE rows={len(open(f).readlines()) if os.path.exists(f) else 0}')


def m_szse_etf(ak):
    out = os.path.join(RAW, 'szse_etf_scale')
    os.makedirs(out, exist_ok=True)
    dates = trade_dates('20161201', '20261015')
    for i in range(0, len(dates), 11):
        chunk = dates[i:i + 11]
        s, e = chunk[0], chunk[-1]
        f = os.path.join(out, f'{s}_{e}.csv')
        if os.path.exists(f) or os.path.exists(f + '.EMPTY'):
            continue
        df = fetch(lambda: ak.fund_scale_daily_szse(start_date=s, end_date=e, symbol='ETF'))
        if df is None or len(df) == 0:
            open(f + '.EMPTY', 'w').close()
        else:
            df.to_csv(f, index=False)
        time.sleep(SLEEP)
    log('szse_etf DONE')


def m_szse_margin(ak):
    out = os.path.join(RAW, 'szse_margin')
    os.makedirs(out, exist_ok=True)
    for d in trade_dates('20180102', '20261015'):
        f = os.path.join(out, f'{d}.csv')
        if os.path.exists(f) or os.path.exists(f + '.EMPTY'):
            continue
        df = fetch(lambda: ak.stock_margin_szse(date=d))
        if df is None or len(df) == 0:
            open(f + '.EMPTY', 'w').close()
        else:
            df.to_csv(f, index=False)
        time.sleep(SLEEP)
    log('szse_margin DONE')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--module', default='all', choices=['all', 'sse_etf', 'sse_margin', 'szse_etf', 'szse_margin'])
    args = ap.parse_args()
    import akshare as ak
    mods = {'sse_etf': m_sse_etf, 'sse_margin': m_sse_margin, 'szse_etf': m_szse_etf, 'szse_margin': m_szse_margin}
    todo = list(mods) if args.module == 'all' else [args.module]
    for m in todo:
        log(f'=== module {m} start ===')
        mods[m](ak)
    log('ALL DONE')


if __name__ == '__main__':
    main()
