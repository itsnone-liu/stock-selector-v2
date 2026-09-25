# T5.8R 冻结报告：Full Lifecycle Strategy Simulation（审计返工版）

> **本报告取代 T5.8 原版（bc8d6a7）**。原版被外部审计判 BLOCKED：MDD/MFE 定义错误、
> buy-and-hold 时钟不一致、停牌日 operator 泄漏、Gate 证明力不足（G1 AST 解析零命中仍
> PASS、G8 自证、G10 仅存在性）。R 版修复 R1–R9 后全量重跑，产物在原路径原位覆盖，
> 上游 T3→T5.7 冻结不动（仍为 `8c4a992` 基线，只读消费）。
>
> **本报告所有规模数字抄自 `t5_8_manifest.json`（机器生成），效果数字抄自
> `t5_8_report_data.json`（由冻结 parquet 自动聚合）。无手填数字。**

- **基线**：`8c4a992`（T5.7；链：`ebfc490 → … → 8c4a992 → bc8d6a7(旧T5.8,作废) → 96c8e86 → 432d7c6 → 本次 T5.8R`）
- **十道 Gate**：10/10 PASS（`t5_8_gates.json`；G1/G4/G7/G8/G10 全部换为真验证）
- **性质**：冻结候选矩阵的结构化模拟 + disable-operator 反事实；**无冠军排名、无参数重调**

## 0. 审计响应对照表（R1–R9）

| # | 审计发现 | R 版修复 | 验证 |
|---|---|---|---|
| R1 | MDD 算的是相对 0 最低点 | `mdd = min_t(C_t − max_{s≤t} C_s)`，running peak 锚定起点 0 | 矩阵口径变化 |
| R2 | mfe_pnl_ep 实为最大单日 P&L | 改累计口径并**更名 `max_cum_pnl_ep`** | 契约 + 列名 |
| R3 | BH 含 day-0 收益（时钟错位） | `bh += ret` 仅当 `d>0`（入场收盘成交，同钟） | G4（2000 cell 抽样 0 失配） |
| R4 | normalized 与账户贡献混用 | 双指标层：`ret_ep_log`（单位 base 预算）与 `portfolio_contribution = base × ret_ep_log`，矩阵双列 `mean_ret_norm_ep` / `mean_contrib_ep` | 契约 metric_layers |
| R5 | 停牌日 pnl 冻结但 operator 照跑 | `ret=None → SUSPENDED_NO_TRADE`：pnl=0 **且 x 不变** | G7（214,083 行全检） |
| R6 | T5.7 collapse 未验证 policy 一致 | `nunique()==1` 断言在 `drop_duplicates` 之前 | build_inputs 硬断言 |
| R7 | 报告写"EXIT 解锁 + ADD 回补" | POST_EXIT_LOCKED **永久锁定，无再入场路径**；本报告 §3 重写 | 契约 post_exit |
| R8 | counterfactual 被读成独立贡献分解 | 全文改称 **disable-operator 反事实**（单组件禁用模拟，非加性分解） | §4 口径声明 |
| R9 | 报告手填规模数字（旧轮 329,064/12.16M 混入） | manifest 输入/产物 sha256 全记录 + `t5_8_report_data.json` 机器聚合 | G1/G10 |
| R10 | day-0 ret 结构性 NaN 被误计为停牌（260,100=每 active 分支恰 1 次；数据实证 27,422/27,422 day0 行 ret=NaN） | d==0 → `ENTRY_DAY_NO_RETURN`（且恢复 day0 operator 执行——作用于 day1 暴露）；`d>0 && ret=None` → `SUSPENDED_NO_TRADE` | G7 重验 |

Gate 侧：G1 显式输入谱系重哈希（非 AST 猜测）；G8 源码扫描调参习语 + P1/P2/P3 常量文本钉死；G10 产物全量重哈希。G4 新增 BH 同钟核对。

## 1. Simulation Contract（冻结要点）

**真实 x₀**：每事件 × 4 入场策略独立分支；`fill_status_close` 口径——filled → x₀=1.0，
not_filled → x₀=0.0（not_filled 终生 NO_POSITION，T5 ADD **永不**开仓——G2/G3）。

**执行时钟（PIT）**：close t 信号 → 目标暴露作用于 (t, t+1] 收益：`pnl_d = x_{d-1} · ret_1d_log_d`；
day-0 收益不交易；**buy-and-hold 对照同样只累计 d>0 收益（同钟，G4）**。

**停牌（R5/R10）**：`d>0 且 ret=NaN` = 无报价 = 不可交易：pnl=0 且 operator 冻结。**filled 池
d>0 真停牌日 = 0**（t5_daily_state 事件级 d>0 NaN 共 1,910 行，全部落在 not-filled 分支的
事件上，实证见 manifest `suspended_no_trade_days=0`）。`delta_day=0` 的 ret 为**结构性
NaN**（入场日无前日收益，27,422/27,422），标记 `ENTRY_DAY_NO_RETURN`，day0 的 resolution
状态照常执行并作用于 day1 暴露——R10 修复恢复了此前被 R5 误冻结的 day0 operator；
数值上收益层与 bc8d6a7 原版完全一致（P2/direct mean_ret 0.053203，差 0.0），MDD 差异
全部来自 R1 口径修正。

**终端**：LIFECYCLE_END 自然结算；MAX_HORIZON 右删失单独报告。censor 率 8.12%（21,132/260,100）。

**指标双层（R4）**：`ret_ep_log` = normalized policy return（x = actual/base 的单位预算口径）；
`portfolio_contribution` = base × ret_ep_log（账户层）。**比较跨 base 的策略时必须用 contribution 层。**

## 2. 冻结 12-cell 矩阵（全库，数字=report_data.json）

规模（manifest）：episodes **283,088**（active 12-cell 260,100 + P0 对照 22,988；
not-filled 46,017；censored 21,132）；daily 行 **4,196,190**；attribution 行 **300,783**；
filled 池 d>0 真停牌日 **0**（G7：SUSPENDED 行=0；day0 全部标记 ENTRY_DAY_NO_RETURN，
214,083 行）。

| strategy | policy | filled率 | mean_ret_norm | **mean_contrib** | mean_mdd(R1) | max_cum_pnl(R2) | p05 | exposure |
|---|---|---|---|---|---|---|---|---|
| direct_chase | P1 | 1.000 | +3.92% | +2.76% | −6.83% | +9.86% | −5.89% | 0.626 |
| direct_chase | P2 | 1.000 | +5.32% | +3.73% | −5.75% | +10.23% | −4.15% | 0.568 |
| direct_chase | P3 | 1.000 | +6.55% | +4.59% | −5.04% | +10.68% | −3.02% | 0.530 |
| staged_entry | P1–P3 | 1.000 | 同 direct_chase | 同 | 同 | 同 | 同 | 同 |
| wait_first_pullback | P2 | 0.786 | +5.32% | +3.70% | −5.12% | +9.63% | −3.46% | 0.468 |
| wait_first_pullback | P3 | 0.786 | +6.36% | +4.42% | −4.57% | +10.07% | −2.37% | 0.444 |
| wait_support_hold | P2 | 0.506 | +3.21% | +2.27% | −3.24% | +5.90% | −2.62% | 0.289 |

- **P1→P3 单调**：normalized 收益 +3.9%→+6.6%，MDD −6.8%→−5.0%（更果断=更高收益+更浅回撤；P3 的低暴露本身是风控）。**此为 normalized 层；账户层乘各策略 base。**
- **staged_entry 与 direct_chase 全同**：两者 x₀ 与 T5.7 状态序列在当前冻结管线里完全一致（filled_rate 均 1.000，同一事件集）。这是**模型边界发现**而非错误：当前 lifecycle 模拟器不表达 staged entry 的 tranche 级执行路径（30%→30%→40% 的分批细节在 x₀=1 归一化后不可区分）。**冻结为 limitation**；若未来要研究分批执行，应另开 execution refinement 阶段，而不是回改 T4.6 制造 12 个不同 cell。
- **分段（12-cell 均值）**：development +3.00%、validation +5.00%、confirmation +5.03%（P2/direct：+3.39%/+5.53%/+5.75%）。**confirmation 段结果保持正向，未观察到明显的跨时间方向翻转，为冻结规则的时间外稳定性提供支持；不等同于独立生产级 OOS 验证**（T5.5 action policy 为 development-derived，且部分 action——尤其 EXIT——的 validation 支撑不完整）。

## 3. 生命周期机制（R7 重写：无再入场）

`RESOLVED_EXIT` → x=0 → **POST_EXIT_LOCKED 永久锁定至 episode 终止**。本契约中**不存在
EXIT→ADD 再入场循环**；能回补暴露的只有 **REDUCE→ADD**。原 T5.8 报告的"EXIT 解锁空仓+
ADD 回补循环"表述与代码直接冲突，作废。

## 4. Disable-operator 反事实（R8 口径声明）

**这些是"其他机制不变、单组件禁用"的模拟，不是加性贡献分解**——ADD/REDUCE/EXIT 通过暴露
路径相互作用，禁用其一会改变其余的作用面。任何"X 贡献 Y pp"的加性读法均无效。
池：71,361 filled cells（P2 固定参数；full P2 均值 +5.32%）；static 86,700 行（x₀ 持有到底）。

| variant | mean_ret_norm | mean_mdd | mean_exposure | vs full P2 |
|---|---|---|---|---|
| static_no_T5 | +0.59% | −10.29% | 0.823 | −4.73pp |
| disable_add | +3.55% | −4.24% | 0.415 | −1.77pp |
| disable_reduce | **+0.95%** | **−12.08%** | **0.962** | **−4.37pp** |
| disable_exit | +5.79% | −6.08% | 0.579 | +0.47pp |
| （参考）BH 同钟 | +0.71% | — | 1.0 | — |

**三条可读结论（描述性，非归因分解）**：
1. **动态管理整体 vs 静态持有**：+4.73pp（normalized 层）且 MDD 减半（−5.8% vs −10.3%）、平均暴露 0.57 vs 0.82——收益与风险双向占优的表象来自组合机制，见 2/3。
2. **禁用 REDUCE 损失最大**（−4.37pp、MDD −12.1%、暴露贴满 0.96）。**修正原 T5.8 报告**："REDUCE 对收益≈0 只管风险"在 R3/R5 修复后**不成立**——REDUCE 同时是收益路径与风险控制的主要载体（低暴露+回补的再平衡收益）。
3. **禁用 EXIT 均值升 +0.47pp、平均 MDD 略有恶化（−6.08% vs −5.75%）**：EXIT 表现出**牺牲部分均值收益、改善平均回撤的保险型特征；是否对尾部风险（MDD 分位数/CVaR/大损概率）具有稳定保护作用，仍需专门的尾部指标验证**——本报告仅有 mean MDD，且 EXIT 在 validation 段的有效证据偏弱。**禁止再使用"EXIT 释放暴露由 ADD 回补"的旧叙事**（POST_EXIT_LOCKED 永久锁定）。

## 5. Gate 证据（10/10 PASS，全部真验证）

| Gate | 验证内容 | 关键数字 |
|---|---|---|
| G1 | 输入谱系：3 输入重哈希 vs manifest | inputs_hash_verified=3 |
| G2 | 真实 x₀ + not-filled 全零（46,017 行） | not_filled_nonzero_pnl=0 |
| G3 | not-filled 永不开仓 | zero_exposure_all_days=true |
| G4 | day-0 pnl=0 全检 + BH==Σ(d>0) 抽样 | bh_clock_mismatch=0/2000 |
| G5 | daily 求和==episode ret（214,083 cell） | branches_checked=214083 |
| G6 | censored ⇔ MAX_HORIZON | 21,132 |
| G7 | ENTRY_DAY 重标 + 真停牌语义（若存在必 d>0 且 x 冻结）+ preserve 路径存活 | entry_day=214,083；true_susp=0；conflict=123,057；noev=234,144 |
| G8 | 源码无调参习语 + P1/P2/P3 常量钉死 | tuning_idioms_found=[] |
| G9 | 三段 × 4 反事实结构 | segments/cf 齐全 |
| G10 | 9 产物重哈希 vs manifest | products_hash_matched=9 |

## 6. 遗留与边界

- `mdd_ep`/`max_cum_pnl_ep` 均为 normalized 层（单位 base 预算）；账户层风险乘 base。
- staged_entry≡direct_chase 的自由度坍缩冻结为 limitation（见 §2）：模型边界发现——当前模拟器不表达 tranche 级执行路径；研究分批执行应另开 execution refinement 阶段，不回改 T4.6。
- 禁用 counterfactual 固定 P2——P1/P3 下的算子敏感性未展开（避免与策略维度混淆）。
- BH 对照为同钟累计收益，未含交易成本（与本管线一致：无成本冻结假设沿 T5.7）。
