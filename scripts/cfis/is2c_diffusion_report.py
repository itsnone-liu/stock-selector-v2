#!/usr/bin/env python3
"""Descriptive independent-diffusion comparison, never a causal/strategy claim."""
import csv
from collections import Counter
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[2]


def main():
    with open(ROOT/'data/cfis/is2c_diffusion_entries.csv') as f: entries=list(csv.DictReader(f))
    with open(ROOT/'data/cfis/is2c_diffusion_outcomes.csv') as f: outcomes=list(csv.DictReader(f))
    lines=['# CF-IS 独立扩散入口首轮比较','',
           '固定规则见 IS2C_DIFFUSION_SPEC_V1.md；已看过历史的探索，非样本外/预注册。独立于旧A，不修改旧A阈值。',
           'AMOUNT_ONLY/PRICE_ONLY是忽略其他门槛的嵌套对照，并非互斥组；ALL_ELIGIBLE逐周背景不是独立事件池。',
           '各臂单独合并连续触发，长期结果仍重叠；不同组数量和所处时期不同，不能把组中位数差当增量因果。','',
           '## 覆盖',f'- 入口行数：{dict(Counter(r["arm"] for r in entries))}',
           f'- 结果状态：{dict(Counter(r["status"] for r in outcomes))}',
           '- 独立指数仅至2026-04-30；右删失/缺口留空，不补0。金额只是成交活动，不代表净流入或具体主体。','',
           '## 分组路径描述','|arm|月|完整数|总行数|期末中位|MAE中位|MFE中位|期末范围|','|---|---|---|---|---|---|---|---|']
    for arm in ('DIFFUSION','AMOUNT_ONLY','PRICE_ONLY','ALL_ELIGIBLE'):
        for h in ('3','6','12'):
            group=[r for r in outcomes if r['arm']==arm and r['horizon_months']==h]
            ok=[r for r in group if r['status']=='COMPLETE']
            vals=[float(r['return']) for r in ok]
            cells=[arm,h,str(len(ok)),str(len(group))]
            cells += [f'{median(float(r[k]) for r in ok):+.2%}' if ok else '' for k in ('return','MAE','MFE')]
            cells += [f'{min(vals):+.2%} ~ {max(vals):+.2%}' if vals else '']
            lines.append('|'+'|'.join(cells)+'|')
    lines += ['','## 扩散入口逐项结果','|week|月|entry|end|status|return|MAE|MFE|首次+10%交易日|', '|---|---|---|---|---|---|---|---|---|']
    for r in outcomes:
        if r['arm']!='DIFFUSION':continue
        cells=[r[k] for k in ('week','horizon_months','entry_date','end_date','status')]
        cells += [f'{float(r[k]):+.2%}' if r[k] else '' for k in ('return','MAE','MFE')]
        cells += [r['first_10pct_days']]
        lines.append('|'+'|'.join(cells)+'|')
    lines += ['','## 首轮判断：同步门槛的覆盖限制',
              '- 当前DIFFUSION两条均在2025年7/8月同一推进阶段，长窗口高度重叠，不能当两轮独立成功。12月结果均删失，不据此声称扩散胜率更高。',
              '- 本版没有触发2024年秋的DIFFUSION：W39价格突破但10日金额达标仅4日，W40为5日；W41金额已9日达标但周广度跌回0.5以下，随后W42/W43因原子可用性未知阻断共同窗口。',
              '- 这表明同时要求金额持续、两周广度及当周价格新高可能错过顺序发生的接力过程；不是2024秋没有扩散，也不能据未触发否定用户的历史观察。',
              '- v1固定保留为同步状态描述，不为了命中2024放宽7/10阈值。若继续研究顺序过程，应独立定义扩张发生后若干周内的承接/再推进路径，先固定再比较，不能悄悄替换本版。',
              '', '## 边界与判断要求',
              '- 只评市场级未扣费固定窗口路径，不执行止损/分批/持仓，不是策略收益；首开盘仅时间代理。',
              '- 价格原始长缺口与>14日保守守卫会损失覆盖；没有数据的时期不是规则否定机会。',
              '- 规则中1.2倍与7/10仅一版探索门槛，不为出现924或更多正收益调整。',
              '- 如扩散入口恰在急涨之后，需看MAE/等待/空间而非只看期末正收益；若仅少量episode，不判胜率更高。',
              '- 下一步区分首次扩张、回落再扩散与高额退潮；这些阶段尚未被当前首入口规则完整表达。']
    p=ROOT/'docs/research/cfis/IS2C_DIFFUSION_RESULTS.md';p.write_text('\n'.join(lines)+'\n');print(p)

if __name__=='__main__':main()
