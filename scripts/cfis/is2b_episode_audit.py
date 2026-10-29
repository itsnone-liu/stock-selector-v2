#!/usr/bin/env python3
"""Causal, read-only audit of frozen IS2B v1 features and nodes (not a strategy)."""
import argparse
import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('is2b_audit_candidate', Path(__file__).with_name('is2b_candidate_nodes.py'))
candidate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(candidate)
number, truth, timestamp = candidate.number, candidate.truth, candidate.timestamp
TRACE_FIELDS = ['week', 'week_end', 'assessment_at', 'current_known', 'complete',
                'episode_id', 'state_before', 'state', 'age', 'upgrade', 'termination',
                'index_close', 'anchor_close', 'anchor_low']
AT_A = ['dd12', 'ax_breadth', 'ax_part', 'margin_easing', 'l1_mean2',
        'pressure_easing', 'downside_pressure', 'low_change', 'index_week_return',
        'coverage_status', 'current_known', 'feature_reason']
SUMMARY_FIELDS = ['episode_id', 'A_week', 'B_week', 'C_week', 'terminate_week',
                  'terminate_status', 'right_censored', 'last_observed_week',
                  'observed_age', 'wait_B_weeks', 'wait_C_weeks', 'wait_B_to_C_weeks',
                  'wait_B_observed_weeks', 'wait_C_observed_weeks',
                  'wait_B_status', 'wait_C_status', 'anchor_close', 'anchor_low',
                  'terminate_close'] + ['at_A_' + k for k in AT_A]
ALIGN_FIELDS = ['episode_id', 'stage', 'week', 'week_end', 'assessment_at', 'anchor_week']


def read_csv(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def assert_aligned(actual, expected, label):
    """Order and multiplicity matter, not just sets of stage dates."""
    a = [tuple(str(r[k]) for k in ALIGN_FIELDS) for r in actual]
    b = [tuple(str(r[k]) for k in ALIGN_FIELDS) for r in expected]
    if a != b:
        raise ValueError(f'{label} node mismatch: replay={a!r}, expected={b!r}')


def replay(features):
    """Independent weekly replay. No trace cell is backfilled from a later week."""
    trace, summaries, nodes = [], [], []
    active = None
    previous_breadth = None
    for i, f in enumerate(features):
        known = truth(f.get('current_known')) and timestamp(f.get('assessment_at')) is not None
        complete = known and f.get('coverage_status') == 'COMPLETE'
        breadth = number(f.get('ax_breadth')) if complete else None
        close = number(f.get('index_close'))
        before = active['stage'] if active else 'NONE'
        upgrade = termination = ''
        age = i - active['i'] if active else ''
        row_episode = active
        if active:
            loss = known and close is not None and close < active['low'] * .97
            if loss or age >= 12:
                termination = 'LOSS' if loss else 'EXPIRED'
                s = active['summary']
                s.update(terminate_week=f['week'], terminate_status=termination,
                         terminate_close=close if known else '', right_censored=False)
                active = None  # consumes this week: no restart or upgrade
            elif complete:
                if active['stage'] == 'A':
                    part, ret = number(f.get('ax_part')), number(f.get('index_week_return'))
                    if breadth is not None and breadth >= .5 and part is not None and part >= 1 and ret is not None and ret > 0:
                        upgrade = 'B'
                elif active['stage'] == 'B':
                    if breadth is not None and breadth >= .5 and previous_breadth is not None and previous_breadth >= .5 and close > active['close']:
                        upgrade = 'C'
        elif complete and truth(f.get('a_candidate')):
            upgrade, age = 'A', 0
            s = dict.fromkeys(SUMMARY_FIELDS, '')
            s.update(episode_id='IS2B-' + f['week'], anchor_close=close,
                     anchor_low=number(f['index_low']), terminate_status='RIGHT_CENSORED',
                     right_censored=True)
            s.update({'at_A_' + k: f.get(k, '') for k in AT_A})
            summaries.append(s)
            active = dict(i=i, low=number(f['index_low']), close=close,
                          stage='A', summary=s, week=f['week'])
            row_episode = active
        if upgrade:
            active['stage'] = upgrade
            active['summary'][upgrade + '_week'] = f['week']
            if upgrade != 'A':
                active['summary']['wait_' + upgrade + '_weeks'] = age
            if upgrade == 'C':
                active['summary']['wait_B_to_C_weeks'] = age - active['summary']['wait_B_weeks']
            nodes.append(dict(episode_id=active['summary']['episode_id'], stage=upgrade,
                              week=f['week'], week_end=f['week_end'],
                              assessment_at=f['assessment_at'], anchor_week=active['week']))
        if row_episode:
            s = row_episode['summary']
            s.update(last_observed_week=f['week'], observed_age=age)
        trace.append(dict(week=f['week'], week_end=f['week_end'], assessment_at=f['assessment_at'],
                          current_known=known, complete=complete,
                          episode_id=row_episode['summary']['episode_id'] if row_episode else '',
                          state_before=before, state=active['stage'] if active else 'NONE', age=age,
                          upgrade=upgrade, termination=termination,
                          index_close=close if known else '',
                          anchor_close=row_episode['close'] if row_episode else '',
                          anchor_low=row_episode['low'] if row_episode else ''))
        previous_breadth = breadth
    for s in summaries:
        for stage in ('B', 'C'):
            reached = s[stage + '_week'] != ''
            s['wait_' + stage + '_observed_weeks'] = s['wait_' + stage + '_weeks'] if reached else s['observed_age']
            s['wait_' + stage + '_status'] = 'REACHED' if reached else ('RIGHT_CENSORED' if s['right_censored'] else 'TERMINATED_UNREACHED')
    return trace, summaries, nodes


def audit(features, frozen_nodes):
    trace, summaries, nodes = replay(features)
    assert_aligned(nodes, candidate.build_nodes(features), 'build_nodes')
    assert_aligned(nodes, frozen_nodes, 'frozen')
    return trace, summaries


def report_text(trace, summaries):
    def cell(value):
        return '—' if value == '' else str(value)
    lines = ['# IS2B Episode Audit', '',
             '由 frozen `is2b_features.csv` 与 `is2b_nodes.csv` 自动生成；独立逐周重放已与原 `build_nodes` 及 frozen nodes 的 episode、阶段、周、周末与 assessment 日期逐条精确核对，mismatch 立即 raise。未修改或调优 candidate 规则。', '',
             f'共 {len(trace)} 个观测周，{len(summaries)} 轮 episode；A/B/C = ' + '/'.join(str(sum(bool(s[k + '_week']) for s in summaries)) for k in ('A', 'B', 'C')) + '；LOSS = ' + str(sum(s['terminate_status'] == 'LOSS' for s in summaries)) + '；EXPIRED = ' + str(sum(s['terminate_status'] == 'EXPIRED' for s in summaries)) + '；右删失 = ' + str(sum(s['right_censored'] for s in summaries)) + '。', '',
             '## 逐轮表', '',
             '| Episode | A | B | C | 终止周 | 状态 | B等待/观测周 | C等待/观测周 | anchor close/low | terminate close |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for s in summaries:
        vals = [s['episode_id'], s['A_week'], s['B_week'], s['C_week'], s['terminate_week'], s['terminate_status'],
                f"{cell(s['wait_B_weeks'])}/{s['wait_B_observed_weeks']}",
                f"{cell(s['wait_C_weeks'])}/{s['wait_C_observed_weeks']}",
                f"{s['anchor_close']}/{s['anchor_low']}", s['terminate_close']]
        lines.append('| ' + ' | '.join(map(cell, vals)) + ' |')
    lines += ['', '## 口径与边界', '',
              '- 失效是候选状态机失效，不是策略执行、交易、止损或收益评价。状态到期后的上涨不归为该 episode 的恢复；C 亦不等于交易成功。',
              '- LOSS：当前已知 close < anchor low × 0.97；优先于 A+12 观测周 EXPIRED。到期/失效周不能重 A；同周只能升级一阶段。C 后仍合并至失效/到期。',
              '- age 从 A=0 起按输入观测周位置计数，坏周照常计龄但不能升级；坏周清空 previous breadth，不能跨坏周满足 C 的连续广度条件。未插补缺失周。',
              '- trace 仅含当时及过去信息，终止行保留该 episode/age，state 为 NONE；不在最后一行预知右删失，不回填未来 B/C。current_known 沿用原规则（含有效 assessment）；未知价格不作为已知信息输出。',
              '- summary 允许最终路径描述；wait_B/C_weeks 均为从 A 起观测周差，另给 B→C 周差；缺失阶段的 observed_weeks 为截止终止/样本末的观测 age，不当作成功等待时间。',
              '- 样本末仍活跃者标 RIGHT_CENSORED（右删失），不伪造终止周/价格；未到 B/C 的晚期 episode 同样明确右删失。已失效未到达者为 TERMINATED_UNREACHED，不标右删失。',
              '- at_A 快照包括 dd12、breadth、part、margin easing、l1、pressure 等原始特征；全量见 summary CSV。使用 frozen 可见性代理，不宣称历史 vintage PIT 保证。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', default=str(ROOT / 'data/cfis/is2b_features.csv'))
    parser.add_argument('--nodes', default=str(ROOT / 'data/cfis/is2b_nodes.csv'))
    parser.add_argument('--trace-out', default=str(ROOT / 'data/cfis/is2b_episode_trace.csv'))
    parser.add_argument('--summary-out', default=str(ROOT / 'data/cfis/is2b_episode_summary.csv'))
    parser.add_argument('--report-out', default=str(ROOT / 'docs/research/cfis/IS2B_EPISODE_AUDIT.md'))
    args = parser.parse_args()
    trace, summaries = audit(read_csv(args.features), read_csv(args.nodes))
    candidate.write_csv(args.trace_out, trace, TRACE_FIELDS)
    candidate.write_csv(args.summary_out, summaries, SUMMARY_FIELDS)
    report = Path(args.report_out)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(report_text(trace, summaries), encoding='utf-8')
    print(f'weeks={len(trace)} episodes={len(summaries)} nodes={sum(bool(r["upgrade"]) for r in trace)} ' +
          ' '.join(f'{status}={sum(s["terminate_status"] == status for s in summaries)}' for status in ('LOSS', 'EXPIRED', 'RIGHT_CENSORED')))


if __name__ == '__main__':
    main()
