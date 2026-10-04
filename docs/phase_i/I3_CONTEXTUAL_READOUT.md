# CSR-8 Phase I / I3 — Contextual Readout (Cluster-Robust)

*Contract:* `i2_contextual_preregistration-v1`（sha `e32bf614…`，commit `eddd1ff`）+ `addendum-1`（EXT-1 三态分类 / EXT-2 有效证据量，均为用户显式授权扩展）
*Mode:* 严格按冻结清单执行——不增变量、不改门槛、不补 context；DEFERRED 层保持 DEFERRED；资金状态标签未动。
*Machinery:* `scripts/phase_i_i3_contextual_readout.py` · 机器版 `i3_contextual_readout.json`
*一致性:* 三关系 naive 统计（nA/nB/dR5/Cliff's δ）与冻结 third readout **逐位一致**（断言全 PASS；δ 口径对齐经典定义 (|x>y|−|x<y|)/n，平局不计入）

## 结果总表

| 关系 | naive dR5 (nA/nB) | date-dedup dR5 (dates A/B) | leave-max-cluster-out (case / dedup) | R4 门 | 分类 |
|---|---|---|---|---|---|
| stock_layer: ND vs NO_PIT | **−0.0256** (86/18) | −0.0393 (74/**4**) | −0.0502 / −0.0533（剔 2021-04-06，9 例） | d ✗（4<5 日） | **DESCRIPTIVE_ONLY** |
| ETF expansion 4 vs 8 | **−0.0635** (15/17) | −0.0163 (11/8) | −0.0356 / −0.0048（剔 2021-03-08，7 例） | 全 ✓ | **THEORY_ELIGIBLE** |
| ETF expansion 8 vs 9 | **+0.0436** (17/14) | +0.0433 (8/11) | +0.0157 / +0.0319（剔 2021-03-08，7 例） | 全 ✓ | **THEORY_ELIGIBLE** |

三关系在 naive / date-dedup / leave-max-cluster-out 三口径下**方向全部不变**；差异只在资格与量级（见下）。

## 逐关系结论

### 1. ND vs NO_PIT — DESCRIPTIVE_ONLY（预注册预期，如期发生）
**允许表述（按裁定原文冻结）**：当前冻结语料中存在稳定的描述性差异（且去聚类后 |d| 反而扩大 0.0256→0.0393），但由于 NO_PIT 的观察日多样性不足（18 例仅覆盖 4 个观察日），**无法排除日期环境集中造成的结构依赖，因此不具备理论升级资格**。资格缺陷在看到 I3 数值前已冻结，无"结果漂亮放松门槛"的空间。

### 2. ETF 4 vs 8 — THEORY_ELIGIBLE（方向稳健，量级显著缩水，须并列披露）
四门全过，但 R2 双列必须如实呈现：**naive |d|=0.0635 → dedup 0.0163（缩水 ~75%）→ leave-max-cluster-out dedup 仅 0.0048（近零）**。方向跨日期环境保持，原始量级高度依赖日期聚类。理论层只可引用"方向"，不得引用 naive 量级。

### 3. ETF 8 vs 9 — THEORY_ELIGIBLE（方向与量级双稳健）
dedup 后 d=+0.0433（与 naive 0.0436 几乎不变），LCO 后 +0.0319。**唯一在方向与量级上都穿越聚类的预注册关系**——进一步支持"扩张计数=离散 regime 档位"的 I1 解读。

## 有效证据量（EXT-2，以后与 nA/nB 并排引用）

| 关系 | raw cases A/B | distinct dates A/B | max date multiplicity | dedup effective N A/B |
|---|---|---|---|---|
| ND vs NO_PIT | 86 / 18 | 74 / **4** | 9（2021-04-06） | 74 / 4 |
| ETF 4 vs 8 | 15 / 17 | 11 / 8 | 7（2021-03-08） | 11 / 8 |
| ETF 8 vs 9 | 17 / 14 | 8 / 11 | 7（2021-03-08） | 8 / 11 |

## C2 杠杆温度分层（仅描述；样本极小，全部不构成判断）

| 关系 | margin 20d | nA/nB | dR5 |
|---|---|---|---|
| ND vs NO_PIT | − | 15/6 | −0.0172 |
| ND vs NO_PIT | + | 12/2 | +0.0128（SMALL-N） |
| ETF 4v8 / 8v9 | 各层 | ≤2/侧 | 层内几乎全部空侧或 SMALL-N，不可报告 |

**禁止解释横幅**：两融变量只是杠杆参与温度（参与者混合，CSR-4 MULTI 口径）；**绝不**解读为大盘趋势 / 国家队态度 / 主力加减仓 / 行业资金流入 / 全市场风险偏好代理 / 因果陈述；context 仅是 modifier，资金状态标签不可变。

## Erratum（append-only，不改冻结合同）

**ERR-I3-1（C2 覆盖率修正）**：I2 合同 `design_audit.schema_probe` 措辞 "every packet carries 20 margin records" 系由 5 个探测包（o7/o50/o100/o119/o128，恰好均有）过度概括。I3 全量核查：**45/122 packet 携带两融证据（margin_szse 24 / margin_sse 21），77 个无 margin endpoint**。probe 描述的窗口结构（obs≤T−1、avail≤T）对全部 45 个成立，PIT-safety 不受影响；C2 实为**部分覆盖 modifier（37%）**，其分层交叉表相应仅为小样本描述。冻结合同正文未改动。

## I3 决策输出（供裁定，不自行推进）

1. 两个 ETF 预注册关系均 **THEORY_ELIGIBLE**（Tier-1 聚类稳健性通过）→ 按你的裁定，"若能通过，才值得进入下一阶段做真正的 market/sector conditional interpretation"——**该升级的 GO/NO-GO 留给你裁定**，I3 到此止步。
2. 若 GO：DEFERRED 的 `broad_index_regime` / `sector_regime` 仍需单独数据授权 + 溯源 erratum，且必须沿用 R4 硬门。
3. ND vs NO_PIT 若要有升级资格，出路是**新语料补采样 NO_PIT 观察日多样性**（≥5 不同观察日）——生产问题，非分析问题。
