# 第四批：行情生命周期与入场回放语义冻结（精确定义版）

状态：语义冻结（含开发级精确定义），待用户审查后进入编码门禁。
上游固定：

```text
pullback_run_spec_hash     = 68cad4022bec6a8b
event_rule_version         = pullback_stage2_v1
outcome_contract_version   = right_censored_v2
weekly_state_run_spec_hash = e2cf0918238fc95c
```

第四批拆分两个连续提交：

1. `lifecycle`：只生成行情生命周期事实（本文件 §1-§4），完成门禁；
2. `entry-replay`：冻结 §5-§9 入场细节后消费生命周期，不重建生命周期。

---

## §1 生命周期起点与重开（回答问题 1）

- **起点（anchor_day）**：首个满足 regime_active 的交易日，其中
  `regime_active(d) = 月线池(d) == "in" AND 周线trend(d) ∈ {intact, starting_to_damage}`。
  周线 trend 按当日对齐（双轴表每交易日一行，同 pullback 契约）。
  数据不足 breakout_lookback+1 日（warmup）之前不得开段。
- 若 anchor 当日收盘已满足突破条件（§2），anchor 同时记为 breakout_day，
  preparation 被跳过（stage_sequence 以 breakout 开头）。
- **结束后的重开**：生命周期关闭后的下一个满足 regime_active 的交易日
  开新段。月线 out→in、pool_gap 恢复 in、max_observation 后仍 active，
  都在满足 regime_active 当日重开新段；lifecycle_id 随 anchor_day 变化，
  永不复用。

## §2 阶段布尔条件与同日记录顺序（回答问题 2）

全部条件只使用截至当日收盘的证据：

| 阶段 | 布尔条件 |
|---|---|
| preparation | regime_active 且本段尚未突破（anchor 起） |
| breakout | `close(d) > max(close[d-20:d])`（shift(1) 排除当日）且为本段首次 |
| confirmation | breakout_day **之后**首个 `close >= breakout_day close`（严格后一日；次日满足即次日） |
| pullback | pullback_v2 事件 `first_day ∈ [anchor_day, end_day]`（窗口包含，不重检测、不重去重） |
| reattack | **某次回调事件开始后**（first_day 之后）的**首次** `close(d) > max(close[d-20:d])`；与 breakout 同一规则复用；可以恰好发生在该回调事件以 new_high 结束的当日；每次独立回调至多记一次，并记录 `reattack_pullback_event_ids`（与 reattack_days 一一对应） |
| divergence | `momentum(d) == heavy_volume_decline AND trend(d) ∈ OK`（周轴当日对齐） |
| decay | `trend(d) == starting_to_damage`（首个出现日） |

**同日冲突记录顺序（固定）**：终止判定 > breakout/reattack > confirmation
> 回调事件进入 > divergence > decay。终止当日不再记录新阶段；其余同日
可并存，stage_sequence 按此顺序追加。`pullback→reattack` 可循环任意次；
所有阶段皆可跳过。

**阶段去重（固定）**：preparation、breakout、confirmation、divergence、
decay 每个生命周期只记录**首次**成立日（连续多日满足不重复追加，含连续
放量下跌不得每天重复记“分歧”）；pullback 每个独立回调事件各记一次；
reattack 每次独立回调各至多记一次。

## §3 终止原因与优先级（回答问题 3）

同日并发按固定优先级分诊，只记一个 end_reason：

```text
pool_gap > monthly_exit > structure_break > max_observation > data_end
```

| 原因 | 条件 | 专列 |
|---|---|---|
| pool_gap | 月线池状态 None（三态 in/out/None）连续 > 5 个交易日，end_day=缺口第 6 日；缺口 ≤5 日期间生命周期继续记录阶段（unknown 仅无证据，不得判失效，同 EpisodeTracker 语义） | — |
| monthly_exit | 池状态显式 "out" | end_monthly_exit=true |
| structure_break | 当日周线 trend == broken | end_structure_break=true |
| max_observation | `session_count = end_pos - anchor_pos + 1 >= 120`，即含 anchor 恰好第 120 个交易日内结束 | — |
| data_end | 数据末尾仍 active | end_data_end=true, right_censored=true（右删失，不是行情失败） |

## §4 生命周期参数（回答问题 4）

```text
WEEK_TREND_OK        = {intact, starting_to_damage}  # regime/divergence 判定唯一集合
breakout_lookback    = 20   # 与 pullback high_lookback 同源，不另设阈值
max_observation_days = 120  # 生命周期级（回调事件的 40 是事件级，不得混用）
pool_gap_tolerance   = 5    # 池 None 连续容忍交易日数
rule_version         = lifecycle_stage4_v1
```

参数写入 run_spec；第一轮不依据结果调整。

## §5 直接追入（回答问题 5）

- 消费 lifecycle.breakout_day 作为 signal_day（=现有日线触发
  `close > 前20日收盘高` 的首次成立日，不另造触发器）。
- **3.5% 按信号日当日涨幅**：`close(t)/close(t-1) - 1`，与原版
  "当日涨幅>3.5%不追" 同口径。
- capped 变体：涨幅 > 3.5% 不入场，capped_not_entered_reason=
  chase_gain_cap_exceeded；unlimited 变体：恒入场。两变体同列并存。

## §6 等待首次回调（回答问题 6）

- 只能使用 **breakout_day 之后开始**（first_day > breakout_day）的、
  属于本生命周期的 pullback_v2 回调事件；突破前的回调不算。
- 等待期限 = 生命周期结束（fill_deadline=lifecycle_end），不设固定天数；
  生命周期内无回调 → not_filled_reason=no_pullback_before_end。
- fill 日 = 回调事件内首个缩量日（pullback 明细 shrink_volume=true，
  量比 < 0.8）；事件内无缩量日 → no_shrink_day。

## §7 支撑止跌（回答问题 7）

- signal 日 = 回调事件 stabilization_day（收盘证据，止跌确认）。
- **两个视角分开输出，不混用**：
  - signal_close：stabilization_day 收盘 ± 滑点；
  - next_session_fill：次日开盘价，经 execution_feasibility 一字涨停
    阻断判定。
- 无 stabilization → not_filled_reason=no_stabilization。

## §8 分批进入（回答问题 8）

仓位比例预先冻结，不看结果选择：

```text
T1 = 30% 于 breakout_day 收盘（小仓跟踪）
T2 = 30% 于首个回调缩量日（同 §6 fill 日；无则缺省不补）
T3 = 40% 于 reattack 日（再创新高；无则缺省不补）
```

记录 avg_cost（加权含滑点）、capital_position_days（Σ 权重×持有交易日）、
max_position（累计权重，≤1.0）；只落 tranche 级摘要，不落每日持仓明细。

## §9 统一观察口径、成本与可成交性（回答问题 9）

- 观察窗口：5/10/20 交易日，从**各自 fill 日**起算；四种策略同一窗口
  定义；窗口超出数据末尾 → outcome_complete=false（右删失，缺失样本
  不进失败分母）。
- 成本模型：`cn-a-share-eod-v1`（佣金 0.03% 最低 5 元、滑点 5bp、
  过户费 0.001%、印花税卖出单边 0.05%）。ret_net = 毛收益 − 往返费用。
- 涨跌停无法成交：次日开盘一字涨停（limit_ratio：300/301/688=20%，
  4/8 开头=30%，其余 10%）→ not_filled + open_limit_up_buy_blocked；
  停牌/缺 bar → missing_bar_or_suspended。不使用前向填充的陈旧价格。
- 第一轮不加止盈规则；所有策略共享事件总体、路径、窗口与成本。

## §10 入场回放执行细节（lifecycle 门禁期间冻结，暂不编码）

1. **双视角全策略**：四种策略都必须分别输出收盘理论成交（signal_close）
   与次日开盘可成交（next_session_fill）两列组，不得只对支撑止跌定义。
2. **模拟资金**：固定每个生命周期 100,000 元初始资金；最低 5 元佣金按
   此换算为收益率影响。
3. **卖出价**：观察期第 5/10/20 个交易日收盘价，暂不执行其他退出规则。
4. **分批口径**：5/10/20 日窗口从**第一笔成交日**起算；收益分母=初始
   总资金（10 万），未投入现金收益记 0；同时保留各批次单独表现列。
5. **特殊涨跌停近似**：无历史 ST/特殊处理状态数据，limit_ratio 为近似
   口径（300/301/688=20%、4/8=30%、其余 10%，5% 特殊限制不可识别），
   输出必须标注 limitation=approximate_limit_ratio，不得声称完全真实
   可成交。
6. **等待成本三指标**（补足 missed_upside 只记 0/W 的盲区）：
   - wait_window_max_gain_pct：等待期间（breakout_day..fill 日前一日）
     最高收盘相对突破收盘的涨幅；
   - fill_price_vs_breakout_pct：成交价相对突破收盘的改善（负）或恶化
     （正，即买得更贵）；
   - wait_days：突破日到成交日的交易日数。
7. **未成交原因分列统计**：no_pullback_before_end、no_stabilization、
   no_shrink_day、open_limit_up_buy_blocked、missing_bar_or_suspended、
   right_censored 分别计数，不得统一归并为“未成交失败”。

## §11 等待错失的基准与公式（回答问题 10）

```text
基准日   = breakout_day（等待起点）
参照价   = breakout_day 收盘
deadline = 本生命周期 end_day（回放前冻结）
窗口上涨 W = max(close[breakout_day .. end_day]) / close[breakout_day] - 1
missed_upside_pct  = 0                    （已成交）
                    = W                   （未成交）
missed_upside_rate = missed_upside_pct / W （W=0 时记 0；∈[0,1]）
```

等待成本另见 §10 第 6 条三指标，二者并存、不得互相替代。

## §12 输出与指纹

- `lifecycle_events`：1 行/生命周期（LIFECYCLE_COLUMNS 冻结）；
- `entry_replay`：1 行/生命周期×策略，direct_chase 行内 capped/unlimited
  列组并存；收盘信号与次日成交两视角分列；
- manifest 链：run_spec 记录 weekly_state 与 pullback 的 run_spec_hash、
  事件规则版本三元组与本批 rule_version；批次分区、断点续跑、数据冻结
  校验与既有 stage 相同。

## §13 验收顺序

人工行情测试（线性突破、跳过准备、回调再上攻循环、五种终止、确定性、
无未来泄漏、四策略同总体、两视角价差、cap/unlimited、成交/错失、
分批守恒）→ 50×3月 → 300×1年 → 全量。
