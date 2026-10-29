# CF-IS IS2A — 事件连续观察窗

## 方法与解释边界

- 本报告及 CSV 仅为描述性案例组织；禁止因果推断，禁止把事件/重叠窗当独立样本。
- 源台账覆盖状态：`seed_not_exhaustive`（非穷尽）；缺席不能解释为无事件。
- first_usable_at 按 UTC+08:00 的 ISO 周锚定；日期精度不补造日内可用时点。
- 相对周按已观测交易周连续行计数，跳过休市周；前 8 周 / 事件周 / 后 12 周。
- 若事件 ISO 周不在周表，保留缺失 EVENT 占位行，不把下一交易周偷换成事件周。
- 完整窗只表示行数齐全，不证明周表底层字段完整或逐字段 point-in-time 合规。
- PRE 另逐行核对 usable_at < first_usable_at；缺失、原子可用性未知、晚于/等于事件分别标记。
  该检查不把 timing_scope 中排除的回溯 episodes 字段升级为 PIT 特征。
- PRE 可用性核查：{'USABLE_BEFORE_EVENT': 72}
- 台账选样声明：Purposive exploratory domestic and overseas event seeds for pipeline/case organization, not an unbiased event census. No event-effect, surprise or no-event claims.
- PRE=`PRE_EVENT_CONTEXT`，只表示事前周表背景，事件元数据是回溯关联，不能作事前特征。
- EVENT=`MIXED_EVENT_WEEK_NOT_PREKNOWN`，整周混合事件前后，不能把 EVENT 整周当已知事件输入。
- POST=`POST_EVENT_OBSERVATION_NOT_ENTRY_SIGNAL`，只作事后观察，不是入场信号。
- 同 cluster 只保留最早 first_usable_at（同刻按 event_id 排序）的代表窗；
  cluster_events_json 保留所有来源，仅供回溯审计，后续公告不是锚点时的已知信息。
- effective_at 可早于/晚于可用日期，不用于替代 first_usable_at；日期缺失或先可用后发布则拒绝。

## 覆盖与完整窗

- 周表：2022-W01 .. 2026-W44，246 个观测交易周。
- 台账事件 10 个；去重后 cluster 窗 9 个；完整窗 9 个。
- 事件类型（源条目）：{'capital_market_policy': 1, 'monetary_liquidity': 1, 'joint_monetary_capital_market_policy': 1, 'fed_monetary_policy': 3, 'trade_escalation': 1, 'trade_deescalation': 1, 'geopolitical_escalation': 1, 'geopolitical_deescalation': 1}
- 证据状态（源条目）：{'official_document_date_verified_exact_release_time_unknown': 1, 'government_republication_verified_original_intraday_timing_unverified': 1, 'official_transcript_verified_conservative_transcript_availability': 1, 'official_statement_release_time_verified': 3, 'official_final_announcement_date_verified_clock_unknown': 1, 'joint_statement_reproduced_by_xinhua_timestamp_verified': 1, 'xinhua_report_verified_not_independent_battlefield_assessment': 1, 'un_official_reaction_verified_not_ceasefire_compliance_confirmation': 1}

|cluster / representative|event ISO week|PRE|POST|状态|合并条目数|
|---|---|---:|---:|---|---:|
|CN_CAPITAL_MARKET_PACKAGE_20230827 / CN_STAMP_TAX_20230827|2023-W35|8|12|COMPLETE|1|
|CN_FINANCIAL_PACKAGE_20240924 / CN_FINANCIAL_BRIEFING_20240924|2024-W39|8|12|COMPLETE|1|
|CN_MONETARY_PACKAGE_20240124 / CN_RRR_20240124|2024-W04|8|12|COMPLETE|1|
|MIDEAST_CONFLICT_JUNE2025 / US_IRAN_STRIKES_REPORTED_20250623|2025-W26|8|12|COMPLETE|2|
|US_CHINA_301_REVIEW_2024 / US_CHINA_301_FINAL_20240913|2024-W37|8|12|COMPLETE|1|
|US_CHINA_GENEVA_202505 / US_CHINA_GENEVA_20250512|2025-W20|8|12|COMPLETE|1|
|US_FOMC_20220921 / US_FOMC_20220921|2022-W38|8|12|COMPLETE|1|
|US_FOMC_20230614 / US_FOMC_20230614|2023-W24|8|12|COMPLETE|1|
|US_FOMC_20240918 / US_FOMC_20240918|2024-W38|8|12|COMPLETE|1|

## 固定日历比较窗（calendar comparison）

无事件筛选的预设季度片段；不是已证无事件对照，也不是匹配/随机对照。
即使包含已登记事件也保留，不依据事后走势或事件密度挑选。按 week_end 落入闭区间选行。

- calendar_2023_q2: 2023-04-03 .. 2023-06-30，13 个观测周。
- calendar_2024_q2: 2024-04-01 .. 2024-06-28，13 个观测周。

不同 cluster 的窗口仍可能共享相同周表行，不能据去重宣称样本独立。
不估计事件效应、不打显著性标签、不产出交易信号。
