# CSR-8 Phase I / I4B — External Market Context Readout

*Contract:* I4A `sha b1278342…` + `addendum-semantic-1`（两层证据语义：R4(d)≥5=理论资格门；≥3=仅输出覆盖门）
*Machinery:* `scripts/phase_i_i4b_market_context_readout.py` · 机器版 `i4b_readout.json`
*一致性:* 两关系 overall 统计与 I3 报告**逐位一致**（断言 PASS；ND/NO_PIT 描述表 ALL 层 d=−0.0256 亦与 I3 一致）

## 主结果

### ETF 4 vs 8 → **CONDITIONAL**

| 层 | dates A/B | naive | date-dedup | LCO case | LCO dedup | 判定 |
|---|---|---|---|---|---|---|
| overall | 11/8 | **−0.0635** | −0.0163 | −0.0356 | −0.0048 | I3: THEORY_ELIGIBLE（方向稳健/量级脆弱） |
| **UP** | 8/5 | −0.0863 | −0.0375 | −0.0955 | −0.0371 | **层内 R4 全过（≥5日+四口径同号）→ 理论级** |
| DOWN | 3/3 | +0.0513 | +0.0513 | +0.0136 | +0.0136 | **方向翻转** · LOW_COVERAGE（仅输出覆盖，非理论证据） |

### ETF 8 vs 9 → **CONDITIONAL**

| 层 | dates A/B | naive | date-dedup | LCO case | LCO dedup | 判定 |
|---|---|---|---|---|---|---|
| overall | 8/11 | **+0.0436** | +0.0433 | +0.0157 | +0.0319 | I3: THEORY_ELIGIBLE（方向+量级双稳健） |
| **UP** | 5/8 | +0.0478 | +0.0551 | +0.0570 | +0.0546 | **层内 R4 全过 → 理论级**（量级依旧稳） |
| DOWN | 3/3 | −0.0242 | −0.0242 | −0.0250 | −0.0250 | **方向翻转** · LOW_COVERAGE |

**机器分类（冻结合同确定性规则）**：两关系均为 CONDITIONAL——总体方向保持 I3 方向，且恰一层（DOWN）翻号。按裁定，冻结为 CONDITIONAL，**不解释哪个才是"真正结果"**。

## 允许的分层陈述（addendum 语义）

1. **UP 层（理论级，满足 R4(d)≥5 + 四口径同号）**：在 UP 市场环境（120 日中位数口径）下，4v8 的 R5 差异方向（−）与 8v9 的方向（+）在 observation-date 去聚类与最大簇剔除后均保持；8v9 在 UP 层连量级都稳（dedup 0.0551 ≈ naive 0.0478）。
2. **DOWN 层（仅输出覆盖）**：两关系方向同时翻转且四口径一致——形状规整（UP: 4<8>9；DOWN: 4>8<9，**非单调排序的镜像**），但 3 日/侧不满足理论资格门，不得解读为市场机制证据，只能记录为"现有证据中未排除环境调节"。
3. **合并语义**：ETF 扩张计数与 R5 路径的描述性关联**方向依赖广义市场环境**（在可观测证据内）；跨 context 完全稳健（CONTEXT_ROBUST）未获支持，8v9 的"cross-context structural relation"候选**未成立**（DOWN 翻转），但其 UP 层表现仍是全语料最强的单环境结构结果。

## ND vs NO_PIT（描述性，禁升级）

| 层 | n ND | n NO_PIT | d(median) |
|---|---|---|---|
| ALL | 86 | 18 | −0.0256（=I3） |
| UP | 62 | 17 | −0.0224 |
| DOWN | 24 | **1** | −0.0620（NO_PIT n=1，不可读） |

**横幅**：DESCRIPTIVE_ONLY · EXCLUDED FROM RE-UPGRADE；DOWN 层 NO_PIT 仅 1 例，任何数字不得引用。

## 禁止解释横幅（全文有效）

禁止因果语言（"第 9 档 ETF 扩张导致 R5 上升"❌）；ETF 层禁止 actor 归因；"regime threshold" 语言在 DOWN 覆盖补足前继续禁用；120 日中位数指数口径是**粗粒度环境 modifier，不是大盘状态模型**；UP=94/DOWN=28 语料偏斜已预披露，DOWN 层波动不得解读为市场机制异常；资金状态标签不可变。

## 理论图景（描述层归纳，供裁定）

I4B 后的图景恰是你预告的一半：**ETF 扩张档位的结构关联在两种市场环境下都呈非单调形状，但排序在 UP/DOWN 间镜像**——比"ETF 越多越怎样"的连续效应叙事强得多，支持"不同档位=不同稳定性的离散资金状态"的离散 regime 假说，但 DOWN 层 3 日覆盖使"跨环境排序"无法成为理论结论。若要把 CONDITIONAL 升格为理论层关系，需新语料补 DOWN 环境观察日多样性（生产问题）。
