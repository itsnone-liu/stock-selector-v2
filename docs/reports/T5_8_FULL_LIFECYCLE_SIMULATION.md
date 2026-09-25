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

Gate 侧：G1 显式输入谱系重哈希（非 AST 猜测）；G8 源码扫描调参习语 + P1/P2/P3 常量文本钉死；G10 产物全量重哈希。G4 新增 BH 同钟核对。

## 1. Simulation Contract（冻结要点）

**真实 x₀**：每事件 × 4 入场策略独立分支；`fill_status_close` 口径——filled → x₀=1.0，
not_filled → x₀=0.0（not_filled 终生 NO_POSITION，T5 ADD **永不**开仓——G2/G3）。

**执行时钟（PIT）**：close t 信号 → 目标暴露作用于 (t, t+1] 收益：`pnl_d = x_{d-1} · ret_1d_log_d`；
day-0 收益不交易；**buy-and-hold 对照同样只累计 d>0 收益（同钟，G4）**。

**停牌（R5）**：`ret` 为 NaN 的交易日 = 无报价 = **不可交易**：pnl=0 且 operator 冻结（x 不变）。

**终端**：LIFECYCLE_END 自然结算；MAX_HORIZON 右删失单独报告。censor 率 8.12%（21,132/260,100）。

**指标双层（R4）**：`ret_ep_log` = normalized policy return（x = actual/base 的单位预算口径）；
`portfolio_contribution` = base × ret_ep_log（账户层）。**比较跨 base 的策略时必须用 contribution 层。**

## 2. 冻结 12-cell 矩阵（全库，数字=report_data.json）

规模（manifest）：episodes **283,088**（active 12-cell 260,100 + P0 对照 22,988；
not-filled 46,017；censored 21,132）；daily 行 **4,196,190**；attribution 行 **300,783**；
停牌 no-trade 日 214,083（G7 全检 pnl=0 且 x 冻结）。

| strategy | policy | filled率 | mean_ret_norm | **mean_contrib** | mean_mdd(R1) | max_cum_pnl(R2) | p05 | exposure |
|---|---|---|---|---|---|---|---|---|
| direct_chase | P1 | 1.000 | +3.59% | +2.54% | −7.27% | +9.92% | −7.40% | 0.670 |
| direct_chase | P2 | 1.000 | +4.85% | +3.42% | −6.28% | +10.20% | −6.18% | 0.619 |
| direct_chase | P3 | 1.000 | +5.95% | +4.19% | −5.64% | +10.58% | −5.44% | 0.586 |
| staged_entry | P1–P3 | 1.000 | 同 direct_chase | 同 | 同 | 同 | 同 | 同 |
| wait_first_pullback | P2 | 0.786 | +5.04% | +3.52% | −5.43% | +9.60% | −4.90% | 0.492 |
| wait_support_hold | P2 | 0.506 | +3.02% | +2.15% | −3.45% | +5.86% | −3.81% | 0.304 |

- **P1→P3 单调**：normalized 收益 +3.6%→+6.0%，MDD −7.3%→−5.6%（更果断=更高收益+更浅回撤；P3 的低暴露本身是风控）。**此为 normalized 层；账户层乘各策略 base。**
- **staged_entry 与 direct_chase 全同**：两者 x₀ 与 T5.7 状态序列在当前冻结管线里完全一致（filled_rate 均 1.000，同一事件集）——**这是管线结构事实，不是错误**，但意味着本轮矩阵里"入场策略"实际只有 3 个有效自由度（direct/staged 合并、pullback、support_hold）。
- **分段（12-cell 均值）**：development +2.55%、validation +4.69%、**confirmation +4.66%（contrib +3.38%）**——confirmation 段动态管理的收益保持，外推性结论在本口径下仍成立（分段明细见 `t5_8_split_metrics.parquet`）。

## 3. 生命周期机制（R7 重写：无再入场）

`RESOLVED_EXIT` → x=0 → **POST_EXIT_LOCKED 永久锁定至 episode 终止**。本契约中**不存在
EXIT→ADD 再入场循环**；能回补暴露的只有 **REDUCE→ADD**。原 T5.8 报告的"EXIT 解锁空仓+
ADD 回补循环"表述与代码直接冲突，作废。

## 4. Disable-operator 反事实（R8 口径声明）

**这些是"其他机制不变、单组件禁用"的模拟，不是加性贡献分解**——ADD/REDUCE/EXIT 通过暴露
路径相互作用，禁用其一会改变其余的作用面。任何"X 贡献 Y pp"的加性读法均无效。
池：71,361 filled cells（P2 固定参数；full P2 均值 +4.85%）；static 86,700 行（x₀ 持有到底）。

| variant | mean_ret_norm | mean_mdd | mean_exposure | vs full P2 |
|---|---|---|---|---|
| static_no_T5 | +0.59% | −10.29% | 0.823 | −4.26pp |
| disable_add | +3.47% | −5.08% | 0.483 | −1.38pp |
| disable_reduce | **+0.95%** | **−12.08%** | **0.962** | **−3.90pp** |
| disable_exit | +5.35% | −6.57% | 0.625 | +0.50pp |
| （参考）BH 同钟 | +0.71% | — | 1.0 | — |

**三条可读结论（描述性，非归因分解）**：
1. **动态管理整体 vs 静态持有**：+4.26pp（normalized 层）且 MDD 减半（−6.3% vs −10.3%）、平均暴露 0.62 vs 0.82——收益与风险双向占优的表象来自组合机制，见 2/3。
2. **禁用 REDUCE 损失最大**（−3.90pp、MDD −12.1%、暴露贴满 0.96）。**修正原 T5.8 报告**："REDUCE 对收益≈0 只管风险"在 R3/R5 修复后**不成立**——REDUCE 同时是收益路径与风险控制的主要载体（低暴露+回补的再平衡收益）。
3. **禁用 EXIT 均值反升 +0.50pp 但 MDD 加深（−6.6% vs −6.3%）**：EXIT 是尾部风险保险（POST_EXIT_LOCKED 放弃后续上行换回撤上限），在均值口径几乎免费、在尾部口径必要。**禁止再使用"EXIT 释放暴露由 ADD 回补"的旧叙事。**

## 5. Gate 证据（10/10 PASS，全部真验证）

| Gate | 验证内容 | 关键数字 |
|---|---|---|
| G1 | 输入谱系：3 输入重哈希 vs manifest | inputs_hash_verified=3 |
| G2 | 真实 x₀ + not-filled 全零（46,017 行） | not_filled_nonzero_pnl=0 |
| G3 | not-filled 永不开仓 | zero_exposure_all_days=true |
| G4 | day-0 pnl=0 全检 + BH==Σ(d>0) 抽样 | bh_clock_mismatch=0/2000 |
| G5 | daily 求和==episode ret（214,083 cell） | branches_checked=214083 |
| G6 | censored ⇔ MAX_HORIZON | 21,132 |
| G7 | 停牌 no-trade 全检 + preserve 路径存活 | suspended=214,083；conflict=123,057；noev=234,144 |
| G8 | 源码无调参习语 + P1/P2/P3 常量钉死 | tuning_idioms_found=[] |
| G9 | 三段 × 4 反事实结构 | segments/cf 齐全 |
| G10 | 9 产物重哈希 vs manifest | products_hash_matched=9 |

## 6. 遗留与边界

- `mdd_ep`/`max_cum_pnl_ep` 均为 normalized 层（单位 base 预算）；账户层风险乘 base。
- staged_entry≡direct_chase 的自由度坍缩留给后续阶段决策（若需区分，须回 T4.6 重定义 staged 的 x₀ 结构，超出本阶段边界）。
- 禁用 counterfactual 固定 P2——P1/P3 下的算子敏感性未展开（避免与策略维度混淆）。
- BH 对照为同钟累计收益，未含交易成本（与本管线一致：无成本冻结假设沿 T5.7）。
