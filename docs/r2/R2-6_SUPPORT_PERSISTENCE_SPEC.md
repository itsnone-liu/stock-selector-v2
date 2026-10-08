# R2-6 H-support：资本成本支撑持久性 — 预注册规范（冻结于运行前）

与 R2-3 NO-GO 完全分线。不找吸筹前兆；检验：**历史资本成本结构定义的支撑区，未来遭卖压时是否比普通技术支撑/随机区域更有承接力。**

## 冻结项
1. **Zone 定义（PIT，只用 T0 及之前数据）**：
   - **ARM-A capital-cost**：过去 500 bar 量加权典型价分布，取累积量最密的连续区间（含 30% 成交量，100-bin 直方图滑动窗）为成本带，T0 前 ≥20 bar 收盘在带上方。
   - **ARM-B MA250**：[MA250×0.98, MA250×1.02]。
   - **ARM-C prev-low**：[250 日最低价×0.98, ×1.02]。
   - **ARM-D random**：同股 trailing-500 价格范围内随机分位带（剔除与 ARM-A 重叠），同触发逻辑，seed=42。
2. **触发事件**：价格自上方首次触及带（low ≤ zone_high 且此前 20 bar 收盘 > zone_high）。每股每带每月至多 1 事件。
3. **评估窗**：触发后 60 bar。预注册 7 指标：
   - P1 penetration = (zone_low − min_low_20d)/zone_mid
   - P2 recovery@5/10/20d（收盘回到 zone_high 上方）
   - P3 time_below = 收盘 < zone_low 的 bar 占比
   - P4 breakdown = 收盘 < zone_low×0.95 连续 ≥5 bar
   - P5 fwd R60（收盘/zone_mid−1）
   - P6 resilience = 同窗个股 maxDD − 市场 maxDD（L1 eq_ret 基准）
   - P7 repeated defense：同股 12 个月内第 1/2/3+ 次触碰的 P2/P4
4. **分层**：ALL/BULL/BEAR × 时代 21-23 / 24-26，不得合并回。
5. **成功标准（冻结）**：ARM-A 须在 P1(浅)/P2(高)/P3(低)/P4(低)/P6(高) 5 项中 ≥4 项同时优于 B、C、D 三臂，且双时代与 BULL+BEAR 层方向一致。不达标 → 「成本支撑无交易级区分力」，资金成本支撑理论收缩为描述性。
6. 禁止：事后改 zone 参数、加指标、挑层。结果无论正负一次定案。
