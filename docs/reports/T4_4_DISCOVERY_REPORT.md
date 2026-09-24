# T4.4 — Context Structure Discovery（Context 拓扑结构冻结）

**阶段**：T4.4（结构发现；非交易规则/评分模型/仓位策略）
**基线**：T4.3 @ `28b1d48`（HEAD 断言一致）；八道 Gate 全 PASS
**开工令**：T4.4 八节方案

---

## 1. 交付物（output/research/t4/discovery/）

`t4_sector_context.parquet`（27,422×LOO sector primitives，retrospective 标记）、`t4_market_2d_structure.parquet`（4×4 map+条件化+polish）、`t4_market2d_yearly.csv`、`t4_market_sector_structure.parquet`（M→S）、`t4_three_layer_structure.json` + `t4_three_layer_cells.parquet`（M×S+个股平行性）、**`t4_structure_decision_matrix.csv`**、gates/manifest/determinism json。

代码：`src/t4/discovery/{sector_primitives,analysis_discovery}.py`、`scripts/run_t4_4.py`、`scripts/t4_4_gates.py`。

## 2. 方法要点

- **Sector primitives（LOO，§3）**：sec_breadth_d5_loo / sec_nh_density_loo（板块内 5 日均上涨占比、20 日复权新高占比，**聚合剔除 focal stock**，只用可分解统计量 count/sum）；sec_rel_breadth_d5（−市场同窗 breadth）；sec_ret20_mean_loo（等权均值收益 20 日复合，LOO 可分解口径——与 T4.1 中位口径差异已在 dictionary 披露）；sec_rel_strength20。全部 as-of ≤T0；as-of expanding percentile（dates<T0，min 120，(day,gate) 去重防事件密度加权）。**membership 仍为 2026-09-21 快照 → 整族 retrospective_context_only**（G2 双轨验证：价格截断重算 + 归类披露）。
- **结构发现（§4/§5）**：离散 Q 表 + Tukey median polish（纯 numpy 可加分解：grand+行效+列效+残差，交互强度=RMS(resid)/RMS(主效应)）替代 GAM——同为 response surface 结构检验，不建预测器；条件化对比沿用 T4.3 双 estimand + 双簇 bootstrap。

## 3. 决策矩阵（本阶段正式输出）

| 结构问题 | 决策 | 关键证据 |
|---|---|---|
| **Market 维度** | **KEEP_2D** | breadth\|new-high EW +3.3/+5.7pp、new-high\|breadth +2.7/+4.7pp（DB 同向 +1.2~+5.6pp）；polish ratio h20=0.23。两轴条件化后均有稳定增量，语义不重叠（参与广度 vs 趋势成熟度）→ 保留二维市场状态 |
| **Sector 独立性** | **SECTOR_SUBSUMED_BY_MARKET** | sector rel strength Q4−Q1 within market Q1-Q4：EW −4.0/−2.2/+0.4/−1.1pp、DB −0.02/−0.6/−0.25/−1.8pp——**无稳定正增量**（四个 DB 全负/零）；rel breadth 同样弱且方向不稳。控制市场后，强板块相对强弱**不**对应更好 breakout 路径 |
| **M×S 可加性** | **INTERACTION_CANDIDATE（弱）** | polish ratio 0.39 但 DiD EW +0.92pp、p=0.26 不显著；残差集中于边缘格（含 1 空格）。按 §7 "交互默认不进入"：**不升级**——尤其 sector 主效应本身不存在，交互无解释对象 |
| **Stock 全局阈值** | **GLOBAL_THRESHOLDS** | load/ref60 的 hi−lo 在 (M,S) 四格全部同号（load 中位 −1.33pp、spread 1.41pp；ref60 −2.22pp、spread 0.76pp）→ T4.3 平行结论在加入 sector 后仍成立 |
| **amount 轴** | **DIAGNOSTIC_ONLY** | 继承 T4.3 趋势污染结论 |

## 4. 结构解读（供状态引擎设计，非交易结论）

```
Market Layer（2 维：breadth + new-high，PIT expanding rank）
   ↓（平移路径，不与个股状态交互）
[Sector Layer：不建独立层——14 门类快照口径下无控制市场后的独立增量]
   ↓
Stock T0 State（load/ref60 等全局阈值，跨环境平行）
   ↓
Position sizing / Entry policy（后续阶段）
   ↓
Post-entry Dynamic Path State（下一大阶段）
```

- 用户开工令预期的"最理想结构"（Market 2 维 + Sector 1-2 维 + Stock 原定义 + additive）**前三项兑现了 3.5 项**：唯一偏差是 Sector 层在当前口径下不值得独立建模。
- **Sector 结论的证据边界（必须随结论传播）**：①14 门类粗粒度（C 占 69.3%，板块内异质性未被利用——83 大类或更细粒度可能改变结论，属 T4.4 未做、留给后续粒度研究）；②membership 非历史 PIT；③LOO 只解决 focal 污染，不解决"板块内同期多只突破"的簇内相关；④检验对象是"突破事件后续路径"层面，不等价于"板块轮动无信息"。
- 分年 polish ratio（0.47/0.43/0.50）显示市场二维 surface 有稳定非可加成分（主要在边缘格），但双向条件增量三年存在——2 维保留决策不依赖单一格。

## 5. 八道 Gate（全 PASS）

G1 lineage（27,422 宇宙/冻结分位继承）/ G2 PIT（mkt breadth 截断重算 0 mismatch + retrospective 100% 标注）/ G3 LOO 对账（5 日窗 nh density 独立重算 0 mismatch）/ G4 覆盖（rel_strength 0.9987）/ G5 EW-DB（双 estimand 落盘、决策矩阵引用 DB）/ G6 稳定性（分年 polish 全在 + sector DB 同号）/ G7 分解守恒（median polish 恒等式闭合误差 <1e-9）/ G8 leakage（sector context 无 outcome 字段 + 双跑 hash 一致）。

**过程披露**：G3/G6 首跑 FAIL 均为 gate 脚本自身缺陷（重算漏 5 日窗均值；把"方向一致"误写为"必须为正"——修正后全过，研究产物未动）；双跑 determinism 首报 false 为 hash 比较对象列不对齐的假阳性，独立逐列诊断证实数据完全一致后修正比较逻辑。

## 6. 阶段放行

八道 Gate 全 PASS，决策矩阵冻结。T4 剩余 T4.5（Exposure：状态×仓位档位）与 T4.6（Execution）待开工令；下一大阶段（突破后 Path State 演化）按 §6 边界与 Entry Context 物理分离。
