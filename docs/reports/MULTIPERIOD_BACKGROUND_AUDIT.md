# 多周期背景覆盖审计(便宜诊断, 2026-09-21)

目的: 四模型(A0/A1/B0/B1)实验前检验观察日背景状态分布是否丰富。数据=momentum_panel_v3
(2024-01-02→2026-09-01, 5,191 股, 日级; 观察日=面板当日行, 重新读取非开段日状态)。
覆盖: 三时点 b19-b22 且 40 日窗在面板内: breakout 20,563 / shrink 16,756 / stab 10,275。

## 一、核心发现

| 维度 | 分布 | 判定 |
|---|---|---|
| 月线池 | **三时点观察事件 100% in**(46,465/46,465) | **无变化, 不可检验** |
| 周线 passed | True 70.1%/21.2%/48.9%(按 bo/sh/st), False/空其余 | 丰富, 可检验 |
| momentum_context | True 30%/56%/46% | 丰富 |
| base_pattern | double_positive/none/negative_to_positive 等多类 | 丰富 |
| 周线 veto | 0.3%/11.3%/4.8% | 稀少(单独不可检) |
| t_eff/l_eff/量比(连续) | 分位跨度宽(如 bo t_eff p5=1.0 p95=22.4) | 丰富 |

月线维度结论: 生命周期开段即要求月线 in 且月池状态持续, 观察日全 in——
**本样本无法检验月线背景差异, 应明确承认识别范围不足**(设计上 A1 的月线分量=常数, 无信息)。周线维度分布足够丰富, 可支撑背景增量检验。

## 二、量价拆分(遵用户要点: current_momentum 量价混合不可整装入 A1)

- **价格侧候选(可入 A1)**: weekly_passed(布尔), weekly_base_pattern(分类),
  momentum_context_positive(布尔), weekly_eligibility_state(分类),
  t_eff/l_eff(周度效率, 连续), week_realized_pct, prev_week_cc_pct
- **量能侧候选(归 B1 的增量或另行拆分)**: volume_ratio_vs_prev_week,
  planned_prorated_volume_ratio
- 交叉格子: in|True 48.3%, in|False 40.5%, in|空 11.2%(空=周证据未成熟的短周行)

## 三、对四模型设计的修订建议(待审)

1 A0=日线价格(已冻结); B0=A0+日线量能(旧对照) —— 不变;
2 **A1=日线价格+周线价格侧背景**(月线分量因全 in 无信息, 不入);
   B1=A1+日线量能 —— 检验掌握周线价格背景后日线量能的额外价值;
3 周线量能侧(volume_ratio_vs_prev_week 等)是否并入 B1 或单独 B2, 需在设计冻结前定夺;
4 本审计仅统计分布, 未建模未检验未挑选; 分组/特征正式冻结于设计文档。

边界: 开发期; 非因果; 非收益证明; 存活偏差保留; 面板自身口径见其 manifest。