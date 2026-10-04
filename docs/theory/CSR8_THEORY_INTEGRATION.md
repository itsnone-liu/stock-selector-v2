# CSR-8 — Observable Capital-State Framework：Theory Integration (H → I → J)

*Document:* `csr8_theory_integration.json`（机器可审计引用链）· 本文档为 CSR-8 正式理论整合文档 v1
*Authority:* Phase H freeze `9dfc516` · Phase I freezes `cee5efd / eddd1ff / 5674101 / 664b35d+597e4a1 / c0937c9 / 670e226 (be1cdd7e…)` · Phase J freezes `683e2f3 (5ddd2866…) / 717200b / 3783d7b (73fc8dd3…)`
*Standing:* **PHASE K NOT STARTED · SECTOR DEFERRED · 129+ UNAUTHORIZED**

CSR-8 的产出不是"发现了某条交易规律"，而是一套**可审计、可解释、边界明确的资金结构研究框架**：它规定了资金状态如何被观察、证据如何分级、环境如何调节可检验性、以及哪些推论永久越界。本文按用户裁定的五章组织。

---

## 1. Observable Capital-State Framework — 观察体系

### 1.1 观察什么

一切变量都定义在 **PIT 决策时点 T**（该信息在 T 当日按冻结规则可见），分四层：

| 层 | 变量 | 观察语义 | 层级属性 |
|---|---|---|---|
| **Disclosure layer** | `stock_layer_summary`（NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10 / NO_PIT_VISIBLE_REPORT / NATIONAL_ACTORS_PRESENT / SOURCE_UNAVAILABLE） | **披露可见性状态**，不是持仓事实。NOT_DISCLOSED 的语义是"最新可见 Top10 中未出现"，永远不是"不存在持仓"（H05 教训，NC-ERRATUM-1.1） | per (entity, T) |
| **Market capital-state layer** | `etf_expansion_count`（13 只 SSE ETF 的 PIT 可见份额状态中 EXPANSION 计数） | **市场级离散资金状态**。是 T 的函数：同一观察日所有 case 共享同一状态值；其状态取值集合本身随时间漂移（Phase J new observation） | per T（市场级） |
| **Market context** | 000985 中证全指 raw close vs 120 日中位数（严格 trade_date<T）| **粗粒度环境 modifier**（UP/DOWN 二值）——不是市场状态模型 | per T |
| **Outcome layer** | R5 = 第 5 个 eligible 交易日的 hfq log-return | 纯价格路径，不承载资金行为语义 | per (entity, T) |

### 1.2 理论对象

**离散资金状态与后续价格路径之间的结构关联**（state structure），不是连续剂量效应。理由（已冻结）：对 ETF expansion 的 4/8/9 三个已观察离散状态，UP 环境呈 4<8>9、DOWN 低覆盖语料呈 4>8<9——两个方向的"单调 ETF 剂量"语言都与数据不兼容。

### 1.3 不观察什么（永久）

- **Actor intention**：任何层都不可观察"国家队/主力/机构意图"；ETF 层 actor_attribution=FORBIDDEN 是数据结构的一部分
- **资金流向因果**：框架测量共时/前瞻结构关联，不测量传导
- **连续阈值**：4/8/9 是观察到的离散档位，不是连续函数上的点
- **Sector**：in-repo 行业标签为单快照（2026-09-21），回灌历史=lookahead；DEFERRED 至独立 PIT 管线存在

---

## 2. Evidence Hierarchy — 证据等级

### 2.1 四级与单向门

```
DESCRIPTIVE_ONLY → THEORY_ELIGIBLE → CONDITIONAL → EXTERNAL VALIDATION
   (方向可报)      (R4 门+四口径)    (环境分层后)     (独立语料+support)
```

| 等级 | 资格门 | 否定的盲区 | 越级为何禁止 |
|---|---|---|---|
| DESCRIPTIVE_ONLY | 方向在语料内成立 | —— | 证据覆盖不足（如 NO_PIT 臂 4 日期）时"不能检验"≠"已检验且敏感"；二者科研意义完全不同（I2 ruling） |
| THEORY_ELIGIBLE | R4(d)≥5 distinct dates/侧 + naive/date-dedup/LCO 四口径同号 | 采样聚类（同日多例、最大簇） | 未过聚类门的量级是采样放大，不是效应 |
| CONDITIONAL | 环境分层后：总体保持方向且恰一层翻号（I4B 确定性规则） | 环境结构（UP/DOWN 组成混合） | 未分层的关系把 composition attenuation 当效应 |
| EXTERNAL VALIDATION | 独立语料 + 目标状态 support 足够 + 方向复现 | 状态支持/transportability | support 不足时强行判决 = 把覆盖问题伪装成方向答案 |

**两层语义（I4A-ADDENDUM-SEMANTIC）**：R4(d)≥5 = 理论资格门；≥3 = 仅输出覆盖门；3–4 日期层可贡献符号进分类，但永远不能独立支撑理论级陈述。

**升级只能靠新证据类型，不能靠重分析同一语料**（Phase I 后同 128 corpus 分析 CLOSED；Phase J 后同语料追加=NO-GO）。

### 2.2 为什么这些门存在——每个门对应一次真实失败

- date-dedup/LCO 门 ← Phase H 的 3 个 REVERSED 对被 I1 证明是 sampling-dependent（2021-04-06 九例聚类抬升 cell-8 中位数）
- 环境 CONDITIONAL 门 ← I4B 的 DOWN 翻号（3/3 日四口径一致）
- support 门 ← Phase J 的 INCONCLUSIVE（cell-8 1/12、cell-9 0/12）

---

## 3. Current Structural Findings — 当前结构发现（全冻结数字）

### 3.1 Established

- **语料身份链**：128 sealed cases，identity-lineage 违规 0，确定性可重建（I1 atlas）
- **UP 层理论级关系**（I4B，层内 R4 全过）：
  - **ETF 4v8 @UP**（8/5 日）：naive −0.0863 / dedup −0.0375 / LCO-dedup −0.0371——UP 环境中 4<8 方向为理论级
  - **ETF 8v9 @UP**（5/8 日）：+0.0478 / +0.0551 / +0.0546——8>9 方向理论级且量级稳定
- **日期聚类事实**：128 例 ≠ 128 份独立环境证据（机制确定性闭合）

### 3.2 Conditional

- **ETF 4v8 / 8v9 = CONDITIONAL**（I4B 判决，Phase J 后不变）：具有市场环境条件性的结构关系。4v8 细化："总体量级不稳定，UP 条件内明显更稳"（composition attenuation 为未证明候选）；8v9 "cross-context structural relation" 候选撤回
- **镜像排序（观察事实，措辞冻结）**："mirror ordering across the observed ETF-expansion levels 4/8/9"——UP: 4<8>9；DOWN: 4>8<9（DOWN 仅 discovery-level 低覆盖观察，3/3 日）

### 3.3 Descriptive-only（永久）

- **ND vs NO_PIT**：ALL d=−0.0256；NO_PIT 臂 4 日期 → 永久 DESCRIPTIVE_ONLY，禁升级

### 3.4 New Observation（Phase J）

- **目标状态支持的时间漂移**：12 个独立冻结 DOWN 日（2024–2026）的 expansion 值域 {0,2,3,4,4,5,7,7,8,10,11,12}，与 discovery 期（4/8/9 常态）显著不同——**ETF expansion count 不在时间上稳定占据同一组状态值**。记录为变量的属性；不构成假设证据；不升级为离散 regime 理论证明

### 3.5 Mirror ordering 的精确状态

**NEITHER VALIDATED NOR REFUTED**。这不是含糊——这是 Phase J 的判决本身：验证窗口未提供足够状态支持（INCONCLUSIVE — SUPPORT/COVERAGE FAILURE），方向读出未打开。

---

## 4. Context and Transportability — 环境与可迁移性

### 4.1 伪独立的三层解剖（CSR-8 最核心的方法论结构）

"更多数据 = 更多证据"在三个层次上依次失效，每层都曾被本项目实际撞上：

| 层 | 伪独立源 | CSR-8 中的证据 | 对应防线 |
|---|---|---|---|
| **Case 层** | 同一观察日的多个 case 共享市场环境与 cell | 2021-04-06 九例、2021-03-08 七例聚类实质移动 cell 中位数 | date-dedup + LCO + distinct-date 门 |
| **Date 层** | 相邻日期属于同一 regime episode，outcome 窗重叠 | Phase J ≥11 交易日分离规则（R10 窗不相交）；附录1语义边界：**≠ 统计独立 episode** | 窗口分离 + episode 语言禁令 |
| **State 层** | 市场根本未进入理论讨论的状态空间 | Phase J：cell-8 1/12、cell-9 0/12——384 case 无法产生任何臂级判决 | support 门 + INCONCLUSIVE 判决 |

### 4.2 Transportability 命题（进入理论主体，非附录）

```
一个关系在 discovery corpus 中成立
        ↓ 并不自动意味着
它可以在任意未来窗口被验证
        ↓ 因为
验证环境首先必须进入理论所涉及的状态空间
```

验证可行性 = **环境分布 ∩ 理论状态空间** 的测度。这是 CSR-8 最成熟的认识论成果：Phase J 证明了协议可以在 support 不足时正确返回 INCONCLUSIVE，而不是把覆盖问题伪装成方向答案——**"没验证出来"与"验证失败"是不同的事实**。

### 4.3 Support-First 设计约束（冻结，未来所有验证阶段）

```
预声明完整候选历史区间 → outcome-blind cell-availability census → 只判"能否验证"
→ 不能：终止该设计（不换窗口） → 能：按事先规则冻结 dates → 才进入 outcome production
```

禁止：扫年代找状态富集窗口（= support cherry-picking）。Phase K（Support-Aware External Validation）已按此概念冻结，NOT STARTED。

---

## 5. Theory Boundary / Forbidden Claims — 永久禁令

以下推论永久禁止，不因任何未来结果自动解禁（解禁需显式裁定 + 新证据等级）：

1. **因果语言**："第 N 档 ETF 扩张导致 R5 上升/下降"——框架测量结构关联，不测量传导
2. **Actor intention 归因**：国家队/主力/机构意图在任何层不可观察
3. **连续阈值**："8 是 regime threshold"、U 型/倒 U 型机制语言——只验证过 4/8/9 三个离散档位的两个预注册比较
4. **单调外推**："ETF 越多越……"——两个方向的单调语言都与观察不兼容
5. **镜像已验证**："DOWN 镜像已被证明"——只有 discovery-level 低覆盖观察；正确状态=NEITHER VALIDATED NOR REFUTED
6. **000985 regime = 完整市场模型**——它是粗粒度二值 modifier
7. **未来行业标签倒灌历史**——sector 单快照标签用于历史=lookahead
8. **为验证挑 support-rich 窗口**——support cherry-picking 等价于 outcome cherry-picking

**变更控制**：本框架随 commit 冻结；任何修改需 append-only erratum + 显式用户授权。等级提升只能来自新证据类型（新语料、新状态支持窗口、独立 PIT 管线），永不来自同一语料的重新分析。

---

## 结语

CSR-8 由三段弧线组成：**Phase H**（统计关系存在吗）→ **Phase I**（哪些结构在采样与环境解剖后仍站立：CONDITIONAL ×2 + UP 层理论级）→ **Phase J**（独立验证发现：理论的可检验性本身受状态支持约束）。

它的最终资产有两件：一个**带精确边界的条件性结构发现**，和一个**方法论命题**——资金结构研究的对象是离散状态，其证据必须按 case/date/state 三层独立性分级，其验证必须以状态支持为先决条件。

现有证据**已经足够形成一个稳定、有限、可证伪的理论框架**——本文件即该框架。
