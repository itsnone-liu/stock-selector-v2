# 第四批：行情生命周期与入场回放语义冻结

状态：语义冻结，待实现与门禁；不消费结果调参。
输入固定：`weekly_state_v1`、`pullback_v2`、核心月线池与日线行情。

## 1. 生命周期事件

生命周期是事件路径，不是强制线性流水线。同一行情允许循环：

`preparation -> breakout -> confirmation -> pullback -> reattack -> divergence -> decay -> end`

其中 `pullback -> reattack` 可重复；任意阶段可以跳过。每只股票同一生命周期使用稳定 `lifecycle_id`，不得将每日状态重复计为独立行情。

### 终止原因

- `monthly_exit`：月线池历史时点退出；
- `structure_break`：周线结构破坏；
- `data_end`：研究窗口结束右删失，不是行情失败；
- `max_observation`：超过统一最大观察窗口；
- `pool_gap`：池数据出现超出允许间隔的缺口。

`monthly_exit`、`structure_break`、`data_end` 必须分别落列；右删失必须保留 `right_censored=true`。

## 2. 四种入场策略

四种策略只在**同一批生命周期事件总体**上回放，不能各自筛选不同事件：

1. `direct_chase`：突破确认收盘入场；另存下一交易日可成交版本；保留原版涨幅 `<=3.5%` 对照与 unlimited 版本；
2. `wait_first_pullback`：首次健康缩量回调候选日；
3. `wait_support_hold`：首次支撑触及并确认止跌日；
4. `staged_entry`：小仓跟踪→回调加仓→确认后主仓，记录平均成本、资金占用、最大仓位。

收盘信号（`signal_close`）与下一交易日成交（`next_session_fill`）分开输出，不混用价格时点。

## 3. 统一观察与结果

第一轮所有策略使用相同观察窗口与成本模型；暂不加入止盈规则。结果包括实际/扣成本收益、MFE、MAE、创新高及所需交易日、失败路径。等待类必须分别记录：

- `fill_status` / `fill_date` / `fill_price`；
- `missed_upside`：因等待而错失上涨；
- `missed_upside_rate`；
- `not_filled_reason`。

未来结果只进入 outcome，不进入入场时特征。

## 4. 背景与参数边界

大盘、行业、聚类只记录为 context，不参与个股准入；第一轮不根据收益修改生产阈值。四种策略共享事件总体、行情路径、观察窗口与成本假设。

## 5. 工程输出

- `lifecycle_events`：每生命周期一行，含阶段序列、终止原因、右删失；
- `entry_replay`：每生命周期×策略一行，含收盘信号和次日成交两种视角；不默认落盘逐日持仓明细；
- 所有表按股票批次分区，manifest 记录上游 `weekly_state` 与 `pullback` 指纹链。

## 6. 验收顺序

人工行情至少覆盖：线性突破、跳过回调、回调再上攻循环、月线退出、结构破坏、窗口右删失、等待成交、等待错失、四策略同事件总体、收盘/次日成交价差。然后 50×3月、300×1年，最后才允许全量。
