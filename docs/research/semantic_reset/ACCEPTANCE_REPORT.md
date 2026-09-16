# P0 验收报告（语义恢复与冻结）

日期：2026-09-16。结论：**P0 完成**。

## 一、八项关键测试（方案 §8.4）

| # | 要求 | 测试 | 结果 |
|---|---|---|---|
| 1 | 今日+4%：优化版保留标签、旧版维持原结果 | test_today_plus4_cap_split | ✅ raw=True, legacy=False, cap_passed=False |
| 2 | 昨日-5%今日+1%：有加速度但非连续上涨 | test_rebound_acceleration_not_consecutive | ✅ rebound≠continuation |
| 3 | 周二实时报价、日线未更新：用实时累计量不跳过 | test_tuesday_realtime_bar_not_skipped | ✅ realtime_synthetic + tuesday 路径 |
| 4 | 节假日短周按真实交易日历 | test_short_week_calendar_not_fixed_five | ✅ planned_sessions=2, 非固定5 |
| 5 | 双阳效率真正执行比较 | test_double_yang_efficiency_really_compares | ✅ 双阳但效率降→False |
| 6 | 改信号日后价格，信号不变 | test_future_prices_do_not_change_signal | ✅ 全字段不变 |
| 7 | 未来收益缺失不计入失败/胜率分母 | test_next_day_split_and_maturity（matured 标记） | ✅ |
| 8 | 收盘/盘中信号不同证据标记 | test_evidence_level_split | ✅ L1/L2 |

补充项：日线bar不与quote重复累计（test_daily_bar_not_duplicated_by_quote）✅。

## 二、旧源码批量差分（等价性第三层）

- 装置：冻结 `datetime.now()` 注入旧函数；旧侧数据截断至 as_of；
  分发层 veto 单独复算（旧函数组无分发器）。
- 结果：**900/900（100%）** 判定一致：
  - monday 178/178；tuesday 153/153；midweek 388/388；friday 181/181。

## 三、差分驱动的语义修正（复刻版）

1. 周一分支 tw=部分周K（W-FRI resample 行为），非两个完整周；
2. 周三四形态B效率用折算涨幅（scaled close）；
3. veto 在分发层前置，一票否决；
4. 周五/周三四标签顺序：形态A优先。

## 四、已知差异（不视为缺陷，详见 KNOWN_DIFFERENCES.md）

1. 周二窗口：旧=滚动7天窗（节假日后可能错认周一），复刻=真实自然周行；
2. 旧实时版合并周语义未混入 EOD 复刻；
3. 历史回放的 as_of 星期 = 事件当日星期（旧代码为真实运行日）。

## 五、遗留

- `legacy_realtime` 盘中变体未单独差分（P4 盘中验证时做）；
- `legacy_reconstructed_v1_eod` 在完成封存样本验证前不注册 `legacy_v0`；
- 全量测试 128 项通过（含 11 项 P0 验收 + 差分 + 面板）。
