# V3 实施账本

依据：`capital_behavior_v3_rebuild_plan.md`（2026-09-16）。

## P0（当前）

| 项 | 状态 | 证据 |
|---|---|---|
| 冻结当前研究版，不冒充原版旧策略 | ✅ | tag `pre-v3-p0-20260916`，`V3_P0_BASELINE.md` |
| 撤回旧研究强结论 | ✅ | TREND_GATE / PORTFOLIO_REPLAY 顶部警示 |
| T+1开盘不读取当天收盘regime | ✅ | pending order携带signal_regime |
| 全候选排序后截top-N | ✅ | `(rank, code)`确定性排序 |
| 费用/滑点/历史印花税 | ✅ | `decision/execution.py` |
| 停牌/开盘涨跌停近似与拒单台账 | ✅ | execution_feasibility + retry exits |
| 未来数据篡改不影响过去 | ✅ | `test_future_data_mutation_*` |
| 输入顺序不影响成交 | ✅ | `test_input_order_*` |
| 复现元数据 | ✅基础版 | manifest + SHA/config/seed/input hash；完整数据快照待数据层 |
| E1 修复后基线 | 🔄 | `output/research/v3_p0_e1` 跑批中 |

## Capital Observer P0

| 项 | 状态 |
|---|---|
| 清除131.7万条伪published_at | ✅，置NULL不猜测 |
| available_at落库 | ✅，新摄取用实际抓取时间 |
| unknown availability不参与context | ✅，刷新前0/6，板块刷新后1/6 |
| membership换组闭旧区间 | ✅ |
| 历史as_of/batch API | 延至P2（时间规则真实前不做伪PIT） |

## P1（下一阶段）

- 主池快照：月线主池版本、池入/出原因；
- 事件账本：candidate_event append-only，多标签；
- 观察状态机：new/observing/confirmed/weakening/invalidated/expired，可恢复；
- 持仓风险池独立运行，不依赖主池/候选池；
- 每次转移保留 old/new、trigger、evidence、rule_version、as_of；
- 全市场廉价扫描只做本地向量化，深检只跑观察池。

## P2–P4 边界

- P2：源级 publication rule、历史行业映射、market/style/sector snapshots、batch/as_of API；
- P3：原双阳效率/revised active_up/V3效率并行特征；趋势年龄、VWAP、换手与成本压力；
- P4：E0–E7、事件去重、同日同行业matched comparison、封存样本外、影子生产。

生产策略在P4验收前不自动切换。
