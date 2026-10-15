# CL-R2 — Event-Anchored Cost (AVWAP) 预注册

状态：ACTIVE（2026-10-14 用户指定启动）

## 1. 研究问题（冻结）

**一个明确资金事件之后，累计成交成本中心（Event-Anchored VWAP）是否能解释后续价格围绕该事件成本的行为？**

禁止的问题形式：

- "AVWAP 能否预测收益"（Factor→Return，禁）
- 寻找"最优锚定日/最优窗口"（参数搜索，禁）

与 R1 的本质区别（测量假设更轻）：

```text
R1:    历史成交 → 推断谁还持有（重假设，已关闭）
R2:    事件后真实成交 → 累计平均成交价（无存活推断）
```

AVWAP 不声称识别持仓者，只是事件锚定的成交重心。

## 2. 构造定义（冻结）

锚定事件起点 `T0`，决策日 `T`：

```text
AVWAP(T0→T) = Σ amount_j / Σ volume_j ,  j ∈ [T0, T]
gap(T) = close_T / AVWAP(T0→T) − 1
```

- amount 与 volume 同源同日（market_ext amount；daily_fullmarket unadj volume），不做跨源拼接；
- 复权一致性必须先审计：amount/volume 是实际成交均价（未复权口径），与 qfq 比较前必须确认窗口内复权因子恒定；因子变化的 episode 单列，不得静默忽略；
- 缺 amount 或 volume 的日期：fail-closed 原则下记录覆盖率，禁止填 0（外部仓库零填教训）。

## 3. 事件定义（第一轮冻结为既有 CD-5 L4 episodes）

- 使用 `data/cd/l4_episodes.json.gz` 冻结事件（84 股、476 episodes 已在 B1 中使用）；
- 先做 Support-First 普查：每事件时长、amount/volume 覆盖率、复权因子稳定性、最小窗长；
- 普查不足（覆盖率低/因子断裂多）则报告 INSUFFICIENT_SUPPORT，不换事件定义硬做。

## 4. 机制结果变量（冻结族，晚挑禁）

围绕 `gap(T)` 与事件成本的行为：

1. **回踩承接**：价格首次回落至 AVWAP ±band 的行为（守住/跌破、触及时量能）；
2. **突破保持**：事件后价格在 AVWAP 上方/下方的停留结构；
3. **推进效率**：gap 分层下的 λ（B1 lambda_norm 复用）；
4. **重心迁移**：后续滚动成交重心相对事件 AVWAP 的漂移方向与速度。

行为结果仅取预注册的固定 band/窗口组合，不做网格搜索。

## 5. 混杂控制（先于分析声明）

log ADV20、当日换手、20 日波动、log close、20 日收益、PIT log 市值（close×outstanding_share）、市场 regime（可得则用）。R1 教训：原始关系必须先过控制再谈机制。

## 6. Gate（预注册）

- **G1 构造有效性**：AVWAP 与未复权典型价一致（单位/口径 sanity）；episode 内复权因子断裂率可接受并显式报告；
- **G2 独立性**：gap 与行为结果的关联在全部声明控制+stock/episode cluster 下仍存；
- **G3 行为一致性**：至少一个行为族（回踩承接/突破保持）表现出围绕事件成本的方向性结构，而非孤立阈值。

停止条件（提前关闭合法）：G2 失败或 G1 普查即 INSUFFICIENT_SUPPORT。失败即 CLOSE，不换锚、不调 band、不加核。

## 7. 解释边界

- AVWAP 是成交重心，不是"主力的成本"；
- gap 不识别持仓者意图；
- 全部结论为机制关联，非因果、非交易信号；
- 不修改生产、不建新 CapitalState。
