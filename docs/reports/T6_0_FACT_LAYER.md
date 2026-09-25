# T6.0 冻结报告：Contract + 统一事实层（Fact Layer）

> T6 定性：**解释与验证阶段，不是策略优化**。全阶段只读 T3–T5 冻结产物（基线 `80e934c`），
> 预注册阈值先于任何 T6 分布检视冻结。本报告所有规模/分布数字抄自
> `output/research/t6/00_factlayer/t6_0_report_data.json`（机器聚合），无手填。

## 1. 交付物

| 产物 | 规模 | 说明 |
|---|---|---|
| `t6_contract.json` | 1 份预注册 | 全部阈值/窗口/分类/统计口径（G6 依赖） |
| `src/t6/common.py` | 构建器 | Episode/Daily Master（只读上游） |
| `src/t6/gate_framework.py` | 统一 Gate 框架 | G1–G11 共享原语，各阶段复用 |
| `t6_0_episode_master.parquet` | 283,088 × 33 | 一行 = event × strategy × policy 执行 cell |
| `t6_0_daily_master.parquet` | 492,900 × 66 | 一行 = event × delta_day，纯 PIT |

## 2. Episode Master（一行一个 lifecycle 执行 cell）

T4 入场事实（E_class / participation_policy / base_exposure / fill_status_close）经
**(event_id, strategy) 双键**连接（assignment 为 event×strategy 粒度）；T5.8R-2 全部
episode 指标（ret_norm_ep / portfolio_contribution / mdd_ep / max_cum_pnl_ep /
mean_exposure / n_add / n_reduce / n_exit / censored）原样并入。

规模守恒：**283,088 = T5.8R-2 冻结 episode 数**（policy 分解见 manifest；
active 260,100 + CONTROL 22,988）。

**数据事实（写入设计约束）**：E0 = NON_PARTICIPATION_CONTROL——active 12-cell 池中
E_class 仅 E1/E2/E3（E1=61,812 / E2=59,568 / E3=138,720 cell 行）；E0 以 CONTROL
分支存在（22,988）。T6.1 的相邻梯度比较因此为 **E2_vs_E1、E3_vs_E2 + E1 绝对水平**，
E1_vs_E0 属零参与对照（ret≡0），按 contract 的比较族在 T6.1 标注处理。
filled_rate=0.8231；censored=21,132（与冻结一致）。

## 3. Daily Master（PIT 事实层）

合并链：`t5_daily_state`（全部当日已知 primitive：cum_ret/drawdown/max_dd/days_since_peak/
efficiency_signed_3/turnover_load_3d_mean/dist_ref20/dist_ref60/market breadth/new-high 等）
+ `t5_candidate_state_daily`（raw_state）+ `t5_operational_state_daily_v2`（operational_state）
+ `t5_7 trajectory` 的 **policy 无关 resolution_state**（T5.8R R6 已验证不变性，本地重验）
+ 参考执行列 `_ref`（direct_chase | P2_balanced：exposure_prev/after、pnl、effective_status）。

**PIT 纪律**：构建器硬断言无 `fwd_/future_/outcome_` 列，且**从不读取 t5_daily_outcome**
（G4 列名+lineage 双查）。路径统计（cum/dd/maxdd/days_since_peak）由 G3 物理截断重放验证
（40 事件前缀重算 == 存储值）。

规模：492,900 行 = 27,422 事件 × 事件日数（与 t5_daily_state 严格相等）；事件集合与
Episode Master 完全一致（join_integrity=True）。resolution_state 分布（top）：
RESOLVED_ADD 206,558 / RESOLVED_REDUCE 108,079 / ZERO_BUDGET 95,866 /
NO_ACTION_EVIDENCE 21,442 / RESOLVED_HOLD 19,703 / CONFLICT 11,450 / POST_EXIT_LOCKED 4,780。
参考执行行（direct|P2）=397,034（=冻结 T5.8R-2 daily 表同 cell 行数，G8 守恒验证）。

## 4. Gate 结果（G1–G11 首次应用）

| Gate | 验证 | 结果 |
|---|---|---|
| G1 lineage | 7 输入 sha256 重验 | PASS |
| G2 上游不可变 | 11 个 T3–T5 冻结产物 hash 记录+重验 | PASS |
| G3 PIT 截断重放 | 40 事件前缀重算 == 存储 | PASS |
| G4 outcome 分离 | 无 fwd 列 + lineage 不读 outcome 表 | PASS |
| G5 segment 隔离 | 值域=冻结三分段 | PASS |
| G6 预注册 | 比较常量全部可溯源 contract | PASS |
| G7 no-tuning | 源码扫描无调参习语 | PASS |
| G8 守恒 | policy 分解=总数；ref 行=冻结值 | PASS |
| G9 统计完整性 | 本阶段无推断 → SKIPPED_WITH_REASON | — |
| G10 determinism | rebuild canonical hash == disk | PASS |
| G11 anti-story | 报告 claim ⊂ registry（本报告无 C-id claim） | PASS |

## 5. 已知边界（冻结为 limitation）

- **initial_state 含 EPISODE_TERMINAL/ZERO_BUDGET 值**：day0 的 trajectory 状态原样保留
  （T5.8 replay 侧有各自的过滤语义）；T6 机制研究使用时按需过滤，不改动冻结产物。
- 20 个事件在 T5.7 无任何轨迹行（空状态生命周期，240 cell 行）：segment 从 T5 state
  文件回填；其 resolution/exposure 列为空，分析时自然落入缺失处理。
- `staged_entry ≡ direct_chase`（T5.8R-2 limitation 继承）：参考执行列选 direct_chase
  不损失信息；其余 cell 可经 t5_8_daily join 获得。
- sector 成员为 retrospective 2026 快照（NON-PIT）：contract 已硬约束 sector 分析只能
  EXPLORATORY，不得进入 primary conclusion（G11 机检）。

## 6. 下一步（按 contract stage_order，每阶段独立审计冻结后才解锁下一阶段）

T6.1 E-class independent validation（validation+confirmation 为主，development 仅
reference；相邻梯度 + 双向 cluster bootstrap B=2000；禁止综合 E-score）。
