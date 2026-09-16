# V3 P0 可复现基线冻结（2026-09-16）

## 冻结对象

- tag：`pre-v3-p0-20260916`
- SHA：`9d3e136`
- 正式名称：**pre-V3 current-research baseline**（不是未经修改的旧系统原版）
- 旧系统语义取证：`docs/research/LEGACY_FORENSICS.md`；重构复刻模式为
  `legacy_reconstructed_v1`，同样不宣称二进制级原版。

capital-observer 同名 tag 冻结于 `98cbab5`。

## 冻结结果的已知无效项

此前组合回放和趋势分组输出保留用于复现，但不得作为生产晋升证据：

1. portfolio replay 在 T+1 开盘成交前使用了当日 15:05 regime，存在未来信息；
2. 候选先 `[:top_per_day]` 后排序，输入遍历顺序会影响成交；
3. 无费用、滑点及停牌/涨跌停可成交约束；
4. 今日流动性筛选回推历史，存在样本选择偏差；
5. 趋势事件窗口重叠，n 不是独立机会数；
6. no-monthly 实验没有限定底部三倍量事件和候选池生命周期，不能称底部池验证；
7. capital-observer 历史 facts 的 published_at 大量等同 effective_at，现阶段不能
   用于严格资金历史 PIT。

因此 `TREND_GATE_20260916.md`、`PORTFOLIO_REPLAY_20260916.md` 中的收益表仅是
**旧实现的探索性输出**；“无过滤价值”“信号真实”“底部池裁决”等强表述已撤回，
必须在 E1 修复执行、E2 同日同行业控制、事件去重及封存样本后重验。

## E1 执行模型

版本：`cn-a-share-eod-v1`

- 信号：T 日 15:05，全部候选统一排序后取 top-N；
- 成交：T+1 09:30 开盘参考价，使用订单携带的 T 日 regime，不读 T+1 收盘；
- 滑点：默认单边 5bps；佣金万3、最低5元；过户费万0.1；卖出印花税按
  2023-08-28 前后 0.1%/0.05%；
- 可成交性：无开盘/无bar视为停牌；开盘封涨停不买、封跌停不卖；无盘口队列，
  因此这是保守近似并在 limitations 标注；
- A股 T+1 lot；卖出阻断订单保留至次日重试；
- 每笔交易记录 gross_value、fees、net value、signal_date、signal_regime；
- 输出 input_snapshot_hash（配置、代码帧边界与末值轻量指纹），正式数据快照仍需
  后续 manifest/Parquet hash。

## P0 验收闸门

- 修改回放区间之后的数据，不改变区间内 trades/daily；
- 打乱股票输入顺序，不改变 trades/final_equity/input hash；
- 费用计入现金，买卖后账本守恒；
- 相同输入与固定配置输出一致；
- 全套 pytest 通过后才可生成 E1 新基线。
