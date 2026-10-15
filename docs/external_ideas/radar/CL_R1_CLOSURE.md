# CL-R1 — 正式关闭声明（CLOSED NEGATIVE MECHANISM RESULT）

关闭日期：2026-10-14（用户终审批准）

## 裁决

\[
\boxed{\text{R1 = CLOSED NEGATIVE MECHANISM RESULT}}
\]

不再补实验。G3 距离曲线明确不补：在 G2（独立性）与 G4（行为后果）已失败的前提下，继续扫 1%–20% 距离网格会退化为"挑一个最漂亮的距离"，违反预注册精神。提前终止是合法研究终点。

## 三层价值（用户终审框架）

### 第一层：否掉一个容易被误用的因果解释

被否证的故事：

```text
历史上方成交密集 → 套牢盘多 → 抛压大 → 主力推不动
```

证据只支持前后变量稳定共变，不支持中间因果链。由此立下体系级边界：

> OHLCV 重建出的历史成交成本密度，只能作为价格/流动性结构描述，不能自动升级为真实持仓供应。"筹码峰""套牢盘""主力成本"这类解释在 A 股工具生态中最易被过度引申，本体系一律禁用。

### 第二层：验证了 CL Radar 研究制度本身

R1 走完的完整链条：

```text
外部算法 → 物理直觉 → 源码审计 → 数据合同缺陷 → 消融
→ 漂亮的原始关系 → 混杂控制 → 关系收缩 → 行为验证失败 → 停止
```

关键纪律点：stock-cluster bootstrap 结果很漂亮（84 股中位 −0.37~−0.63，区间同号），但它只证明 raw association 稳定，不证明独立机制。没有因此重新包装。此模板适用于未来所有类似对象（主力资金指标、筹码集中、CVD、absorption、AVWAP、order flow）：第一轮相关再漂亮也不得升级。

### 第三层：保留统计事实，不保留生产变量

永久知识条目（同步存入项目记忆）：

> 当前价附近历史成交密度与较低 price-impact efficiency 和较低突破命中率存在稳定原始关联，但该关联很大程度与流动性、价格状态和规模共变，尚无独立资金供应机制证据。

不创建 `LocalSupplyState` / `ChipSupplyState`。重启前提：出现真实持仓、Level2、账户持仓结构或直接卖出行为数据，并重新预注册；禁止以调核函数/bins/decay/窗口/阈值的方式挽救。

## 证据链存档

| 阶段 | 文档 |
|---|---|
| 源码+数据合同审计 | `CL_R1_ASTOCK_CHIP_AUDIT.md` |
| M0–M3 消融 | `CL_R1_ABLATION_REPORT.md` |
| 机制对照 | `CL_R1_MECHANISM_REPORT.md` |
| R1-B 预注册 | `CL_R1B_LOCAL_SUPPLY_PREREGISTRATION.md` |
| R1-B 控制与行为 | `CL_R1B_CONTROLS_BEHAVIOR_REPORT.md` |
| R1-B2 终止报告 | `CL_R1B2_INDEPENDENT_MECHANISM_CLOSURE.md` |
| 数据 | `data/cl_radar/r1_chip_ablation/`（ablation.csv.gz、summary.json、r1b_*.json） |

## 下一步（用户改定的 CL Radar 顺序）

```text
R1 Chip/Local Supply        — CLOSED
R2 Event-Anchored Cost/AVWAP — ACTIVE（预注册见 CL_R2_AVWAP_PREREGISTRATION.md）
R3 Effort vs Result / Absorption-Supply
R4 Price Impact / Opening EI integration
Profit Mass / Trapped Mass   — 后移（历史 OHLCV 推"谁被套"假设过重）
```
