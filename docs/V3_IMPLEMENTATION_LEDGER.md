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
| E1 修复后基线 | ✅ | `docs/research/E0_E1_20260916.md`：E0 +5.01% / E1 -9.61% / E1b(选样防前视) -6.05% |
| 选样防前视 | ✅ | 资格按窗口起点判定，113→105只，前视约虚增3.6pp |
| 盘后影子链 | ✅ | `scripts/v3_daily_shadow.py` 单入口幂等，2026-09-15实测重跑0新增 |

## Capital Observer P0

| 项 | 状态 |
|---|---|
| 清除131.7万条伪published_at | ✅，置NULL不猜测 |
| available_at落库 | ✅，新摄取用实际抓取时间 |
| unknown availability不参与context | ✅，刷新前0/6，板块刷新后1/6 |
| membership换组闭旧区间 | ✅ |
| 历史as_of/batch API | 延至P2（时间规则真实前不做伪PIT） |

## P1（已完成影子内核，不切生产）

- ✅ 月线主池快照，显式区分当前未完成月与上一完整月；
- ✅ signal_event append-only、多标签、确定性去重ID、默认20会话有效期；
- ✅ new/observing/confirmed/weakening/invalidated/expired，可恢复且转移全审计；
- ✅ 持仓风险批处理独立于主池/候选池，缺数据为unknown；
- ✅ 全市场本地影子扫描：2026-09-15共5237帧、主池712、事件301、unknown 135；
- ✅ 行为特征快照分离 raw/cost_ref/version/data_quality。

## P2–P4 进度与边界

- P2已完成：strict `as_of` context、batch context、observations窗口，统一
  `available_at <= as_of`；旧unknown历史不准入。
- P3已完成基础层：趋势年龄、5/10/20日VWAP、相对VWAP、推进/成交额特征；
  真实TDX单位验证确认volume=手，显式×100股换算。
- P4已完成研究原语：事件簇去重、严格事后5/10/20日路径、MAE/MFE、分位数、
  正收益率与右尾贡献；尚未完成E2-E7全矩阵及真正封存样本。

- P2：源级 publication rule、历史行业映射、market/style/sector snapshots、batch/as_of API；
- P3：原双阳效率/revised active_up/V3效率并行特征；趋势年龄、VWAP、换手与成本压力；
- P4：E0–E7、事件去重、同日同行业matched comparison、封存样本外、影子生产。

生产策略在P4验收前不自动切换。
