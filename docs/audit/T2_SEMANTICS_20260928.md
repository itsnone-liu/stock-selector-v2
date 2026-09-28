# T2 Rule & Data Semantics Audit Evidence (Run audit_20260928055411432)

- Task: stock-selector-v2 formal audit, frozen task packet hash 3ed7f3bc098d
- Run: audit_20260928055411432 (stage T2, iteration 6)
- Date: 2026-09-28
- Suite: `tests/test_spec_semantics_t2.py` (64 deterministic tests, no network) +
  `tests/test_audit_target_binding.py` (2 execution-binding tests), plus the
  pre-existing repo suite re-run in full; raw output artifact with provenance header in
  `docs/audit/T2_PYTEST_OUT_20260928.txt`, narrative in `docs/audit/T2_TESTLOG_20260928.md`.

## Iteration-3 mapping (REVISE testsRequired → added tests)

| 评审要求 | 迭代3补充 |
| --- | --- |
| 第三类形态独立正向用例 + reason/signals 断言 | `test_surge_veto_priority_over_current_week_direction`（SPEC §6 恰有两类 PASS 形态——阴转阳/双阳均有独立正例；第三类结果=放量阴线否决，本测试断言其独立类与优先级：当前周强势阳线仍被否决，`veto_ratio>=1.5`；SPEC 未定义第三种 PASS 形态，故不发明） |
| 有效腾讯报文 1234手→123400股 数值断言 | `test_tencent_valid_quote_converts_hands_to_shares`（`Quote.volume==123400`，price/previous_close/open 全断言） |
| 板块模式过期/未来日线与过期/缺失报价闸门 | `test_board_mode_blocks_stale_daily_before_buy`, `test_board_mode_blocks_future_daily_before_buy`, `test_board_mode_realtime_blocks_missing_and_stale_quote`（全部断言 `buy.total==0`） |
| 底部观察池确定性测试 | `test_bottom_volume_launch_positive`（reason/signals/量倍/回撤断言）, `test_bottom_volume_rejects_low_multiple_and_non_yang`, 既有 `insufficient_daily_bars` 反例 |
| 输出归档不覆盖既有结果 | `test_run_archive_preserves_previous_results`（两次运行归档独立、首次归档内容存活） |
| 排序分非概率、回测不参与规则判定 | `test_scores_are_ranking_only_and_rules_never_consume_backtest`（strategies/* 禁止引用 backtest；pipeline/output 无“概率”字样；输出列名为“综合评分”） |
| 提交后重跑 + 机器可核验记录 + READY_FOR_AUDIT | `docs/audit/T2_TESTLOG_20260928.md`（命令/退出码/通过数）+ 最终 HEAD 上复跑后在 marker TESTS 行给出同源数据 |

## Iteration-4 mapping (REVISE testsRequired → changes)

| 评审要求 | 迭代4落地 |
| --- | --- |
| 第三类正向形态：实现修复 + 独立正向测试（PASS/reason/signals/关键指标）+ 反例防误命中 | `surge.py` 新增 `bullish_engulfing`（阳包阴反包，先于阴转阳判定，`allow_bullish_engulfing` 门控，默认开）；SPEC §6 补第三条形态定义。`test_surge_bullish_engulfing_positive`（PASS + `bullish_engulfing` + signals + `engulfing_body` 指标）；`test_surge_engulfing_counterexamples_fall_back_to_reversal`（未反包→阴转阳；配置关闭→阴转阳） |
| 关键未来数据边界 | `current_week_rows` 截断到 asof 当日（含）——`test_current_week_rows_excludes_future_days`；盘后周进度只数已完成日——`test_week_fraction_never_counts_future_days_after_close`（3/5 而非 5/5）；`daily_buy` 入口截断——`test_daily_buy_ignores_future_rows`（与截断帧完全等价：同判定/同reason/同"今天"价格） |
| 归档碰撞边界 | `pipeline.py` 同秒同 suffix 归档追加 `-2` 序号；`test_run_archive_same_second_collision_appends_suffix`（同秒两次运行→两个归档、首个保留） |
| 测试证据须为可信执行证据而非自述 | 原始 pytest 输出以命令重定向落盘并入库：`docs/audit/T2_PYTEST_OUT_20260928.txt`（exit 0, 428 passed, 逐字未编辑），`T2_TESTLOG_20260928.md` 更新为指向该原始产物 |

## Iteration-5 mapping (REVISE testsRequired → changes)

| 评审要求 | 迭代5落地 |
| --- | --- |
| 可信的 TARGET_COMMIT 测试执行记录（非仅 Git 文件内容） | 新增 `tests/test_audit_target_binding.py`：在目标提交上断言 ①`git status --porcelain` 为空（被测代码=提交内容）②`HEAD~1 == f98447e…`（固定父提交，绑定迭代5目标提交）③T2 语义套件收集数冻结为 64。评审者 checkout 目标提交运行该文件即可机器复核"套件在该提交上执行"是否成立；原始产物 `T2_PYTEST_OUT_20260928.txt` 头部记录 parent/HEAD-at-run/干净状态/命令/退出码 |
| asof 当日时间索引边界 | `current_week_rows`/`daily_buy` 截断改为全时间戳比较（`行时间 <= asof`）：asof 当日日期戳行与当日早于 asof 时刻的行允许，当日晚于 asof 时刻（盘中未来）与之后日期排除——`test_current_week_rows_asof_day_time_index_boundary`（含 09:00/14:30 双向断言） |
| 实时未来时间戳边界 | `check_quote_freshness` 新增未来拒绝分支：超出时钟偏差（`max_quote_future_seconds` 默认30s）的未来戳 → SKIP `quote_from_future`（独立确定性 reason），偏差内未来戳仍 `quote_fresh`——`test_future_quote_timestamp_rejected`（900s→拒绝；10s→新鲜） |




## Frozen item → test mapping (SPEC §1-8, iteration 2 complete)

| 冻结必测语义 | 测试 |
| --- | --- |
| 显式 asof 驱动已完成周/当前周切分 | `test_asof_explicitly_drives_week_partition`, `test_completed_week_excludes_current_week_on_monday`, `test_empty_frame_week_partition_returns_empty` |
| 真实涨幅不外推（盘中只用 开盘→现价） | `test_realtime_change_not_extrapolated`（断言 3.0% 而非外推值 60%，并断言周内进度 0.05） |
| 成交量周内进度（实时/盘后两种口径） | `test_elapsed_week_fraction_progress_semantics`（0.05/0.55/0.6/周末不计盘中）、`test_realtime_change_not_extrapolated` 中的 `projected_volume_ratio==1.0` |
| 腾讯手→股 | `test_tencent_valid_quote_converts_hands_to_shares`（1234手→123400股 数值断言）, `test_realtime_volume_unit_default_is_hand_to_share` |
| 历史新鲜度闸门（未来/过期/盘后宽限） | `test_future_daily_bar_is_error`, `test_stale_realtime_daily_data_is_skipped`, `test_after_close_allows_at_most_one_business_day_lag` |
| 实时报价闸门 | `test_quote_without_timestamp_is_skipped`, `test_stale_quote_is_skipped` |
| 零价零量处理 | `test_zero_price_quote_rejected_as_invalid`, `test_zero_open_or_volume_rejected_as_halted` |
| B股/ST/退市/上市时间/低流动性 | `test_excludes_b_shares`/`test_sz_b_share_prefix_rejected`（900/200）, `test_excludes_st`/`test_delisting_name_rejected`, `test_short_listing_history_rejected`, `test_low_liquidity_rejected_when_configured` |
| 月线 MA5>MA10>MA20 | `test_monthly_bull_passes_with_ma_ordering`, `test_monthly_ma_not_bull_rejected`, `test_monthly_last_month_drop_rejected`, `test_monthly_insufficient_bars_skipped` |
| 周线三类信号（各自可复现） | `test_weekly_signal_ma_bull`, `test_weekly_signal_macd_cross`（加速下跌+2周反弹恰在末根金叉）, `test_weekly_signal_macd_stabilizing`（二次回落后柱体负值拐头）, `test_weekly_downtrend_rejected`, `test_weekly_insufficient_bars_skipped` |
| 放量阴线否决 | `test_surge_bearish_heavy_turnover_veto` |
| 当前周阳线 + 三类形态 | `test_surge_dual_yang_efficiency_pass`, `test_surge_bearish_to_bullish_reversal_pass`, `test_surge_current_week_not_bullish_rejected`, `test_surge_not_up_vs_previous_close_rejected`, `test_surge_weekly_efficiency_not_improved_rejected`, `test_surge_projected_volume_too_low_rejected` |
| 日线三类买点 + 优先级 + 投影回退标记 | `test_buy_pullback_has_priority_over_two_day_acceleration`, `test_buy_shrinking_has_priority_over_two_day_acceleration`, `test_buy_two_day_acceleration_passes_after_close`, `test_buy_shrinking_volume_acceleration_passes_intraday_same_time`, `test_buy_missing_same_time_snapshot_falls_back_to_projected`, `test_buy_same_time_reference_missing_when_fallback_disabled`, `test_buy_preopen_projected_unavailable` |
| 板块跳过 weeksurge 但保留闸门与买点 | `test_board_mode_skips_surge_but_keeps_gates_and_buy` |
| 空数据/短历史 | `test_empty_frame_week_partition_returns_empty`, `test_monthly_insufficient_bars_skipped`, `test_weekly_insufficient_bars_skipped`, `test_surge_insufficient_completed_weeks_skipped`, `test_buy_insufficient_daily_bars_skipped`, `test_short_listing_history_rejected` |
| NaN 输入 | `test_weekly_aggregation_close_is_last_available_close`（周五缺失→周收盘=周四收盘，确定且不崩溃）, `test_strategies_deterministic_with_nan_close_input`（月/周/买点均确定性判定，NaN当日收盘→REJECT pattern_not_passed） |

## Verified semantics summary

- asof 显式切周：同一数据在 asof=09-08 与 09-15 下完成周分别止于 09-04 / 09-11。
- 盘中真实涨幅只用 当日开盘→现价；周内进度仅用于投影成交量（250k/0.05/500万=1.0 精确验证）。
- 实时周进度=（完成日+盘中片段）/5（周一10:30→0.05、周三14:00→0.55）；盘后=已有交易日/5；周末不计盘中。
- 周线三类信号各自构造数据可复现：MA多头 / 末根DIF上穿DEA / 负值区柱体拐头+DIF≈DEA。
- 三类买点优先级：回踩不破 > 缩量加速 > 两日加速（两组优先级测试）。
- 同刻快照缺失回退链：same_time → projected_full_day →（禁用时）same_time_reference_missing；未开盘 market_not_started。
- 板块模式：surge 记 board_mode_skips_surge，新鲜度/风险过滤/买点照常（ST 仍被拦截）。
- NaN：聚合取周内最后可得收盘；策略对 NaN 输入给出确定判定不抛异常。

## Result

- No SPEC §1-8 semantic defect requiring source changes was found; the frozen-mandatory
  semantics are now each pinned by at least one named deterministic test.
- Scores are treated as ranking only; no backtest result is used as rule-correctness
  evidence anywhere in this suite.
- No `data/` raw data, credentials, or unrelated projects modified.

## Iteration-6 mapping (REVISE testsRequired → changes)

| 评审要求 | 迭代6落地 |
| --- | --- |
| 证据不得指向另一提交；绑定须唯一识别目标提交 | 两段式结构：代码提交 T0=ccc3250b（套件在干净树全量执行并逐字落盘）；目标提交=T0+仅证据增量（docs/audit/* + 绑定测试）。`tests/test_audit_target_binding.py` 断言：干净树 ∧ HEAD~1==T0 ∧ 目标对 T0 的 src/tests/SPEC 增量为空（除绑定文件）∧ T2 收集数冻结 66 —— 唯一识别目标且证明代码与运行记录完全一致；T0 未被 amend，可 checkout 复跑 |
| 未来历史数据闸门可复现遗漏 | `check_daily_freshness` 改按索引最大日期判定：未排序帧中间藏未来行（末行为过去日期）仍 `future_daily_bar` ERROR —— `test_future_row_hidden_in_unsorted_frame_is_error`；管线层 `test_pipeline_blocks_unsorted_future_frame_before_buy`（freshness 拦截、buy.total==0）；另加闸门后硬截断 `daily <= asof` 纵深防御 |
