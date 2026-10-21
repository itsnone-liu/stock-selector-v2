#!/usr/bin/env python3
"""全市场 TDX 除权事件表落盘（op15 xdxr_batch）。

用法: .venv/bin/python scripts/tdx_fetch_xdxr_fullmarket.py [--out PATH]
池子: data/cd/daily_fullmarket/*.json.gz 的 code 全集 ∩ 本地 /root/tdx_data/{sh,sz,bj}/lday 存在
      可用 --pool all 改为纯本地 .day 全量（含指数，一般不用）
产物: data/r2/tdx/xdxr_fullmarket_YYYYMMDD.json.gz
"""
import argparse
import gzip
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from r2.tdx_client import with_session, symbol  # noqa: E402

log = logging.getLogger('tdx_xdxr')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

TDX_ROOT = Path('/root/tdx_data')
ARCHIVE = ROOT / 'data' / 'cd' / 'daily_fullmarket'


def stock_universe():
    codes = sorted(p.name.split('.')[0] for p in ARCHIVE.glob('*.json.gz') if not p.name.startswith('_'))
    out, missing = [], []
    for c in codes:
        if c.startswith(('6', '9')):
            mkt = 'sh'
        elif c.startswith(('0', '3', '2')):
            mkt = 'sz'
        else:
            mkt = 'bj'
        if (TDX_ROOT / mkt / 'lday' / (mkt + c + '.day')).exists():
            out.append((mkt, c))
        else:
            missing.append(mkt + c)
    return out, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    stocks, missing = stock_universe()
    stocks = [symbol(m + c) for m, c in stocks]
    log.info('universe=%d missing_local_day=%d %s', len(stocks), len(missing), missing[:10])
    t0 = time.time()
    batches = 0

    def op(s):
        nonlocal batches
        rows = []
        total = len(stocks)
        for start in range(0, total, 200):
            chunk = stocks[start:start + 200]
            rows.extend(s.xdxr_batch(chunk))
            batches += 1
            log.info('progress %d/%d elapsed=%.1fs', min(start + 200, total), total, time.time() - t0)
        return rows

    rows = with_session(op)
    total_events = sum(len(r['events']) for r in rows)
    cats = {}
    for r in rows:
        for e in r['events']:
            cats[e['category']] = cats.get(e['category'], 0) + 1
    out = {
        'source': 'tdx_op15_xdxr_batch',
        'fetched_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        'universe_size': len(stocks),
        'batches': batches,
        'rows': len(rows),
        'total_events': total_events,
        'category_counts': {str(k): v for k, v in sorted(cats.items())},
        'elapsed_sec': round(time.time() - t0, 1),
        'events': [dict(market=r['market'], code=r['code'], events=r['events']) for r in rows],
    }
    out_path = Path(args.out) if args.out else ROOT / 'data' / 'r2' / 'tdx' / f"xdxr_fullmarket_{datetime.now():%Y%m%d}.json.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix('.tmp')
    with gzip.open(tmp, 'wt', encoding='utf8') as f:
        json.dump(out, f, ensure_ascii=False, allow_nan=False)
    tmp.replace(out_path)
    log.info('DONE rows=%d events=%d cats=%s elapsed=%.1fs -> %s',
             len(rows), total_events, out['category_counts'], out['elapsed_sec'], out_path)


if __name__ == '__main__':
    main()