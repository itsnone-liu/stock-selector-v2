# T5.1 冻结报告：逐日 PIT 事实层（动态资金状态与持仓管理 · 第一步）

- **基线**：3f10a96（T4.6 冻结提交）
- **RULE_VERSION**：`t5_1_facts_v1`
- **任务书**：《T5 动态资金状态与持仓管理：代码实施方案》v1（2026-09-24）§10"当前可执行任务书：仅 T5.1"
- **本阶段不实现**：C0–C6 候选状态、动作资格、仓位优化、T5.2–T5.6 任何策略逻辑。

---

## 1. 交付物

| 产物 | 路径 | 规模 |
|---|---|---|
| 逐日状态表 | `output/research/t5/facts/t5_daily_state.parquet` | 492,900 行 × 59 列 |
| 逐日结果表（独立） | `output/research/t5/facts/t5_daily_outcome.parquet` | 492,900 行 × 24 列 |
| 字段字典 | `output/research/t5/facts/t5_primitive_dictionary.json` | 6 族 55+ 条目 |
| 覆盖表 | `output/research/t5/facts/t5_coverage.parquet` | 年 × 相对日 × E 档 |
| 清单 | `output/research/t5/facts/t5_1_manifest.json` | 血缘+语义+哈希 |
| 门禁 | `output/research/t5/facts/t5_1_gates.json` | **10/10 PASS** |

代码：`src/t5/`（constants / schemas / primitives / primitives_build / outcomes）、
`scripts/run_t5_1_primitives.py`、`scripts/gate_t5_1.py`、
`tests/test_t5_{pit,relative_day,primitives,outcomes}.py`（20 用例全过）。

## 2. 展开语义（披露）

- **delta_day** = 指数市场日历（sh999999）相对 T0 序号，与 V3 tau 同源——
  对账锚 `cum_ret_from_t0_log ↔ V3 close_rel_t0_log` **max|diff| = 0.0**
  （492,900 行 join 全对齐，row_present 逐行一致）。
- **行数** = `min(40, lifecycle_end−T0, 日历末) + 1`：均值 18.0、中位 15、
  p90=38、max=41。终止类型守恒：LIFECYCLE_END 25,228 + MAX_HORIZON 2,194
  = 27,422 事件（**DATA_END=0**：本事件表构建时已要求完整数据窗，无右删失）。
- **row_present=False 为 0 行**（数据源行覆盖含停牌日空行）；停牌/异常以
  `volume_valid=False`（1,318 行）、`adj_available=False`（2,022 行）分别编码。
- **状态/结果物理隔离**：outcome 表独立落盘，state 构建器不 import outcomes
  模块；两表键完全一致（keys parity True），窗口不完整记
  `complete=False + n_obs`，绝不当零（censor 显式）。complete 率 99.59%（h=1..10）。

## 3. 字段族（A–E 批）

- **A 索引+继承**：event_id/delta_day/state_date/row_present/三标志位/终止原因；
  E_class、participation_policy、initial_risk_budget_class、M_cell/L_q/R60/year
  从 T4.5/T4.6/t4_context_state 冻结表逐事件继承（G6 精确对账 27,422/27,422）。
- **B 价格**：ret_{1,3,5}d、cum_from_t0、post_t0_peak/dd、max_dd（V3 口径）、
  距 ref20（raw）/ref60（adj）/T0、运行峰距、21 窗新高、T0 起创新高计数、
  涨跌天数、回调时长。
- **C 参与**：turn/vol/amount 对事件级 **pre20 冻结基数**（T4.2 口径，不重算）
  的 load、1/3 日变化、3 日收缩/扩张。
- **D 效率+市场**：efficiency_signed_{1,3} = price_progress / Σ load
  （**LOAD_EPS=0.01 分母下限冻结**；分母不足 156 行记 None）、
  efficiency_change_3、marginal_progress；
  市场广度/新高（T4.1 冻结口径）水平与 1/3 日变化；
  **mkt_amount_yi 仅诊断（state_allowed=false）**。
- **E 结果（独立表）**：fwd 1/3/5/10 log 收益、5/10 峰值/MDD/新高/失守 ref20，
  complete/complete_path/n_obs 全部显式。

## 4. 无法从冻结数据获得的字段（单列缺口，不静默替代）

| 字段 | 状态 | 处理 |
|---|---|---|
| 板块（申万/证监会门类）逐日 PIT 背景 | 无冻结逐日板块数据 | **未引入**；不以 T4.4 retrospective 表充当（红线：sector 仅 retrospective） |
| 盘口/日内（竞价、分时） | 数据层无 | 不适用（本层为日频） |
| 龙虎榜/融资余额等资金流 | 无冻结数据源 | 留待后续阶段单独开工令 |

## 5. 十道门禁（全部 PASS）

G1 lineage（基线 3f10a96）· G2 主键唯一+相对日连续（0 重复、起点 0 步长 1）·
G3 PIT（非 present 行值列全空；构建器无未来入参）· G4 物理隔离（共享列仅
event_id/delta_day；state 无 fwd_ 前缀列）· G5 行数/终止守恒（每事件恰一个
termination_reason；两表行数一致）· G6 继承精确对账（27,422/27,422，E_class
零不符）· G7 字典齐全（模式族正则覆盖全部 state/outcome 列）· G8 覆盖
（2024/2025/2026 × delta 0..40 × E0..E3）· G9 空值原因分别编码（停牌/复权
缺失/量能无效/分母不足四类计数）· G10 确定性（磁盘键序 + sha256 哈希 +
**200 事件独立重构建 3,433 行逐格零差异**）。

## 6. 工程披露

- 运行：`scripts/run_t5_1_primitives.py` 全量 908s（加载 5,240 股 132s）；
  outcome 修补重跑 244s。峰值 RSS ≈ 3.2GB（**超出主线 2.5G 预算**——T 系列研究
  模块按 T4.4 同款全量缓存执行，非 `run_research_stage.py` 主线路径；后续若
  转主线需改流式）。字典重生成与 gates 运行秒级。
- V3 口径差异披露：V3 tau 行恒 41（固定窗），T5.1 按 lifecycle 截断（均值 18）；
  join 后 cum_ret/row_present 全等。V3 `max_drawdown_to_tau` 与本层
  `max_dd_to_date_log` 同公式（运行峰-谷），但因截断窗不同仅在共同行可比。
- 测试：`/root/venv/bin/python3 -m pytest`（venv 无 pytest 已安装 8.x）；
  合成数据 20 用例：PIT 不回填、相对日连续、span 三边界、已知数值路径、
  分母下限守卫、censor 非零、停牌行空值、键隔离。

## 7. 冻结结论

逐日 PIT 事实层成立：状态与结果物理分表、继承字段零重算、全字段
时间可得性可审计、确定性可复现。**T5.2 候选状态设计（C0–C6 等）须基于本层
真实分布另行开工令，本层未做任何状态聚合或动作资格判断。**
