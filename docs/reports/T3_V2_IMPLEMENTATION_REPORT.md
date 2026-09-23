# T3 V2 实现报告：事件级特征层 + 路径结果层的实现与完整性验证

- 基线：`da933a1`（T3 V1 冻结：`docs/reports/T3_SUSTAIN_COVERAGE_AUDIT_V1.md`，path_label_v1 + t3_id_v1）
- 开工令：T3 V2 正式工单（只物化、不研究；冻结定义问题只报告、不自改）
- 实现代码：`src/stock_selector/research/t3_v2.py` + `scripts/run_t3_v2.py` + `scripts/t3_v2_gates.py` + `scripts/t3_gate_b_ref60.py` + `scripts/t3_determinism_check.py`；单测 `tests/test_t3_v2.py`（6/6 PASS）
- 产物目录：`output/research/t3_v2/`（gitignored；证据副本见 docs/reports/T3_V2_*.json）

## 0. 六 Gate 一览（先看这里）

| Gate | 内容 | 结论 | 关键数字 |
|---|---|---|---|
| ID | 主键唯一性 + 映射保留 | **PASS** | 27,422 唯一 `{code6}_{breakout_day}`；lifecycle 映射列全保留 |
| A | 任务二 y40 复算一致 | **PASS** | 可比集 26,126；`max_abs_diff = 0.0`（逐位一致）；删失判定 0 分歧；ref_only=0 |
| B | ref60 冻结口径 vs lifecycle 既有规则 | **FAIL（提请裁定）** | B0 基线复现 PASS；B1b 原生口径 100%；B1 ref60 过 68.27%；B2 重构 16,495 vs 27,422 |
| C | high×F 对账 hfq | **PASS** | 4,760 股 / 6,255,000 行每股常数性最差 9.5e-11；事件日 TDX↔库 close 27,310/27,310 一致 |
| D | PIT 截断重算 | **PASS** | 抽样 283 事件 × 3 层 = 849 次截断重算，0 处不一致（含周线未满周排除） |
| E | V1 覆盖数字复现 | **FAIL（V1 审计脚本缺陷，非实现分歧）** | 严格 §5 口径下 T0 有效=27,310/27,422；112 事件因子不可得；完整归因见 §2.5 |
| 确定性 | 双跑 hash | **PASS** | 6 个 parquet 产物逐字节一致 |

**总结论：数据层已按冻结定义完整物化并通过数值级一致性验证（A/C/D/确定性全 PASS），但两项必须人工裁定：①Gate B 的 ref60 与 lifecycle 20 日规则分歧（事件定义层）；②Gate E 暴露的 V1 审计覆盖表错误（112 个因子不可得事件被记为全有效）。裁定前不进入 V3。**

## 1. 交付物

| 文件 | 行×列 | 内容 |
|---|---|---|
| `event_master.parquet` | 27,422×17 | breakout_event_id + code6 + breakout_day + lifecycle 全映射列（lifecycle_id/anchor/end_reason/pullback_event_ids 等） |
| `event_labels.parquet` | 27,422×109 | §6.1 y{5,10,20,40}_raw/mkt_excess_log + 四态删失 + primary 资格 + §6.2–6.4 全套路径指标（MDD/恢复/新高/趋势维持/路径效率/回调量能/换手累计）|
| `event_labels_sensitivity.parquet` | 1,296×21 | imputed_last_available 敏感性口径（物理分离；h40 有值仅 22 个，原因见 §3.4） |
| `event_features_a1.parquet` | 27,422×25 | 周线结构（未满周不合成）/前高距离/MA 距离/TR 收缩/ref60+突破幅度，含观测数 |
| `event_features_b1.parquet` | 27,422×11 | vol_ratio_20 / turn20 均值 / 当日量价态 / 缩量上涨延续，含基准观测数 |
| `event_features_chip.parquet` | 27,422×19 | vwap_day(元/股，不除100) / price_to_vwap{5,10,20} / 成本带(60/120, 冻结候选待审)，严格全窗 |
| `integrity_report.json` | — | 计数/schema/缺失/覆盖/hash/Gates D+E |
| `y40_recalc_diff.{json,parquet}` | — | Gate A 证据 |
| `ref60_event_diff.{json,parquet}` | — | Gate B 证据（每股 margin 明细） |
| `high_f_reconcile.json` | — | Gate C 证据 |
| `determinism_check.json` | — | 双跑 hash 比对 |
| `factor_unavailable_events_112.csv` | — | Gate E 归因事件清单 |

代码约定统一执行：新产物统一 6 位零填充字符串 code；股票 ID 映射断言（`sh./sz. 前缀 ↔ code6`）在构建器内完成；事件宇宙未做任何增删。

## 2. 六 Gate 详情

### 2.1 Gate ID — PASS
27,422 个 `breakout_event_id`（`{code6}_{YYYY-MM-DD}`）全部唯一；code 全部 6 位零填充字符串；lifecycle_id 非空 27,422；映射列（anchor_day/end_day/end_reason/pullback_event_ids 等）原样保留。静态 membership **未进入任何特征表**（板块字段整个特征层不出现，无需 pit_eligible 标记；留待 V4 风险集层再议）。

### 2.2 Gate A — PASS（逐位一致）
- 参考实现 = `forward_y40_lib.build_events("breakout")`（任务二冻结代码+冻结输入，未改动）。
- 参考主样本 26,126；可比交集 26,126（ref_only = 0）；数值比对 26,126 事件 `max_abs_diff = 0.0`——公式逐位镜像（`log(pH/p0) − log(mclose[iH]/mclose[i0])`，float64 同序）。
- 删失/可标性判定 0 分歧；参考 22 个 imputed 敏感性事件全部落入我的敏感性文件且互为印证。
- my_only 1,296 的完整核算：1,137 参考侧 data_end_censored（日历末端）+ 112 因子不可得事件（identify 构建时即被剔除，见 §2.5）+ 25 excl_not_active（identify eligibility 先行剔除）+ 22 imputed（在 sens 不在 main）。
- 结论：**标签数学与任务二冻结实现在可比域上完全等价。**

### 2.3 Gate B — FAIL（分歧如实报告，事件宇宙未动）
四级子检查：

**B0 基线复现 PASS（数据漂移非影响证明）**：TDX 目录自冻结运行后发生大漂移（day 文件 14,753→35,311，codes 5,588→5,590）。以冻结配置（lookback=20）在当前数据上重跑 `classify_lifecycle`：55,646 个 lifecycle_id 集合相等，12 个关键列（含 breakout_day/end_reason/stage_sequence）**全部逐行一致**，breakout 事件 27,422 = 27,422。→ 追加数据全部在 2026-09-01 窗口外，新增 2 股无上游数据不产生生命周期；重构 diff 可干净归因于规则本身。

**B1b 原生口径 100%**：27,422/27,422 事件满足 `close(TDX 未复权) > max(前 20 个 TDX close)`。→ 事件宇宙被证明精确等于 lifecycle 的 20 日突破规则；我的 TDX 读取与冻结管线一致。

**B1 冻结 ref60 口径 68.27%**：18,725/27,422 满足 `复权 close > 前 60 个有效观测最大值`（严格 >）。8,697 不满足 = 8,585 margin≤0 + 112 因子不可得。margin_vs_ref60 分布：中位 +8.4%，均值 +28.4%（长尾：max +1956%），≤−5% 有 5,917 个、≤−10% 有 3,896 个。→ 分歧是**实质性的**，不是边缘噪声。

**B2 全域重构（lookback=60）**：同一冻结锚定机制、仅突破窗改 60：重构事件 16,495 个；与 27,422 的交集 9,185；old_only 18,237；new_only 7,310；同生命周期内 breakout_day 变化 18,237 处。

**分歧根源（代码考古）**：`lifecycle.py` L53 `breakout_lookback: int = 20  # 与 pullback high_lookback 同源，不另设阈值`。V1 冻结的 ref60（60 个有效观测、复权、严格 >）是**特征层的参考位定义**，与 lifecycle 生成事件宇宙的 20 日规则不是同一条规则；两者在"突破"语义上相差 40 个观测 + 复权 vs 未复权。

**提请裁定（三选一或另议，V2 不自行决定）**：
1. 事件宇宙维持 lifecycle 20 日规则，ref60 降级为 A1 特征（`a1_breakout_margin` 已存在，负值即"未过 60 日高"的诚实记录）；
2. 事件宇宙改用 ref60 重建（= B2 的 16,495，属重大口径变更，需新版本号）；
3. 双轨并行（lifecycle 事件 + ref60 子集标记），V3/V4 按裁定使用。

### 2.4 Gate C — PASS
- 方法论说明：`close×F / hfq_close` 为**每股常数**（如 000001=0.010021、600519=0.152278、300750=0.996591）——因子表 F 与库 hfq 的基准日归一不同，收益/比值层完全等价（这正是 Gate A 能逐位一致的原因）。因此 Gate C 检验**每股常数性**而非 |ratio−1|。
- 结果：4,760 事件股 / 6,255,000 行，close 与 high 两口径的每股内最大偏离 9.5e-11，0 只违例股 → 无单位跳变、无日期错位、F 对 OHLC 均匀适用。
- 事件日 TDX close vs 库 close：27,310/27,310 逐分一致（112 因子不可得事件不在此口径内，见 §2.5）。
- 附注：因所有标签/特征均为比值或同空间原始价，常数缩放不影响任何已交付字段。

### 2.5 Gate E — FAIL（V1 审计脚本自身缺陷，证据链完整）
**现象**：严格按 V1 冻结 §5（缺因子即无效、不默认 F=1）重算，17 项覆盖指标中 14 项与冻结审计表不一致，且全部指向同一个 112：

| 指标 | 冻结表 | 严格口径重算 | 差异 |
|---|---|---|---|
| T0 close 有效 / ref60 ready / vol20 ready | 27,422 (100%) | 27,310 (99.59%) | −112 |
| h5/h10 none | 27,422 | 27,310 | −112 |
| h20 none / sample_end | 27,289 / 133 | 27,177 / 133 | −112 / 0 |
| h40 none / sample_end | 26,237 / 1,185 | 26,126 / 1,185 | −111 / 0 |
| h20/h40 security_history_end | 0 | 112 / 111 | +112/+111 |
| chip vwap5/10/20 miss | 85/137/218 | 197/249/330 | +112 each |
| turn20 partial / missing days | 279 / 1,202 | 278 / 1,192 | −1 / −10 |

**根因（`scripts/t3_event_coverage_audit.py` L85–118）**：
1. L82–86 正确地把零/缺因子股收进 `bad_factor_codes`（因子行数≠库行数即入列）；
2. 但 L89–94 的 `fac_dates_bad` 是 `defaultdict(set)`，**只对在因子表里有行的股创建键**；
3. 21 只**零覆盖**股（因子表完全无行：000407、000753、000970、000981、002321、002523、002546、002759、300176、300278、600272、600313、600339、600477、600518、600603、601388、601686、601818、688711、689009）在因子表中无行 → 键永不创建 → `code_pfx in fac_dates_bad` 为 False → 走 else 分支 `valid = 全部库日期` → 被当成因子全覆盖；
4. 这 21 只股上的 112 个事件因此被审计为"T0 有效/ref60 可算/窗口完整"，冻结覆盖表随之高估。

**交叉验证**：任务二 identify 构建时 `load_stock` 的日期 = TDX∩库∩因子，这 112 个事件当年即被剔除（27,422−112=27,310）——两个独立管线互证 112 这个数。

**附带发现**：这 112 个事件在四态枚举中无干净归属——其库价格历史并未终止（有库行到 2026-09-18），终止的是因子可得性。我的实现将其记为 `security_history_end`（冻结枚举内唯一可落的位置）+ `terminal_reason="unknown"`，并在报告此处置疑该语义；若裁定剔除或新增第五态，属规格修订。

**提请裁定**：
1. 接受严格口径重述表（上表右列）为权威覆盖数字，V1 审计表标注作废条目（建议）；
2. 112 事件处置：从标签主样本剔除（与 identify 对齐）/ 保留现状（null 标签+四态错位披露）/ 新增删失态（需改冻结枚举）。

### 2.6 Gate D — PASS
抽样 283 事件（按排序位次每 97 个取 1，无随机）：对每个事件把单股数据**物理截断到 ≤T0**（全部字典逐项过滤），重算 A1/B1/chip 三层共 849 次，与全量数据下的结果**逐字段全等（0 不一致）**。周线聚合的未满周排除（T0 所在周不合成）在截断测试中天然覆盖——若实现有周内未来日泄漏，截断重算必然不等。

## 3. 开工令 §六 问题逐答

1. **事件数**：27,422（与冻结一致；Gate B2 的 ref60 重构 16,495 仅是裁定材料，未替换宇宙）。
2. **删失四态**（严格口径）：h5/h10：none 27,310；h20：none 27,177 / sample_end 133 / security_history_end 112(因子不可得，语义错位披露) / data_gap 0；h40：none 26,126 / sample_end 1,185 / security_history_end 111 / data_gap 0。primary_eligible_H 与 label_avail_H 仅审计记账，未进入任何特征。
3. **特征覆盖**（严格口径）：A1 ref60 27,310；B1 vol20 27,310；chip vwap5/10/20 可算 27,225(99.25%)/27,171(99.08%)/27,092(98.80%)；成本带 60/120 待裁定后冻结（覆盖率随裁定更新）。缺失一律保持缺失（不插补/不零填/不缩窗），所有滚动窗带真实观测数字段。
4. **PIT**：Gate D 截断重算 0 不一致；特征层无任何板块/行业字段；周线只用完成周。
5. **口径统一**：新产物统一 6 位零填充 code6；与 signal_panel 裸 int、identify `sz.` 前缀、lifecycle 6 位的映射在构建器断言；镜像表 md5 已入 integrity_report 的 inputs_sha256。
6. **奇异发现**：①Gate B 的 20d/60d 规则分歧（§2.3）；②Gate E 的审计 defaultdict 缺陷（§2.5）；③F 与 hfq 的每股常数关系（§2.4，等价性证明）；④sensitivity 文件中 h40 有值仅 22 个——因日历末端 2026-09-22 与数据末端 09-18 仅隔 2 个市场日，绝大多数 sample_end 事件的 T+40 落在日历之外，连"向前取最近可得日"都无位可取（22 与任务二 sens 精确互证）；⑤chip 的 vwap 用原始 amount/volume 与原始 close 同空间比较，窗口内除权会混合两种价格空间（冻结口径接受，窗口中位仅 20 日，除权落入比例极低，未做修正）。

## 4. 已发现的冻结定义问题清单（只报告，未自改）

| # | 问题 | 状态 |
|---|---|---|
| 1 | ref60（V1 §2.2）与 lifecycle 20 日突破规则不是同一条规则 | Gate B FAIL，提请裁定 |
| 2 | V1 审计脚本 `fac_dates_bad` defaultdict 缺陷 → 覆盖表高估 | Gate E FAIL，提请重述 |
| 3 | 112 因子不可得事件在四态枚举无干净归属 | 随裁定 2 一并处置 |
| 4 | V1 §3.2 "组合六态"字面为 2×3，实际矩阵 3×3=9 | 已实现为 9 态 `b1_day_state`（high/norm/low × up/down/flat），六态为其子集；请确认或修订字面 |
| 5 | chip 成本带（§3.4 冻结候选）实现口径：同一有效观测骨架 + 全窗 vpos；`chip_cost_zone_pos` = 窗口内逐日 vwap 分布对当前收盘的分位 | 待审计后冻结 |
| 6 | `margin_fin_*`/`sf_*`/行业超额/行业生命周期/ETF→行业映射 | 维持排除（与 V1 一致） |

## 5. 复算指令（确定性）

```
/root/venv/bin/python scripts/run_t3_v2.py            # 6 产物 + integrity（~400s）
/root/venv/bin/python scripts/t3_v2_gates.py          # Gate ID/A/C
/root/venv/bin/python scripts/t3_gate_b_ref60.py      # Gate B（复用变体 parquet；--force 全重算）
/root/venv/bin/python scripts/t3_determinism_check.py # 双跑 hash 比对
/root/venv/bin/python tests/test_t3_v2.py             # 单测 6/6
```
无随机数、无墙钟依赖；两次全量构建的 6 个 parquet 逐字节一致（sha256 见 `determinism_check.json`）。运行环境：/root/venv（pandas 3.0.3 / numpy 2.4.6 / pyarrow 25.0.1 / duckdb 1.5.5）。

## 6. 条件版结论（历史记录）

V2 条件版 `93afd5e` 的原始 Gate B/E FAIL 与待裁定结论保留在本报告前文，作为审计历史，不删除、不回写。

## 7. 用户裁定后重签结论

用户选择 Gate B 方案 1，并接受 Gate E 审计缺陷；规范勘误见 `T3_V1_ERRATA_AND_V2_REGATE.md` 与 V1 文档 Erratum E-2026-09-23。修订只改变规范职责和字段级审计语义，不重建 27,422 事件宇宙、不删除 112 事件。

| 重签 Gate | 结果 | 证据 |
|---|---|---|
| ID | **PASS** | 27,422 唯一；映射完整 |
| Y40 | **PASS** | 26,126 可比事件，max_abs_diff=0.0 |
| lifecycle20 universe | **PASS** | 55,646 rows/12 columns 全表 0 mismatch；27,422=27,422 |
| ref60 feature integrity | **PASS** | 27,310/27,310 与 A1 逐事件一致；obs_n=60；native20 27,422/27,422 |
| high×F | **PASS** | 最差每股常数偏离 9.476e-11；事件日 27,310/27,310 |
| PIT | **PASS** | 849 次物理截断重算，0 mismatch |
| corrected field coverage | **PASS** | 字段矩阵 62 行；Gate E diff={} |
| deterministic rerun | **PASS** | 6/6 产品 hash identical |

字段级关键覆盖：A1 ref60=27,310/27,422；B1 volume=27,422/27,422；chip VWAP 5/10/20 均为 27,422/27,422；h20/h40 security_history_end=0；112 事件归入 data_gap/adj_factor_missing（主因按 horizon 优先级可与 sample_end 并存）。

特别更正：条件版 Gate B 诊断脚本曾因复用首事件 prior 窗口错误报告 ref60 同时突破 18,725（68.27%）；产品 builder 未受影响。本次修正脚本逐事件取窗，正确保存值为 9,430/27,422。

**V2 状态：PASSED。按裁定边界，V3 尚未开工，等待新的明确开工令。**
