#!/usr/bin/env python3
"""Post-hoc four-week coverage diagnostic; never changes features or CF-IS rules."""
import argparse
import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


outcomes = load_sibling('is2b_node_outcomes')
rules = load_sibling('is2b_candidate_nodes')
CONDITIONS = ('dd12_deep', 'low_stable', 'pressure_easing', 'margin_easing', 'support_nonnegative')
CATEGORIES = ('actual_A', 'merged_A_condition', 'feature_incomplete', 'failed_A_conditions')
FIELDS = outcomes.FIELDS + ['observation_index', 'rally_4w', 'category', 'coverage_status',
                            'feature_reason', 'a_candidate', *CONDITIONS, 'failed_conditions',
                            'unknown_conditions', 'active_episode_status', 'active_episode_id',
                            'active_episode_stage', 'episode_exit_reason']


def tri(value):
    if value is True or str(value).lower() in ('true', '1'):
        return True
    if value is False or str(value).lower() in ('false', '0'):
        return False
    return None


def conditions(feature):
    def numeric(key, predicate):
        value = rules.number(feature.get(key))
        return None if value is None else predicate(value)
    return dict(dd12_deep=numeric('dd12', lambda x: x <= -.05),
                low_stable=numeric('low_change', lambda x: x >= -.01),
                pressure_easing=tri(feature.get('pressure_easing')),
                margin_easing=tri(feature.get('margin_easing')),
                support_nonnegative=numeric('l1_mean2', lambda x: x >= 0))


def replay_active(features, nodes):
    """Independent causal replay of existing nodes, loss and observed-week expiry.

    No outcome data or future nodes are consulted. Missing current close makes
    coverage unknown until an observable exit/expiry or a new actual A resolves it.
    Stages remain active after C, matching the fixed rule.
    """
    by_week = {}
    for node in nodes:
        by_week.setdefault(node['week'], []).append(node)
    active = None
    uncertain = False
    result = []
    for i, f in enumerate(features):
        exit_reason = ''
        known = rules.truth(f.get('current_known')) and rules.timestamp(f.get('assessment_at')) is not None
        close = rules.number(f.get('index_close'))
        if active:
            if known and close is not None and active['low'] is not None and close < active['low'] * .97:
                active, uncertain, exit_reason = None, False, 'ANCHOR_LOSS'
            elif i - active['i'] >= 12:
                active, uncertain, exit_reason = None, False, 'EXPIRED_12'
            elif not known or close is None or active['low'] is None:
                uncertain = True
        visible = [n for n in by_week.get(f['week'], [])
                   if rules.timestamp(n.get('assessment_at')) is not None
                   and rules.timestamp(f.get('assessment_at')) is not None
                   and rules.timestamp(n['assessment_at']) <= rules.timestamp(f['assessment_at'])]
        for node in visible:
            if node['stage'] == 'A':
                active = dict(i=i, low=rules.number(node.get('anchor_low')),
                              episode_id=node['episode_id'], stage='A')
                uncertain = active['low'] is None
            elif active and node['episode_id'] == active['episode_id']:
                active['stage'] = node['stage']
        result.append(dict(active_episode_status='unknown' if uncertain else ('active' if active else 'none'),
                           active_episode_id=active['episode_id'] if active else '',
                           active_episode_stage=active['stage'] if active else '',
                           episode_exit_reason=exit_reason))
    return result


def build(features, nodes, weeks, index_rows):
    """One synthetic node per current-known week; strict original outcome rows."""
    selected = [(i, f) for i, f in enumerate(features) if rules.truth(f.get('current_known'))]
    synthetic = [dict(episode_id='COVERAGE-' + f['week'], stage='SYNTHETIC',
                      week=f['week'], assessment_at=f['assessment_at']) for _, f in selected]
    evaluated = outcomes.build(synthetic, weeks, index_rows, horizons=(4,))
    active = replay_active(features, nodes)
    actual = {n['week'] for n in nodes if n['stage'] == 'A'}
    rows = []
    for (i, feature), outcome in zip(selected, evaluated):
        checks = conditions(feature)
        complete = feature.get('coverage_status') == 'COMPLETE'
        if feature['week'] in actual:
            category = 'actual_A'
        elif rules.truth(feature.get('a_candidate')):
            category = 'merged_A_condition'
        elif not complete or any(v is None for v in checks.values()):
            category = 'feature_incomplete'
        else:
            category = 'failed_A_conditions'
        row = dict(outcome)
        row.update(observation_index=i, rally_4w=(outcome['return'] >= .05
                   if outcome['status'] == 'COMPLETE' else ''), category=category,
                   coverage_status=feature.get('coverage_status', ''),
                   feature_reason=feature.get('feature_reason', ''),
                   a_candidate=feature.get('a_candidate', ''),
                   failed_conditions=';'.join(k for k, v in checks.items() if v is False) if complete else '',
                   unknown_conditions=';'.join(k for k, v in checks.items() if v is None),
                   **{k: 'unknown' if v is None else v for k, v in checks.items()}, **active[i])
        rows.append(row)
    return rows


def rally_runs(rows):
    """Adjacent original feature observation indices, not independent events."""
    indices = sorted(int(r['observation_index']) for r in rows if r['rally_4w'] is True)
    return sum(i == 0 or value != indices[i - 1] + 1 for i, value in enumerate(indices))


def report(rows):
    complete = [r for r in rows if r['status'] == 'COMPLETE']
    rallies = [r for r in rows if r['rally_4w'] is True]
    lines = ['# IS2B 反弹覆盖诊断（自动生成）', '',
             '固定规则不变；rally_4w 仅为后验标签，不写回前置特征或节点。',
             '每个 current_known=true 周作为 synthetic 节点调用 is2b_node_outcomes.build，严格 assessment 后进入、4完整交易周；原 status/return 原样继承，非 COMPLETE 标签留空（未知，非 false）。', '',
             f'- 当时已知周：{len(rows)}；4周完整结果：{len(complete)}；未知结果：{len(rows)-len(complete)}。',
             f'- 完整结果中期末 return >= 5% 标签周：{len(rallies)}；描述性占比：{len(rallies)/len(complete):.2%}。' if complete else '- 没有完整结果。',
             f'- 相邻标签周 run 数：{rally_runs(rows)}（按原 features 观测序号相邻合并）。',
             '- 重叠标签周共享未来行情，不是独立样本；run 也不是经验证独立事件。上述占比不是规则召回率、交易胜率或独立事件成功率。', '', '## 结果状态', '']
    lines += [f'- {k}: {v}' for k, v in sorted(Counter(r['status'] for r in rows).items())]
    lines += ['', '## 前置分类', '', '| 类别 | 全部已知周 | rally标签周 | rally周举例（ISO week） |', '|---|---:|---:|---|']
    for category in CATEGORIES:
        subset = [r for r in rallies if r['category'] == category]
        lines.append(f'| {category} | {sum(r["category"] == category for r in rows)} | {len(subset)} | ' + ', '.join(r['week'] for r in subset[:12]) + ' |')
    lines += ['', 'actual_A 为实际节点；merged_A_condition 仅指当周 a_candidate=true 但未产生新A，并非“无覆盖”。loss/到期周也可能属于此栏，须看 active 状态。',
              'feature_incomplete 不视为规则拒绝；完整但不触发A的所有周均保留。', '', '## 当时已有 episode（各阶段都可覆盖，不借未来）', '',
              '按实际A节点独立重放：已知 close < anchor_low × 0.97 退出，原观测序号 A+12 到期，B/C 节点仅更新当时可见stage；含本周新A。无法确认则 unknown；缺失观察之后即使后来close恢复，期间是否已失效仍不确定，直到可确认退出/到期或新实际A。此为保守覆盖确认，不声称未知期间原状态机必已退出。']
    for status in ('active', 'none', 'unknown'):
        subset = [r for r in rallies if r['active_episode_status'] == status]
        lines.append(f'- {status}: 全部 {sum(r["active_episode_status"] == status for r in rows)} 周；rally {len(subset)} 周；例：' + ', '.join(r['week'] + (':' + r['active_episode_stage'] if r['active_episode_stage'] else '') for r in subset[:12]))
    lines += ['', '## 多重A门槛失败（非互斥）', '', '仅 feature coverage_status=COMPLETE 周计失败；缺失条件标 unknown，不归 false。阈值照原规则：dd12<=-5%、low_change>=-1%、pressure_easing、margin_easing、l1_mean2>=0。', '', '| 条件 | 完整特征失败周 | 其中rally周 | rally例 |', '|---|---:|---:|---|']
    for condition in CONDITIONS:
        failed = [r for r in rows if condition in r['failed_conditions'].split(';')]
        subset = [r for r in failed if r['rally_4w'] is True]
        lines.append(f'| {condition} | {len(failed)} | {len(subset)} | ' + ', '.join(r['week'] for r in subset[:10]) + ' |')
    lines += ['', '完整逐周记录（含未涨、未知、失败列表及episode状态）：`data/cfis/is2b_coverage_diagnostic.csv`（ignored）。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag, default in [('features', 'data/cfis/is2b_features.csv'), ('nodes', 'data/cfis/is2b_nodes.csv'),
                          ('weekly', 'data/cfis/weekly_full_202201_202610.csv'),
                          ('index', 'docs/phase_i/evidence/market_index_000985.json'),
                          ('out', 'data/cfis/is2b_coverage_diagnostic.csv'),
                          ('report', 'docs/research/cfis/IS2B_COVERAGE_DIAGNOSTIC.md')]:
        parser.add_argument('--' + flag, default=str(ROOT / default))
    args = parser.parse_args()
    def read_csv(path):
        with open(path, encoding='utf-8-sig', newline='') as stream:
            return list(csv.DictReader(stream))
    with open(args.index, encoding='utf-8') as stream:
        index = json.load(stream)['rows']
    rows = build(read_csv(args.features), read_csv(args.nodes), read_csv(args.weekly), index)
    rules.write_csv(args.out, rows, FIELDS)
    Path(args.report).write_text(report(rows), encoding='utf-8')
    print(f'{len(rows)} known weeks; {sum(r["status"] == "COMPLETE" for r in rows)} complete; '
          f'{sum(r["rally_4w"] is True for r in rows)} rally labels; {rally_runs(rows)} adjacent runs')


if __name__ == '__main__':
    main()
