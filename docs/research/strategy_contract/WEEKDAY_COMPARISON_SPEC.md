# 周一至周五动能比较规范

## 2026-09-17 裁定（最新，优先级最高）

### 比较口径（全局）

所有周线/部分周比较一律用**当期收盘 vs 前一期收盘**（close-to-close），不用当期开盘：避免跳空/低开把"高开低走/低开高走"误判为动能方向。落地字段：`prev_week_cc_pct`、`prev2_week_cc_pct`、`partial_week_cc_pct`、`momentum_context_positive`（前两周cc均>0；任一未知→None，不猜）。

### 周一/周二准入（沿用原版总体方向）

前期动能正向（前两周cc均>0）时：

| 早周情形 | Theory状态 | 说明 |
|---|---|---|
| 周一跌（部分周cc<=0）、非放量 | observation | 下跌不做部分周硬约束；放量跌由veto排除 |
| 周二反红（B路径） | observation | 裁定：反红可接受观察，不再是暂定eligible |
| 周二缩量小跌（C路径） | observation | 卖压衰减≠正向推动 |
| 周二放量双阴 | excluded | 连续放量下跌不考虑 |
| 早周上涨 | 部分周约束判滞涨 | 折算(cc/sessions×5)量>上周量 且 折算cc涨幅<上周cc×0.8 → excluded |
| 早周上涨、不滞涨、Legacy通过 | eligible | 形态判定维持 |

前期动能非正向或未知：回到Legacy形态判定（开盘口径复刻不改）。`passed` 语义不变；以上仅作用于 `eligibility_state` 派生层。

## 不变方向

每个交易日判断“本周截至当时的价格推进与资金投入，相比此前是增强、减弱还是转向”。星期分支用于处理证据进度，而非改变研究目标。

## Legacy

严格保持旧源码：

- 周一：W-FRI 最后一根部分周K与上一完整周比较；
- 周二：先过旧周一门槛，再走A/B/C；
- 周三/四：按已发生交易日 `/days×5` 折算涨幅与成交量；
- 周五：完整周比较；
- veto：旧v4.0分发层一票否决。

## Theory 待逐项裁决的比较轴

1. 上一完整周：回答当前推动相对上周是否增强；
2. 相同进度：回答本周前n个交易日相对上周前n日是否增强；
3. 计划交易日折算：短周使用真实计划交易日，不固定5；
4. 早周证据：周一/周二输出置信等级，不把单日噪声等同完整周结论。

Theory现在已并行输出上述证据，但尚不参与准入：`same_progress_return_delta_pct`、`same_progress_volume_ratio`、`planned_prorated_return_pct`、`planned_prorated_volume_ratio`、`early_week_evidence_strength`；周二另输出`tuesday_recovery_ratio`及是否收复周一收盘。之后单因素决定采用哪种准入，不得根据同一批收益反复拼公式。

## 已确认与未确认

已确认：周线必须比较此前；负向动能不进入主策略；形态和星期路径分开记录；收盘对收盘口径；周二B/C=observation；早周跌不做部分周硬约束、涨才判滞涨。

未确认：同进度比较具体窗口；短周折算公式（当前并行输出，planned_sessions 由快照提供）；连续放量下跌的精确阈值（当前沿用veto 1.5×与周二C缩量规则）。未确认项不得假装已定规则。
