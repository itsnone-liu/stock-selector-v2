#!/usr/bin/env python3
"""Point-in-time event timeline, not a trading strategy (stdlib only).

CSV goes to stdout by default; --out selects a file. No collection or seed edits.
POST windows are fixed observed trading weeks: invalid rows are never skipped.
"""
import argparse
import csv
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))
METRICS = ('l1_fam_delta_w', 'm_fin_flow_w', 'm_pressure', 'ax_breadth',
           'ax_part', 'ax_conc50', 'l4_amt_ratio')


def timestamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            if len(str(value)) != 10:
                return None  # ambiguous timezone-free intraday timestamps
            result = result.replace(tzinfo=TZ)
        return result.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def week_start(week):
    year, w = week.split('-W')
    return date.fromisocalendar(int(year), int(w), 1)


def compound(values):
    return math.prod(1 + x for x in values) - 1


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def fields():
    base = ['event_id', 'title', 'event_cluster_id', 'published_at', 'first_usable_at',
            'event_week', 'visible_cluster_ids', 'availability_semantics', 'label',
            'pre_status', 'pre_week', 'pre_usable_at']
    base += ['pre_' + m for m in METRICS]
    for n in (1, 2, 4):
        base += [f'post{n}_weeks', f'post{n}_status', f'post{n}_ew_compound_proxy',
                 f'post{n}_index_compound', f'post{n}_index_status']
    return base + [f'post4_{kind}_{m}' for m in METRICS for kind in ('mean', 'delta')]


def build_timeline(events, weekly, baseline=()):
    """Return one row per event. All future data is confined to POST labels."""
    ids = set()
    for event in events:
        eid = event.get('event_id')
        if not eid or eid in ids:
            raise ValueError('missing or duplicate event_id')
        ids.add(eid)
        if timestamp(event.get('first_usable_at')) is None:
            raise ValueError(f'invalid first_usable_at: {eid}')
        if event.get('published_at'):
            published = timestamp(event['published_at'])
            if published is None or published > timestamp(event['first_usable_at']):
                raise ValueError(f'invalid published_at ordering: {eid}')
    weeks = sorted(weekly, key=lambda row: week_start(row['week']))
    if len({r['week'] for r in weeks}) != len(weeks):
        raise ValueError('duplicate weekly week')
    indexes = {}
    for row in baseline:
        if row['week'] in indexes:
            raise ValueError('duplicate baseline week')
        indexes[row['week']] = row
    # Include trading weeks with broken AX coverage; do not slide past them.
    observed = [r for r in weeks if (number(r.get('days_obs')) or 0) > 0
                or (number(r.get('ax_days')) or 0) > 0]
    ordered = sorted(events, key=lambda e: (timestamp(e['first_usable_at']), e['event_id']))
    output = []
    for event in ordered:
        at = timestamp(event['first_usable_at'])
        monday = at.date() - timedelta(days=at.weekday())
        iso = monday.isocalendar()
        cluster = event.get('event_cluster_id') or event['event_id']
        visible = [e['event_id'] for e in ordered
                   if (e.get('event_cluster_id') or e['event_id']) == cluster
                   and timestamp(e['first_usable_at']) <= at]
        row = dict.fromkeys(fields(), '')
        row.update(event_id=event['event_id'], title=event.get('title', ''),
                   event_cluster_id=cluster, published_at=event.get('published_at', ''),
                   first_usable_at=event['first_usable_at'], event_week=f'{iso.year}-W{iso.week:02}',
                   visible_cluster_ids=json.dumps(visible, ensure_ascii=False),
                   availability_semantics='PUBLICATION_AVAILABILITY_NOT_TRADABILITY',
                   label='DESCRIPTIVE_ONLY_NOT_A_BUY_SIGNAL')
        candidates = [r for r in weeks if week_start(r['week']) < monday
                      and str(r.get('availability_unknown')) == '0'
                      and timestamp(r.get('usable_at')) is not None
                      and at - timedelta(days=21) <= timestamp(r['usable_at']) < at]
        pre = max(candidates, key=lambda r: (timestamp(r['usable_at']), r['week'])) if candidates else None
        row['pre_status'] = 'AVAILABLE' if pre else 'MISSING_WITHIN_21D'
        if pre:
            row.update(pre_week=pre['week'], pre_usable_at=pre['usable_at'])
            for metric in METRICS:
                row['pre_' + metric] = pre.get(metric, '')  # preserve source values
        following = [r for r in observed if week_start(r['week']) > monday]
        for n in (1, 2, 4):
            window = following[:n]
            row[f'post{n}_weeks'] = '|'.join(r['week'] for r in window)
            valid = len(window) == n and all(
                (number(r.get('ax_days')) or 0) > 0
                and number(r.get('ax_eq_ret_w')) is not None
                and timestamp(r.get('usable_at')) is not None
                for r in window)
            status = 'AVAILABLE' if valid else ('MISSING_INSUFFICIENT_WEEKS' if len(window) < n else 'MISSING_INVALID_WEEK')
            row[f'post{n}_status'] = status
            if valid:
                row[f'post{n}_ew_compound_proxy'] = compound([number(r['ax_eq_ret_w']) for r in window])
            matched = [indexes.get(r['week'], {}) for r in window]
            index_valid = valid and all(r.get('coverage_status') == 'ENDPOINT_AVAILABLE'
                                       and number(r.get('index_week_return')) is not None for r in matched)
            row[f'post{n}_index_status'] = 'AVAILABLE' if index_valid else 'MISSING_ENDPOINT_OR_POST_WINDOW'
            if index_valid:
                row[f'post{n}_index_compound'] = compound([number(r['index_week_return']) for r in matched])
            if n == 4 and valid:
                for metric in METRICS:
                    values = [number(r.get(metric)) for r in window]
                    if all(v is not None for v in values):
                        mean = sum(values) / 4
                        row[f'post4_mean_{metric}'] = mean
                        before = number(pre.get(metric)) if pre else None
                        if before is not None:
                            row[f'post4_delta_{metric}'] = mean - before
        output.append(row)
    return output


def report(rows):
    counts = Counter(r['post4_status'] for r in rows)
    lines = ['# IS2B 逐事件描述性时间线', '',
             f'事件数：{len(rows)}；保留 seed 所有事件，不去簇丢弃后续事件。', '',
             '## 时间与缺失规则',
             '- 按 first_usable_at 排序；visible_cluster_ids 仅包含同簇且 first_usable_at <= 当前事件的成员。',
             '- publication availability 不等于可交易（tradability）；时间戳不是成交价格或买点。',
             '- 日期无时分按中国时区00:00解释；含时分的 timestamp 必须显式提供时区。',
             '- PRE 排除事件及未来 ISO 周，仅取 usable_at 严格早于事件、availability_unknown==0 的最近周；按 usable_at 最多回溯21天，缺失不补0。',
             '- POST 完全排除事件 ISO 周，固定选之后1/2/4个已观测交易周，不因坏周向后跳选。',
             '- 完整窗口须每周 ax_days>0、ax_eq_ret_w 非空且有限、usable_at 有效；不足/坏周留空。',
             '- post4 均值逐指标要求四周全有值，不 skip 缺失；delta=post4 mean−PRE 原值。',
             '- EW 为周等权收益复利代理，不是可执行组合净值；不是指数价格收益。',
             '- 可选真实价格基准使用 is2a_index_baseline 同一 POST 周，全部周端点 ENDPOINT_AVAILABLE 才复利；不填充缺失。',
             '- 完整性指已落盘周观测及上述数据守卫；未额外声称已核验交易所每日交易日历。', '',
             '## 解释边界',
             '- 事件窗口重叠、同簇事件重复使用背景/结果，样本非独立；不得解释为独立样本统计。',
             '- seed 是目的性样本而非事件普查；这不是机制检验、因果检验、策略回测或买点标签。',
             '- POST 仅描述后验路径，不可回流到实时特征。', '',
             '## 运行产物',
             '- CSV：`data/cfis/is2b_event_timeline.csv`（本次 --out 指定）；脚本默认 stdout，可用 --out 自选路径。',
             '- 输入为冻结 weekly_full、seed 和可选 is2a_index_baseline；未重采集、未重建上游。', '',
             '## 本次覆盖', f'- POST4 状态：{dict(counts)}',
             f'- PRE 缺失：{sum(r["pre_status"] != "AVAILABLE" for r in rows)}',
             f'- POST4 价格基准可用：{sum(r["post4_index_status"] == "AVAILABLE" for r in rows)}', '',
             '|事件|可见同簇成员|PRE|POST4 状态|EW 复利代理|价格基准|',
             '|---|---|---|---|---|---|']
    for r in rows:
        lines.append('|{}|{}|{}|{}|{}|{}|'.format(r['event_id'], r['visible_cluster_ids'], r['pre_week'],
                     r['post4_status'], r['post4_ew_compound_proxy'], r['post4_index_compound']))
    lines += ['', '## PRE → POST4 变化（观测，非因果）',
              '|事件|breadth PRE|breadth POST4均值|融资 PRE|融资 POST4均值|',
              '|---|---|---|---|---|']
    for r in rows:
        lines.append('|{}|{}|{}|{}|{}|'.format(r['event_id'], r['pre_ax_breadth'],
                     r['post4_mean_ax_breadth'], r['pre_m_fin_flow_w'], r['post4_mean_m_fin_flow_w']))
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', default=str(ROOT / 'docs/research/cfis/macro_events_seed.json'))
    parser.add_argument('--weekly', default=str(ROOT / 'data/cfis/weekly_full_202201_202610.csv'))
    parser.add_argument('--baseline', default=str(ROOT / 'data/cfis/is2a_index_baseline.csv'),
                        help='optional; use empty string to disable')
    parser.add_argument('--out', default='-', help='CSV path, default stdout')
    parser.add_argument('--report', default=str(ROOT / 'docs/research/cfis/IS2B_TIMELINE.md'))
    args = parser.parse_args()
    with open(args.seed, encoding='utf-8') as handle:
        seed = json.load(handle)
    events = seed['events'] if isinstance(seed, dict) else seed
    baseline = read_csv(args.baseline) if args.baseline and Path(args.baseline).exists() else []
    rows = build_timeline(events, read_csv(args.weekly), baseline)
    handle = sys.stdout if args.out == '-' else open(args.out, 'w', newline='', encoding='utf-8')
    try:
        writer = csv.DictWriter(handle, fieldnames=fields())
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if handle is not sys.stdout:
            handle.close()
    Path(args.report).write_text(report(rows), encoding='utf-8')
    print(f'timeline events={len(rows)}; report={args.report}', file=sys.stderr)


if __name__ == '__main__':
    main()
