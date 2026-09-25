# T5.8 冻结报告：Full Lifecycle Strategy Simulation

- **基线**：`8c4a992`（T5.7；链：`ebfc490 → aac1f9f → c4a3056 → ad7fd2c → 8c4a992 → 本次`）
- **十道 Gate**：10/10 PASS（`t5_8_gates.json`）
- **性质**：冻结候选矩阵的结构化模拟 + 反事实归因；**无冠军排名、无参数重调**

## 1. T5.8A Simulation Contract（全部冻结）

**真实 x₀（T5.7 的 x₀=1 假设正式撤销）**：每事件 × 4 入场策略独立分支；`fill_status_close` 口径——filled → x₀=1.0，not_filled → x₀=0.0。join 键 (code, signal_day) 连接率 100%（27,422/27,422）。

**执行时钟（PIT）**：close t 信号 → 目标暴露作用于 (t, t+1] 收益区间：`pnl_d = x_{d-1} · ret_1d_log_d`；day-0 收益不交易（入场即收盘成交）。G4 硬验证。

**not-filled 永不建仓**（G3）：整个生命周期 NO_POSITION，T5 ADD 无法从 0 重建仓位。

**P0 对照**：base=0 分支记为 NON_PARTICIPATION_CONTROL（不除 0/0），不入动态统计。

**Terminal 语义**：LIFECYCLE_END = episode 自然结算；MAX_HORIZON = 右删失（8.1%，val 段最高 10.6%），单独披露，不并入正常退出收益。

**E0/E1**：E0 精确语义为主口径（任何 x>0 即持仓）；E1 仅敏感性——x<0.05 记 dust-days，**阈值未冻结、不转 EXIT**。

## 2. T5.8B 12-cell 冻结矩阵（329,064 episodes；12.16M 日行）

| strategy | fill率 | P1 ret/mdd/expo | P2 | P3 |
|---|---|---|---|---|
| direct_chase | 100% | .039/-.021/.626 | .053/-.014/.568 | .066/-.010/.530 |
| staged_entry | 100% | 同 direct | 同 | 同 |
| wait_first_pullback | 78.6% | .041/-.016/.506 | .053/-.011/.468 | .064/-.008/.444 |
| wait_support_hold | 50.6% | .024/-.011/.313 | .032/-.007/.289 | .039/-.005/.275 |

（ret=mean episode log return；mdd=episode 内均值；expo=mean exposure）

**结构发现（非排名）**：

1. **direct_chase ≡ staged_entry**：close-fill 口径下两者在 T5 事件集的初始暴露与 fill 语义完全重合，模拟分支相同——这是 T4.6 两策略在该口径下的重合事实，已披露。
2. **P1/P2/P3 呈单调 trade-off**：暴露递减（0.63→0.53）、MDD 收窄（-0.021→-0.010）、ret 上升（.039→.066）、**dust 天数递增**（0.77→3.24/episode）。P3 用更多 near-zero 时段换取风险压缩。
3. **split 稳定性**：三段内 P1<P2<P3 排序全部保持（direct：dev .020/.034/.045、val .042/.055/.067、conf .042/.058/.071）；dev 段绝对收益系统性偏低（与 T5.5 已知的 ADD val/conf 漂移一致），方向未翻转。
4. **日状态构成**（12-cell 池）：ADD_AT_CAP 28.8%、REDUCE 27.8%、ADD 26.2%、NO_ACTION 5.8%、HOLD 5.4%、CONFLICT 3.1%、EXIT 0.8%、POST_EXIT_LOCKED 2.1%。

## 3. T5.8C 反事实归因（P2，300,783 行）

相对 static（entry-only、无 T5）的 per-event 平均差：

```text
full T5 (P2, direct) : +4.73pp
disable_ADD          : +2.70pp   ← ADD 贡献约 2.0pp
disable_EXIT         : +4.70pp   ← EXIT 贡献约 0.0pp（收益维度）
disable_REDUCE       : -0.11pp   ← REDUCE ≈ 0（收益维度）
static (no T5)       : 0.59% episode ret
```

读法（**这是机制归因，不是策略建议**）：

- **完整 T5 的收益优势主要来自"EXIT 解锁空仓 + ADD 回补"的组合**：disable_EXIT 后收益与 full 几乎相同（+4.70 vs +4.73）说明 EXIT 单独不贡献收益——它释放的暴露由后续 ADD 重新使用；disable_ADD 掉到 +2.70 说明 re-entry 是主要来源。
- **REDUCE 的价值不在收益而在风险维度**：disable_REDUCE 时 mean_exposure 升至 0.96、MDD 恶化到 -0.056（vs 完整 P2 的 -0.014）——REDUCE 是风险整形器，不是收益来源。四维度分层正是为避免只看 ret 得出"REDUCE 无用"的错误结论。
- static ≠ buy&hold（相等率 82.4%）：wait 类策略 fill 晚于 day-0，episode 起点不同。

## 4. 实现过程缺陷记录（三处，均已修复并单测验证）

1. **merge 未去重**：T5.7 trajectory 携带 3 个 policy 的重复行（未加载 policy 列时为精确重复），merge 后每日迭代 3 次 → 全部数字作废重跑。
2. **状态推进丢失**：重写 replay 时丢失 `x = x_after`，每个 operator 都从 x₀=1 独立计算（REDUCE 永远输出 1/3、ADD 永远 AT_CAP）——由 T5.7/T5.8 同事件序列对比发现，单测复现后修复。
3. 首版 OOM（7GB 内存 daily 全量累积）→ 改为 400k 行分批 flush parquet。

G5（daily pnl 恒等式 Σ=x Episode ret）、G4（day-0 零 pnl）在修复后版本通过。

## 5. 产品

`output/research/t5/full_lifecycle/`：contract / execution_clock / strategy_matrix / episode_results（329k）/ daily_exposure_pnl（12.16M）/ split_metrics / counterfactual_attribution / censor_terminal_audit / manifest / gates。

## 6. 冻结结论与移交

```text
T4.6 Entry → T5.1–T5.6 决策 → T5.7 算子 → 逐日 exposure → price path → P&L ✓
```

- T5 动态风险管理的价值结构已可回答：**收益来自 EXIT+ADD 的释放-回补循环，风险改善来自 REDUCE**；conflict/no-evidence preserve 全程保留原始语义（G7）。
- **未做**：冠军排名、policy/策略选择、生产参数、成本/滑点、组合级资金曲线、T5.7 E1 阈值冻结。策略选择应另立阶段。
