#!/usr/bin/env python3
"""Descriptive TDX turnover proxy; no trading rules or net-flow inference.
Only build_daily is a daily feature table. Monthly/weekly tables are retrospective.
"""
import argparse
import calendar
import csv
import gzip
import hashlib
import json
import math
import struct
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = struct.Struct('<IIIIIfII')


def finite(value):
    return value is not None and value != '' and math.isfinite(float(value))


def parse_day_bytes(raw):
    if not raw or len(raw) % RECORD.size:
        raise ValueError('empty or truncated 32-byte TDX records')
    rows = []
    for rec in RECORD.iter_unpack(raw):
        s = str(rec[0])
        if len(s) != 8:
            raise ValueError('invalid TDX date')
        d = date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
        if rows and d <= rows[-1]['date']:
            raise ValueError('TDX dates must be strictly increasing')
        amount = rec[5]
        if not math.isfinite(amount) or amount < 0:
            raise ValueError('invalid TDX amount')
        # OHLC describe advancing-stock counts, NOT an investment index price.
        rows.append(dict(date=d, amount_yuan=amount, volume=rec[6]))
    return rows


def iso_week(d):
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f'{y}-W{w:02d}'


def build_daily(rows):
    out = []
    for i, r in enumerate(rows):
        if i and r['date'] <= rows[i-1]['date']:
            raise ValueError('daily dates must increase')
        amount = r['amount_yuan']
        v = dict(r, amount_yi=amount / 1e8 if finite(amount) else None,
                 iso_week=iso_week(r['date']),
                 available_at=(date.fromisoformat(r['date'])+timedelta(days=1)).isoformat()+'T00:00:00+08:00')
        for n in (20, 60):
            past = [x['amount_yuan'] for x in rows[max(0, i-n):i]]
            sequence = rows[max(0, i-n):i+1]
            gap = any((date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days > 14
                      for a,b in zip(sequence,sequence[1:]))
            status = 'GAP_GT14' if gap else ('INSUFFICIENT_OR_MISSING' if len(past) != n or not all(finite(x) and x > 0 for x in past) else 'OK')
            mean = sum(past) / n if status == 'OK' else None
            v[f'past{n}_status'] = status
            v[f'past{n}_mean_yuan'] = mean
            v[f'ratio{n}'] = amount / mean if mean and finite(amount) else None
        out.append(v)
    return out


def unique_map(rows, key):
    out = {}
    for r in rows:
        d = r[key]
        if d in out:
            raise ValueError(f'duplicate {key}: {d}')
        out[d] = r
    return out


def build_monthly(daily, axes_rows, price_rows):
    axes = unique_map(axes_rows, 'date')
    prices = unique_map(price_rows, 'trade_date')
    months = defaultdict(list)
    for r in daily:
        months[r['date'][:7]].append(r)
    out = []
    for month, rows in sorted(months.items()):
        first, last = rows[0]['date'], rows[-1]['date']
        end = f'{month}-{calendar.monthrange(int(month[:4]), int(month[5:]))[1]:02d}'
        complete = last == end or any(d['date'][:7] > month for d in daily)
        amounts = [r['amount_yi'] for r in rows if finite(r['amount_yi'])]
        m = dict(month=month, month_complete=complete, days=len(rows), first_date=first, last_date=last,
                 amount_days=len(amounts), amount_mean_yi=sum(amounts)/len(amounts) if amounts else None,
                 amount_min_yi=min(amounts) if amounts else None, amount_max_yi=max(amounts) if amounts else None)
        ar = [axes[r['date']] for r in rows if r['date'] in axes]
        m['axes_days'] = len(ar)
        for key in ('breadth', 'part', 'conc50'):
            vals = [float(a[key]) for a in ar if finite(a.get(key))]
            m[key+'_days'] = len(vals)
            m[key+'_mean'] = sum(vals)/len(vals) if vals else None
        eq = [float(a['eq_ret']) for a in ar if finite(a.get('eq_ret'))]
        m['eq_ret_days'] = len(eq)
        m['axes_complete'] = len(ar) == len(rows) and all(m[k+'_days'] == len(rows) for k in ('breadth','part','conc50','eq_ret'))
        m['eq_ret_compound'] = math.prod(1+x for x in eq)-1 if len(eq) == len(rows) else None
        m['index_return'], m['index_status'] = None, 'INCOMPLETE_MONTH'
        if complete:
            previous = sorted(d for d in prices if d < first)
            required = [r['date'] for r in rows]
            if not previous or any(d not in prices for d in required):
                m['index_status'] = 'MISSING_PREVIOUS_OR_MONTH_DATE'
            else:
                prev = previous[-1]
                sequence = [prev]+required
                valid = all(finite(prices[d].get('close')) and float(prices[d]['close']) > 0 for d in sequence)
                gaps = [(date.fromisoformat(b)-date.fromisoformat(a)).days for a,b in zip(sequence,sequence[1:])]
                if not valid or max(gaps) > 14:
                    m['index_status'] = 'INVALID_CLOSE_OR_GAP_GT14'
                else:
                    m['index_return'] = float(prices[last]['close'])/float(prices[prev]['close'])-1
                    m['index_status'] = 'OK'
        out.append(m)
    return out


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def source_info(path, raw=None):
    raw = path.read_bytes() if raw is None else raw
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def fmt(x):
    if x is None or x == '':
        return '—'
    return f'{x:.4f}' if isinstance(x, float) else str(x)


def table(rows, columns):
    return '\n'.join(['| '+' | '.join(columns)+' |','|'+'|'.join(['---']*len(columns))+'|']+
                     ['| '+' | '.join(fmt(r.get(k)) for k in columns)+' |' for r in rows])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tdx', type=Path, default=Path('/root/tdx_data/vipdoc/sh/lday/sh880005.day'))
    ap.add_argument('--axes', type=Path, default=ROOT/'data/cd/sector_axes/l1_market_axes.json.gz')
    ap.add_argument('--weekly', type=Path, default=ROOT/'data/cfis/weekly_full_202201_202610.csv')
    ap.add_argument('--index', type=Path, default=ROOT/'docs/phase_i/evidence/market_index_000985.json')
    ap.add_argument('--out-dir', type=Path, default=ROOT/'data/cfis')
    ap.add_argument('--docs-dir', type=Path, default=ROOT/'docs/research/cfis')
    args = ap.parse_args()
    raw = args.tdx.read_bytes()  # ~40 KB only; never writes the externally maintained source.
    parsed = parse_day_bytes(raw)
    daily = build_daily(parsed)
    info = source_info(args.tdx, raw)
    snapshot = args.out_dir/'snapshots'/f'sh880005_{parsed[0]["date"]}_{parsed[-1]["date"]}_{info["sha256"]}.day'
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists() and snapshot.read_bytes() != raw:
        raise ValueError('snapshot collision')
    snapshot.write_bytes(raw)
    with gzip.open(args.axes, 'rt', encoding='utf-8') as f:
        axes = json.load(f)['rows']
    prices = json.loads(args.index.read_text())['rows']
    with args.weekly.open() as f:
        weekly = list(csv.DictReader(f))
    unique_map(weekly, 'week')
    monthly = build_monthly(daily, axes, prices)
    dp, mp = args.out_dir/'is2c_turnover_daily.csv', args.out_dir/'is2c_turnover_monthly.csv'
    write_csv(dp, daily)
    write_csv(mp, monthly)
    anchors = [r for r in daily if r['date'] in ['2024-08-13','2024-09-18','2024-09-24','2024-09-30','2024-10-08']]
    shown = [m for m in monthly if m['month'] >= '2024-06']
    # ISOweek match for audit only: never joins the whole week's outcome into a daily feature.
    observed_weeks = {r['iso_week'] for r in daily if r['date'] >= '2024-06-01'}
    matched = [w for w in weekly if w['week'] in observed_weeks]
    report = '''# IS2C TDX统计成交额代理：日频与月度轨迹

## 口径、范围与时点

sh880005 是上涨家数统计指标，OHLC/close 不是可投资指数价格。只提取32字节 `<IIIIIfII` 的第6元 float amount（元）；第7元 volume 单独保存，不当金额。称 **TDX统计成交额代理**，ETF/北交所范围待确证，非官方沪深总额。金额单位换算为亿元不改变源精度。

成交额是双边交易活动规模，不是净流入、存量资金或新增资金；倍数不冒充净流。日频 past20/60 为严格排除当日的过去20/60个观测日算术均值，样本不足/窗口缺失或含当日边界的窗口内>14自然日断档留空（status显式）。日表available_at统一按次日00:00北京时间保守假设，不是历史发布时间取证，也不声称盘前已知。它们是观测日而非交易日历补齐窗口。axes part 是含当天的20日均成交量参与比，与这里严格过去成交额倍数口径不同；conc50 为正收益×volume前50贡献集中度，不是金额集中度。

日表仅含 TDX 当日观测与向后窗口；ISOweek只是连接键，不注入冻结整周广度/融资的事后值。月表是事后描述，按当月实际TDX日期匹配axes日频 breadth/part/conc50求有效日均，列出分母及完整性；eq_ret是日等权收益复利，缺一天留空，不代替独立指数。融资/L1/ETF等仍在独立冻结周表，不强拼月归属，不把跨月周重复计入月融资；周表以下每ISO周一行，m_fin_flow_w不按日重复sum，l1保持周原值。

月完整性只表示已观察到月末自然日或本输入已进入下月，不使用未来交易日历、也不保证源无漏日。内部>14自然日断档拒绝独立价格月收益。独立000985要求当月TDX首日前最近收盘与所有当月TDX日期价格（含末日）存在、间隔≤14天；不用上涨家数close，不用未来值。2026-04-30虽周四但确为自然月末，可完整四月；2026-10-29为不完整尾月，不用于长周期结果。月表仅为观察，非历史当日特征。

## 用户指定日期（非最优择时）

'''
    report += table(anchors, ['date','amount_yuan','amount_yi','past20_mean_yuan','ratio20','ratio60'])
    report += '\n\n## 2024年6月至全部可用月份\n\n金额均值/min/max为亿元；收益为小数，—为缺失。月均可能掩盖月内上升或回落，不能凭单日峰值或高额推断持续扩散/普涨。\n\n'
    report += table(shown, ['month','month_complete','amount_mean_yi','amount_min_yi','amount_max_yi','days','first_date','last_date','axes_days','axes_complete','breadth_mean','part_mean','conc50_mean','eq_ret_compound','index_return','index_status'])
    report += '\n\n## 冻结周层（独立粒度，跨月边界mixed，不聚合进月表）\n\n周信息仅事后观察，非当日可用特征；可用时点沿用冻结表，非重新声称PIT。跨月周mixed明确列示，周均而非日重复均值。\n\n'
    for w in matched:
        y, wn = w['week'].split('-W')
        monday = date.fromisocalendar(int(y),int(wn),1)
        friday = date.fromisocalendar(int(y),int(wn),5)
        w['boundary'] = 'mixed' if monday.month != friday.month else 'within_month'
    report += table(matched, ['week','week_end','boundary','ax_breadth','ax_part','ax_conc50','m_fin_flow_w','l1_fam_delta_w','days_obs'])
    report += '\n\n## 限制\n\n无最优择时搜索、无新阈值、无交易规则、无收益保证。2024-09-24仅指定历史描述锚点。独立价格覆盖止于'+max(r['trade_date'] for r in prices)+'，不凭金额/axes更长覆盖推断之后价格上涨。缺失不填充；完整月标签不是交易所日历认证。\n'
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    rp = args.docs_dir/'IS2C_TURNOVER_TRAJECTORY.md'
    rp.write_text(report, encoding='utf-8')
    manifest = dict(schema_version=1, source=info, snapshot=source_info(snapshot),
        coverage=dict(first_date=daily[0]['date'], last_date=daily[-1]['date'], records=len(daily)),
        inputs={k:source_info(getattr(args,k)) for k in ('axes','weekly','index')},
        outputs={k:source_info(p) for k,p in [('daily',dp),('monthly',mp),('report',rp)]},
        index_coverage=dict(first=min(r['trade_date'] for r in prices),last=max(r['trade_date'] for r in prices)),
        weekly_iso_matches=len(matched), monthly_rows=len(monthly), amount_unit='yuan', amount_record_index=5,
        source_scope='TDX统计成交额代理; ETF/北交所待确证; 非官方沪深总额',
        month_policy='observed calendar month end or later input month; no future calendar',
        daily_feature_policy='prior 20/60 observations excluding current; no weekly features',
        missing_policy='blank, no imputation', research_only=True)
    (args.docs_dir/'is2c_turnover_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(rows=len(daily),months=len(monthly),snapshot=str(snapshot),sha256=info['sha256']),ensure_ascii=False))


if __name__ == '__main__':
    main()
