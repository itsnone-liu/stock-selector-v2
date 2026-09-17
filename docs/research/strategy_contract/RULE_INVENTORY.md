# 规则清单与状态契约

## 月线层

- `monthly_provisional_state`：包含事件月截至当日收盘，决定动态池进出。
- `monthly_completed_state`：仅使用已结束月份，作为解释字段。
- 后续补：`monthly_state_changed_this_month`、均线间距、当月推动幅度。
- 当前主池实现仍为 provisional；completed 等解释字段未实现，列为开放项。

## 周线层

方向固定：周一至周五均判断当周相对此前的资金动能。优化只研究比较基准、折算和早周证据，不取消相对比较。

输出四态：

| 状态 | 含义 | 是否产生主策略候选 |
|---|---|---|
| eligible | 周线正向准入 | 是，可继续看日线 |
| observation | 未达到正向准入、但无明确负向否决 | 否，仅观察 |
| excluded | 明确负向/veto | 否 |
| unknown | 数据不足 | 否，且不计作失败 |

Legacy 当前映射：passed=True→eligible；veto→excluded；passed=False→observation；None→unknown。此映射只为状态化旧判定，不代表Theory已定稿。

周线形态/路径必须独立：negative_to_positive、double_positive_efficiency_improved、monday、tuesday_A/B/C、midweek_partial、completed_week。周二C在Theory中的最终状态仍需规则确认，当前Legacy行为不改。

## 日线层

- Legacy raw：上限前原现象；Legacy label：含3.5%上限。
- Theory基础加速：`today_return>0 AND today_return>yesterday_close_to_close_return`，不依赖昨日实体阳线。
- 再按昨日收盘收益分 continuation / rebound。
- 原版 `two_day_raw` 与 Theory 基础加速并行，禁止互相覆盖。

## 事件层

每日状态不等于独立事件。同一信号持续满足属于一个 episode；失效后重新满足才是新 episode。月线池成员周期与信号episode分开记录。
