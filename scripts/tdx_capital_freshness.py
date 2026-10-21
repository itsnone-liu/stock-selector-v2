#!/usr/bin/env python3
"""股本新鲜度研究：capital-batch data_date 分布 + 送转事件是否落后于股本缓存。

判据：若某票存在 cat1 送转/配股事件日期 > capital.data_date → 该票股本已过期（STALE）。
产物：data/r2/tdx/capital_freshness_YYYYMMDD.json
"""
import sys, os, json, gzip, random, collections, argparse, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from r2.tdx_client import with_session, symbol  # noqa


def prefix(code):
    if code.startswith(('6', '9')):
        return 'sh' + code
    if code.startswith(('0', '2', '3')):
        return 'sz' + code
    return 'bj' + code


def pull(sample, chunk=10, sess_provider=with_session):
    """分块拉股本；块内 identity mismatch 时退化为逐只，缺票记 None。"""
    def op(s):
        out = {}
        for i in range(0, len(sample), chunk):
            part = sample[i:i + chunk]
            try:
                rows = s.capital_batch([symbol(prefix(c)) for c in part])
                for r in rows:
                    out[r['code']] = r
                if len(rows) != len(part):
                    raise ValueError('short')
            except Exception:
                for c in part:
                    try:
                        rs = s.capital_batch([symbol(prefix(c))])
                        out[c] = rs[0] if rs else None
                    except Exception:
                        out[c] = None
        return out
    return sess_provider(op)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=300)
    ap.add_argument('--seed', type=int, default=11)
    ap.add_argument('--xdxr', default='data/r2/tdx/xdxr_fullmarket_20261021.json.gz')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    random.seed(a.seed)

    d = json.load(gzip.open(a.xdxr, 'rt'))
    ev = collections.defaultdict(list)
    for r in d['events']:
        ev[r['code']].extend(r['events'])
    codes = sorted(ev)
    sample = random.sample(codes, min(a.n, len(codes)))

    cap = pull(sample)

    stale, fresh, missing = [], [], []
    dd_bucket = collections.Counter()
    for c in sample:
        r = cap.get(c)
        if not r:
            missing.append(c)
            continue
        dd = int(r['data_date'])
        dd_bucket[str(dd)[:6]] += 1
        late = [e for e in ev[c]
                if e['category'] == 1 and e['date'] > dd and (e.get('f3') or e.get('f4'))]
        bucket = {'code': c, 'data_date': dd, 'float_shares': r.get('float_shares'),
                  'late_songzhuan': sorted(str(e['date']) for e in late)[-3:]}
        (stale if late else fresh).append(bucket)

    ts = datetime.datetime.now().strftime('%Y%m%d')
    out = a.out or f'data/r2/tdx/capital_freshness_{ts}.json'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({'generated': datetime.datetime.now().isoformat(timespec='seconds'),
               'sample_n': len(sample), 'stale_n': len(stale), 'fresh_n': len(fresh),
               'missing_n': len(missing), 'data_date_month_dist': dict(dd_bucket),
               'stale_examples': stale[:40], 'missing_examples': missing[:40]},
              open(out, 'w'), ensure_ascii=False, indent=1)

    print(f'sample={len(sample)} fresh={len(fresh)} stale={len(stale)} missing={len(missing)}')
    print('data_date 月度分布:', dict(sorted(dd_bucket.items())))
    print('STALE 例:', [(x['code'], x['data_date'], x['late_songzhuan']) for x in stale[:8]])
    print('缺失例:', missing[:8])
    print('out=', out)


if __name__ == '__main__':
    main()