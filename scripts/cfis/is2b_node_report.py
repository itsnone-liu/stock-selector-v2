#!/usr/bin/env python3
"""Summarize fixed-rule exploratory candidate nodes and independent outcomes."""
import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', default=str(ROOT / 'data/cfis/is2b_nodes.csv'))
    ap.add_argument('--outcomes', default=str(ROOT / 'data/cfis/is2b_node_outcomes.csv'))
    ap.add_argument('--report', default=str(ROOT / 'docs/research/cfis/IS2B_NODE_RESULTS.md'))
    args = ap.parse_args()
    nodes, outcomes = read(args.nodes), read(args.outcomes)
    lines = ['# CF-IS 首轮候选节点结果（探索）', '',
             '规则：IS2B_NODE_SPEC_V1.md。已看过历史，非预注册或未见样本验证；不调阈值。',
             'A早期平衡/B接力启动/C修复确认仅候选研究节点，不是已验证买点。', '',
             f'独立状态机episode数：{len(set(r["episode_id"] for r in nodes))}；节点行数：{len(nodes)}。',
             f'阶段行数：{dict(Counter(r["stage"] for r in nodes))}。', '',
             '## 节点', '|episode|stage|week|assessment_at|known events|', '|---|---|---|---|---|']
    for r in nodes:
        lines.append('|'+ '|'.join(r.get(k, '') for k in ('episode_id','stage','week','assessment_at','known_event_ids'))+'|')
    lines += ['', '## 每个节点的独立结果（未扣费用的价格路径）',
              '|episode|stage|horizon|status|return|MAE|MFE|首次+5%交易日|',
              '|---|---|---|---|---|---|---|---|']
    for r in outcomes:
        cells = [r.get(k, '') for k in ('episode_id', 'stage', 'horizon', 'status')]
        for key in ('return', 'MAE', 'MFE'):
            value = r.get(key, '')
            cells.append(f'{float(value):+.2%}' if value else '')
        cells.append(r.get('first_5pct_days', ''))
        lines.append('|' + '|'.join(cells) + '|')
    lines += ['', '## 首轮观察与限制',
              '- 本版只有6个A episode，B3/C2，远不足以评估稳定性或校准概率。宏观关联字段为空不表示无宏观事件，只表示有限seed过去28天未匹配。',
              '- A的低点趋稳与压力缓和不等于底已形成：2022-W14和2024-W01随后4周价格路径分别下跌约9.31%和12.10%，MAE约14.82%和14.44%。',
              '- 等待确认也不天然更优：2024-W08 episode的C节点随后4周约-3.05%，相比早期A已失去部分修复空间。不可凭2个C推断普遍效果。',
              '- 2024-W29/B随后8周约+9.26%，期间MAE约-7.22%；正期末结果仍可能经历显著不利路径。',
              '- 上述是节点后固定持有的市场价格路径，未应用状态机失效止损；节点失效不代表结果表中已经执行卖出，不可当策略收益。',
              '- 8/12周的WEEKLY_GAP可能来自节假日长休与端点间隔>14天的保守阻断，不代表已确认数据损坏。没有官方日历前仍留空。',
              '- 246个周表行只有139个历史特征完整；价格样本截止2026年4月且2023年有长缺口，缺少节点的时期不能解释为规则判定没有机会。',
              '', '## 独立结果表状态', '```json', json.dumps(dict(Counter(r.get('status', '') for r in outcomes)), ensure_ascii=False), '```', '',
              '结果逐行字段与定义见 data/cfis/is2b_node_outcomes.csv（可复现，ignored）及结果脚本。',
              '不同stage来自同轮行情，不能当独立样本；阶段间比较是时间与选择条件共同变化，不是随机比较。',
              '当前未建立价格基线/匹配对照、宏观事件增量或机构层完整证据；不报显著性、胜率或校准概率。',
              '首个后评估交易日开盘仅时间顺序代理，无费用滑点，不等于策略可实现收益。',
              '指数历史长缺口、原子时间未知、右删失必须保留，不能为了多出节点放宽标准。',
              '下一步核对每个节点路径及失败/滞留案例，再固定小范围比较方案；本结果不授权生产接入。']
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines)+'\n')
    print(f'nodes={len(nodes)}, episodes={len(set(r["episode_id"] for r in nodes))}; report={path}')


if __name__ == '__main__':
    main()
