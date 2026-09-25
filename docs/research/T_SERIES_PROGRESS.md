# T 系列研究进度（进度快照）

更新时间：2026-09-25（T5.8 提交后）
记录方式：commit + 冻结报告为唯一事实源；本文件为进度索引。

## 当前状态

**T5 全链条已闭环，T5.8（bc8d6a7）已提交，待用户验收冻结。**

## 版本链（冻结点）

| 阶段 | commit | 内容 |
|---|---|---|
| T5.1 | `62b3feb` | Path Observations（lifecycle20 突破事件 27,422 个） |
| erratum | `c6dc354` | T5.1 勘误 |
| T5.2 | `af2dac7` | raw_state_v1（C0–C6，priority C6>C5>C4>C1>C3>C2>C0） |
| T5.3 | `a33c9b5` | transition + operational_state_v1（C1 hysteresis+C6 立即） |
| T5.4 | `ebfc490` | state/transition/short-path → outcome 映射（10/10） |
| T5.5 | `aac1f9f` | action evidence + 四独立多标签 eligibility（10/10） |
| T5.6A | `c4a3056` | conflict census：16 vector 仅 6 种出现，1100 日加权 58.3% |
| T5.6B/C | `ad7fd2c` | containment-based resolution（10/10）：90.75% resolved / 5.93% conflict / 3.34% no-evidence |
| T5.7 | `8c4a992` | exposure contract + 六算子 + P1/P2/P3 无 P&L replay（10/10） |
| T5.8 | `bc8d6a7` | full lifecycle simulation：真实 x₀、12-cell 矩阵、反事实归因（10/10） |

## T5.8 核心结论

- 12-cell（4 entry × P1/P2/P3，329,064 episodes / 12.16M 日行）三段方向稳定：P1<P2<P3 排序在 dev/val/conf 全部保持。
- **反事实归因**：full T5 vs static +4.73pp；收益主要来自 EXIT 解锁空仓 + ADD 回补循环（disable_EXIT ≈ 不掉收益、disable_ADD 掉至 +2.70pp）；REDUCE 收益维度 ≈ 0 但风险维度关键（disable 时暴露 0.96 / MDD -0.056）。
- direct_chase ≡ staged_entry（close-fill 口径下 T4.6 两策略在 T5 事件集语义重合，已披露）。
- MAX_HORIZON 右删失 8.1%（val 段最高 10.6%），与 LIFECYCLE_END 结算分开披露。
- T5.8 实现过程三个缺陷已修复并披露：merge 未去重（3 policy 重复行）、replay 状态推进丢失（`x = x_after`）、OOM（改分批 flush）。

## 未做（边界移交）

冠军排名、policy/入场策略选择、成本/滑点、组合级资金曲线、E1 dust 阈值冻结、re-entry 语义、T5.7 真实分批 x₀ 之外的入场模拟。**策略选择应另立阶段**（不在 T5.8 内偷偷完成）。

## 流程纪律（不变）

开工令即批准；只读继承上游冻结产物；dev-only 阈值（val/conf 只评不改）；十道 Gate 全 PASS 才冻结；commit + 冻结报告为唯一事实源；用户逐阶段验收。

## 环境备忘

- 必须用 `/root/venv/bin/python3`（系统 python3 pandas 二进制损坏）。
- 本机 7GB 内存：大表模拟需分批 flush parquet（T5.8 教训）。
- 数据要点：cs 表 segment 列、年份列 `year_s`；outcome clock 停牌跳过、incomplete 保留缺失；`ret_1d_log` at day d = (d-1, d] 区间收益。
