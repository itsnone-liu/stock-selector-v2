# CSR-8 Phase I / I1 — 128-Case Structural Atlas

*Authority:* Phase H final freeze `csr8-phase-h-final-freeze-v1` (commit `9dfc516`) + third readout (commit `3f46515`).
*Mode:* **read-only** over sealed/frozen artifacts — no production, ordinals 1–128 only, capital-state labels unchanged, no new statistical claims.
*Machine atlas:* `docs/phase_i/i1_structural_atlas.json` (128 per-ordinal cards, deterministic rebuild via `scripts/phase_i_i1_structural_atlas.py`).
*Hypothesis semantics:* frozen CSR-3 registry (`H01 吸筹 / H02 锁筹 / H03 主升 / H04 外部参与 / H05 派发 / H06 主导退出后`) — preregistered, NOT validated claims.

## Card coverage

| Segment | n | Card contents |
|---|---|---|
| ordinals 7–128 (readout corpus) | 122 | identity (epoch, T, opaque entity, paired ordinal, packet sha) + capital state (stock layer, actor records, ETF per-record structure) + 6 annotation judgments + R3/R5/R10 + taxonomy status |
| ordinals 4–6 | 3 | 同上 except path outcomes (outside readout corpus) |
| ordinals 2–3 | 2 | 无 national_ctx（pre-NC era），packet+annotation+sealing |
| ordinal 1 | 1 | sealing only |

Campaign structure (from the freeze): 64 opaque entities × 2 production epochs — each ordinal N pairs with N±64 (same entity, different packet bytes and observation date T).

---

## 1. The 20 non-dominant ordinals — candidate classification

**Deviation pattern (uniform across all 20):** every deviation is a *support* deviation on a lifecycle hypothesis fed by stock-layer records — `rt_H01/H02/H05 = SUPPORTED_PARTIAL` (18 cases) or `H01+H05 = MIXED` (2 cases). **Observability is OBSERVABLE in all 120 judgments; reference fields never deviate.** The non-dominance is a *graded-evidence* phenomenon, not a missing-data or unjudgeable phenomenon.

| Candidate class | n | Cases | Deterministic rationale |
|---|---|---|---|
| **A — taxonomy granularity boundary** | 16 | 8, 15, 41, 48, 51, 53, 63, 67, 68, 72, 79, 105, 112, 115, 117, 127 | NATIONAL_ACTORS_PRESENT：披露在场记录对生命周期假设给出分级支持，而案例级 `stock_layer_summary` 是二元轴——分级证据无处安放 |
| **B — mixed capital state** | 2 | 44, 108 | 2 条 actor 记录同时喂 H01（吸筹方向）与 H05（派发方向）MIXED 支持——相反方向的分级证据并存 |
| **C — time-scale misalignment** | 2 | 55, 119 | 当期非披露 + 前期持仓记录并存（同一披露状态在同一报告可得窗内的两个观察日被重复采样；o55/o119 的 stock 记录逐字段相同） |
| **D — PIT observation insufficient** | 0 | — | 全部 20 例 OBSERVABLE 且有记录，无 D 候选 |
| **E — genuine new structure** | 0 | — | **没有任何案例需要现有 taxonomy 字段之外的结构** |

**I1 结论（证据层）：taxonomy_v3 在本语料上没有证据基础。** 20 例全部可用 A/B/C 解释——即现有字段的粒度与对齐问题，而非缺失类别。（最终分类保留给人工复核；本表为确定性候选分类。）

## 2. The 3 REVERSED pairs — forensic result

三对 REVERSED（`etf_contraction_count` 1v8 / 5v8 / 6v8）**共享同一个 cell-8 成员池**，且机制已确定性定位：

```
64 语料 cell-8 (n=7)            128 语料 cell-8 (n=19)
d(1v8) = +0.0224                 d(1v8) = −0.0273
        │                                ▲
        │              64→128 新增 9 例：T=2021-04-06 全部同构
        │              （epoch-2、NO_PIT_VISIBLE_REPORT、c=8/e=0 全收缩快照）
        └──────── 单一观察日簇 R5 中位 −0.0045 ──→ 把 cell-8 中位数
                 从 −0.0362 (其余10例) 抬到 −0.0088，符号翻转 ──┘
```

- 簇成员：o66/70/75/92/93/101/106/107/114（占 128 语料 cell-8 的 9/19）
- **仅取 epoch-1 成员时 64 语料符号精确复现**（d=+0.0224）
- **共同条件 = 单一观察日的同构批量采样（语料设计特征），不是市场结构变化**

**Context 线索（记录、不建层）：** 语料存在观察日聚类（2021-04-06: 9 例；2021-03-08: 7 例，均来自 epoch-2 采样设计）。任何未来的 conditional layer 必须把观察日聚类作为一等 context——这是"市场环境 × 资金结构"层必要性的第一份正面证据，但 I1 按裁定只记录、不构建。

## 3. The 3 preregistered PRESERVED relations — semantic decomposition

### 3.1 `stock_layer_summary`: NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10 vs NO_PIT_VISIBLE_REPORT
- **122 例数字**：n=86/18，dR5=−0.0256，Cliff's δ=−0.249（符号一致、合格）
- **状态定义**：NOT_DISCLOSED=当前 PIT 可见披露窗口内不在任何最新可见十大名单披露中（只约束"最新可见报告的在场披露"，不约束持仓是否存在）；NO_PIT=无任何 PIT 可见报告可引用（无记录≠无持仓）
- **可观察证据**：`stock_capital_records.state` 与报告期可得性，全部从披露通道推导
- **允许解释**：两种"资金在场不可确认"状态的后续 R5 路径分布存在稳定描述性差异；差异可能源于披露节奏、报告期可得性与参与结构的系统性差别
- **禁止解释**：NOT_DISCLOSED=国家资金退出/看空/减仓；NO_PIT=无资金参与；任何因果或控制推断

### 3.2 `etf_expansion_count`: 4 vs 8
- **122 例数字**：n=15/17，dR5=−0.0635，δ=−0.318
- **定义**：PIT 可见 ETF 份额快照中 EXPANSION（份额净增）计数档位
- **允许**：配置通道不同扩张强度档位与后续路径分布的稳定描述性差异（4<8）
- **禁止**：个体 ETF 申购主体识别（该层 actor_attribution FORBIDDEN）；因果陈述；单调外推

### 3.3 `etf_expansion_count`: 8 vs 9
- **122 例数字**：n=17/14，dR5=+0.0436，δ=+0.479
- **允许**：高强度档内部 8<9 的反向差异支持把扩张计数读作**离散 regime 档位**而非连续剂量
- **禁止**："9 只更牛/更熊"的单调解读；把 8/9 边界解释为机制阈值（边界位置由样本分布决定，未经预注册）

**三张卡的共同边界：全部是描述性结构关联的持久化，不是因果识别、不是 alpha、不是国家资金控制证据。**

---

## I1 conclusions → decision inputs

1. **taxonomy_v3：无证据基础**（A16/B2/C2/D0/E0）。若未来要动 taxonomy，正确方向是给 `stock_layer_summary` 加分级/混态表达（A、B 类的证据），不是新增类别。
2. **REVERSED 已解释**：单一观察日簇的采样构象效应，epoch-1 限制下 64 符号复现。探索性结构（12 PRESERVED / 18 WEAKENED / 3 REVERSED）中，REVERSED 属"采样依赖结构"，非"市场结构变化"。
3. **contextual layer（市场环境 × 资金结构）获得第一份正面必要性证据**（观察日聚类直接改变 cell 级中位数），但按裁定 I1 不建层。
4. 三个 PRESERVED 关系的允许/禁止解释边界已逐条冻结在卡上，可直接作为解释树（资金证据→状态→路径特征→环境修饰→允许/禁止推论）的叶子约束。
