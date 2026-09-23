# T3_SUSTAIN_COVERAGE_AUDIT_V1 — 任务三 V1：多周期趋势持续性数据覆盖审计 + 标签规范冻结版

> 状态：**正式冻结版（path_label_v1 + t3_id_v1）。**
> 验收记录：用户条件验收（2026-09-23）——裁定 1（收益主口径）/2（60日最高收盘）/4（板块克制）
> 直接冻结；裁定 3（删失三态）**修改后冻结**（四态拆分 + label_avail 限审计用途）；
> 两个前置门禁（全事件集 chip 覆盖审计 / label_avail 反分层条款）已于冻结前补齐，
> 结果见 §0 与 `event_coverage_audit.json`。实现批次（T3 V2）按 §10 边界执行。
> 授权范围：仅覆盖/缺失/PIT 审计与规范冻结。本审计**未计算任何未来收益结果变量、
> 未训练模型、未运行回测**（与任务二阶段0 同一授权级别）。
> 审计脚本：`scripts/t3_coverage_audit.py` + `scripts/t3_event_coverage_audit.py`（均只读）；
> 审计数字：`output/research/t3_audit_v1/{coverage_audit,event_coverage_audit}.json`。
> 基线 HEAD：25379ed（任务二已结项，全部封存产物未动）。

---

## 0. 结论摘要（先读）

1. **A1 纯价格结构：原始层完全可用。** 冻结库 5,240 只 × 2021-01-04→2026-09-18
   （6,696,221 行），OHLC 零缺失、零非正值；复权因子缺 0.494%（24 只股，见 §5）。
   面板层（signal_panel）A1 类价格字段实测**零缺失**。
   **全事件集实测（27,422 突破）：ref60（前 60 个有效交易观测）100% 可算，
   连续 60 市场日变体亦 100%。**
2. **B1 量价/资金效率：原始层可用，量能缺失 0.12–0.15% 需显式规则。**
   volume/amount 缺 0.1225%，turn 缺 0.1455%，volume=0 行 0.147%——量比/换手类
   特征必须带"量能缺失日"处理条款，不允许静默当 0。
   **全事件集实测：T0 量/换手 100% 可算；前 20 观测量能基准 100% 可算；
   事件后 20 日换手全在率 98.50%（279 事件部分缺，共缺 1,202 换手日）。**
3. **板块层只有"价格动能"全域可用；"真实资金流入"证据只有两条窄通道**：
   ETF 份额（1,672 只，2024-01 起，PIT 100%）和行业融资余额（31 行业，
   2025-01 起）。语义区分表见 §4——**板块价格强 ≠ 板块资金流入**为永久红线，
   术语规范：ETF份额/融资余额=资金证据，申万价格=价格动能，
   静态membership=当前分类回溯标签（禁入PIT主研究解释），15只ETF→主题=descriptive theme tag。
4. **筹码/VWAP：全事件集真实覆盖率为 99.2–99.7%（非零缺失）。**
   滚动 VWAP 严格口径（含 T0 全窗 + vol>0）：vwap5 99.69%、vwap10 99.50%、
   vwap20 99.21%（85/137/218 事件缺）。首轮"三通道全可算"表述作废，
   以 `event_coverage_audit.json` 全集实测为准（e6 13,616 子集零缺失系该子集
   构造上自带完整性，不外推）。
5. **路径标签可标性实测（27,422 突破事件，四态分解）**：
   Y5/Y10 全量 `none`；Y20：none 27,289 + sample_end 133；
   Y40：none 26,237 + sample_end 1,185。**security_history_end 与 data_gap
   在本事件集均为 0，mean win coverage=1.000**——四态机制为正确性而设，
   当前数据只出现右边界删失；退市终态核实留 V2（§6.5）。
6. **ID 规范已冻结**：四种 code 书写约定并存（§7.1），新产物统一 6 位
   零填充字符串；breakout_event_id = `{code6}_{breakout_day}`，实测 27,422
   全唯一、零冲突。**事件去重/生命周期锚定逻辑不动**（§2.2 边界条款）。

---

## 1. 数据资产与版本锚（全部只读引用，不重跑）

| 层 | 资产 | 路径 | 规模 | 时间范围 | 状态 |
|---|---|---|---|---|---|
| 原始·个股 | 冻结库 per_stock | `data/adjustment_baostock/per_stock/*.json.gz` | 5,240 文件 / 6,696,221 行 | 2021-01-04→2026-09-18 | 任务二冻结输入 |
| 原始·复权 | 因子表 | `output/research/adjustment_v1/factor_table.csv.gz` | 6,663,146 行 / 5,216 只 | 同上 | 任务二冻结输入 |
| 原始·日历 | 上证日历 | `/root/tdx_data/.../sh999999.day` | 1,248 bars | 2021-08-02→2026-09-22 | 只读 |
| 特征·日 | signal_panel | `output/research/momentum_panel_v3(_parquet)/signal_panel` | 971,463 行 / 4,855 只 | 2024-01-02→2026-09-01 | momentum_panel_v3 契约（月池内股票-日） |
| 特征·周 | weekly_state | `output/research/lifecycle_v1/weekly_state_v1` | 971,463 行（与 signal_panel 对齐） | 2024-01-02→2026-09-01 | state_axes_stage1_v1（e2cf0918238fc95c） |
| 事件·生命周期 | lifecycle | `output/research/lifecycle_v1/lifecycle_stage4_v1_full` | 55,646 生命周期 / 27,422 首突 | 2024-01→2026-09 | 7f2c8dda08801d27 已验收 |
| 事件·三时点 | identify_* | `output/research/posneg_v1/identify_{breakout,shrink,stabilization}.csv.gz` | 27,310 / 21,515 / 13,597 | 同上 | 任务二冻结（48f8…三元组见封存稿） |
| 背景·板块/ETF/市场 | capobs facts | `/root/project/workspace/capital-observer/output/research_context/facts.csv` | 839,593 行 / 8 指标 | 主 2024-01→2026-09 | strict_pit 视图（manifest 自带口径） |
| 背景·行业映射 | membership | `.../research_context/membership_history.csv` | 5,216 行 / 31 申万一级 | 2021-12-13 快照+新股补录 | sw_l1_2021 |
| 筹码·VWAP | e6_vwap | `output/research/e6_vwap/events.csv` | 13,616 事件 | 2024+ | E5_E6 已封存（参考实现） |
| 收益引擎 | forward_y40_lib / retcalc_v1 | `scripts/forward_y40_lib.py` 等 | — | — | 复权口径与删失规则的**冻结先例** |
| 审计·库级 | coverage_audit | `output/research/t3_audit_v1/coverage_audit.json` | §1–§5 数字来源 | — | 本轮产出 |
| 审计·事件级（门禁一） | event_coverage_audit | `output/research/t3_audit_v1/event_coverage_audit.json` | 27,422 全事件 | — | 本轮产出 |

审计实测细节全部在 `output/research/t3_audit_v1/coverage_audit.json`，本文引用其数字。

---

## 2. A1 纯价格结构字段表（层 1：只含价格，不含量能）

### 2.1 原始层输入（冻结库，2021-01→2026-09，全 5,240 只）

| 字段 | 来源 | 实测缺失 | 实测非正/零 | 可用性 |
|---|---|---|---|---|
| open/high/low/close | per_stock unadj | **0 / 0 / 0 / 0** | 0 | ✅ 全域 |
| 复权价 P(t) | close × F（factor_table） | 库行无因子 33,075 = **0.494%** | — | ✅（缺失跳过，见 §5） |
| hfq 后复权序列 | per_stock hfq | 行数与 unadj 逐股一致（0 错配） | — | ✅（仅作交叉校验，不作主口径） |

注：pctChg"非正 52%"为**正常市场涨跌分布**，不是数据缺陷；A1 不使用该字段（用复权价自算）。

### 2.2 派生字段（A1 定义冻结候选——全部只用价格）

| 字段名（建议） | 定义（开发级） | 回看窗 | 最长回看 | 有效起始（原始层） |
|---|---|---|---|---|
| wk_up_streak | 周线（周一~周五收盘合成周收盘，未满周不合成）连续上涨周数；周收益 close-to-close | — | 全历史 | 2021-01 + 2周 |
| wk_hl_struct | 周线高低点结构：本周高 > 上周高 且 本周低 > 上周低 记 HH_HL，余类推四态 | 2周 | 2周 | 2021-01 + 2周 |
| dist_prior_high | close / 窗口内前高 − 1（复权口径） | 60d（主）/ 120d（辅） | 120d | 2021-07 起 |
| wk_slope | 近 N 周对周收盘 OLS 斜率 / 均值（归一化） | 8周 | 8周 | 2021-03 起 |
| wk_cum_ret | 近 N 周累计对数收益 | 4/8/12周 | 12周 | 2021-04 起 |
| vol_contraction | 日真实波幅（TR）20 日均值 / 60 日均值 | 60d | 60d | 2021-04 起 |
| **breakout（冻结定义）** | `ref60_T0 = max(close[T-60 ... T-1])`（**前 60 个有效交易观测**，复权收盘；T0 不进入参考窗口；不 forward-fill）；`breakout ⇔ close_T0 > ref60_T0`（**严格 >**，非 ≥）；`breakout_day = T0` | 60d | 60d | 全事件集 100% 可算（§0.1） |
| dist_ma20 / dist_ma60 | close / MA20−1、close / MA60−1（复权） | 20/60d | 60d | 2021-04 起 |

**breakout 定义边界条款（裁定 2 附带，冻结）：**
- 参考位定义与**事件去重/生命周期锚定是两个问题**——本条只冻结参考位口径；
  lifecycle_v1 既有"每生命周期首突 ≤1"的去重/锚定规则**原样沿用，不修改**；
- 若 V2 实现按新冻结口径复算后事件数偏离 27,422，**必须输出 old/new event
  diff 清单**（新增/消失事件的 code+日期逐条列出），不得静默变化；
- "有效交易观测"= 该股当日有行情行且复权因子存在（§5 规则：缺因子即无效，
  不默认 F=1）。

**面板层现状**（signal_panel，2024-01→2026-09，月池内 971,463 行）：上表同族字段
`pre_return_{5,10,20,60}_pct / dist_to_prior_ma{5,10,20,60}_pct /
dist_to_prior_high{5,10,20,60}_pct / prior_up_streak / atr14_prev` 实测**零缺失**，
但范围=月池内股票-日，且 code 用裸 int（§7.1）。**A1 若要覆盖 2021-2023 与全市场，
必须从原始层新算，不重用面板层**——这是 A1 独立成层的理由之一。

### 2.3 A1 语义红线

- A1 层**禁止混入任何量能/换手/成交额字段**（B1 边界，见 §3）。
- A1 全部字段 PIT 语义 = **T 日 15:30**（收盘即知）；任何字段不得使用 T 日以后数据。
- 同族字段已在 identify_* 存在（bo_dist_high60/bo_ma_bias20/bo_cum5/10/20/bo_hlpos60 等，
  27,310 行，缺失 0.49%＝因子缺失日）——任务三若复用须按 §7 ID 规范对齐，不重算。

---

## 3. B1 量价/资金效率字段表（层 2：A1 + 量能）

### 3.1 原始层输入与缺失（全库实测）

| 字段 | 来源 | 缺失 | 零值/非正 | 处置规则（冻结候选） |
|---|---|---|---|---|
| volume | per_stock | 8,201（0.1225%） | 1,637（0.0244%）+ volume=0 行 9,838（0.147%） | 缺失/零 → 该日**量能类特征=缺失**，不插补、不当 0 |
| amount | per_stock | 8,201（0.1225%） | 同上 | 同上 |
| turn（换手率%） | per_stock | 9,745（0.1455%） | 93（0.0014%） | 同上；turn 缺失但 volume 在 → 量比可算、换手类缺失 |

**结构性缺失（非数据缺陷，必须写进特征定义而非"缺失率"）**：
signal_panel 周比较族字段缺失＝周一无同进度可比（t_eff/l_eff/eff_delta/
volume_ratio_vs_prev_week 38.8%）、首周无前周（60.0% 族）、sv_continuation/rebound
仅特定状态定义（85.1%）、tuesday_recovery_ratio 仅周二（92.4%）。这些是**定义性空洞**，
B1 沿用 weekly_state 的 evidence_completeness 标注（partial_week/carry_previous_week/
full_week_confirm/intraday_veto 四态），不得当成数据缺失合并统计。

### 3.2 B1 派生字段（定义冻结候选）

| 字段族 | 定义要点 | 回看 |
|---|---|---|
| 量比 | 当日 volume / 前 20 日均 volume（不含当日） | 20d |
| 放量/缩量 × 涨/跌/滞涨 | 量比 ≥1.5 / ≤0.8 × 当日复权收益正/负/|r|<0.5% 的组合六态 | 1d+20d |
| 缩量上涨延续 | 连续放量上涨后，量比 <0.8 且收涨的天数序列 | 事件内 |
| 回调量能衰减 | 回调段（见 §6 路径标签）日均量 / 突破前 20 日均量 | 事件内 |
| 再攻量能恢复 | 再攻段首 3 日均量 / 回调段均量 | 事件内 |
| 换手强度 | turn 20 日均值、事件内累计换手 | 20d/事件内 |
| 量价背离指数 | 事件内价格新高日量比 − 前高日量比 | 事件内 |

### 3.3 B1 核心研究问题（写入文档、指导后续对照）

> 价格趋势本身（A1）已解释的之外，量能/资金效率（B1）**增加**了什么信息？
> 消费方式：同一样本上 A1-only vs A1+B1 的对照（任务三第二/三阶段），不提前承诺结论。

### 3.4 筹码/VWAP 字段表（chip_*，独立成层；覆盖=门禁一全事件集实测）

**量纲冻结**：chip 层全部使用冻结库（baostock）amount/volume，**元/股**，
`vwap_day = amount / volume`，**不除 100**（e6 旧实现的 /100 是 TDX 手单位换算，
仅属该历史实验，不带入 chip 层）。窗口语义镜像 e6：滚动 VWAP = **含 T0** 的最近
w 个有效交易观测，**严格全窗在 + 窗内总量 >0**，任一日量缺失/为零 → 字段缺失。

| 字段 | 定义 | 全事件集实测覆盖（27,422） |
|---|---|---|
| vwap_day | amount/volume（当日成交均价代理） | T0 量能 100% 可算 |
| price_to_vwap_5d | close_T0 / (Σamount[−4..T0]/Σvolume[−4..T0]) − 1 | **99.69%**（缺 85） |
| price_to_vwap_10d | 同上，窗口 10 | **99.50%**（缺 137） |
| price_to_vwap_20d | 同上，窗口 20 | **99.21%**（缺 218） |
| turn_cum_20 | 事件后 20 市场日累计换手（缺换手日跳过并计 turn_miss_days） | 全在率 **98.50%**（279 事件部分缺，共 1,202 缺日） |
| cost_zone_pos（V2 冻结候选） | 当前价相对近 60/120 日 amount 加权均价带（成本密集区代理）的分位 | V2 实现时按本表口径审计后冻结 |

**chip 层规则**：缺失即缺失（不插补、不用零量凑窗口）；每字段覆盖数必须进 V2
完整性报告；成交密集区/成本分布等更重构造不在 chip_v1，留后续版本按同一审计流程扩展。

---

## 4. 板块/ETF/市场背景字段覆盖表（层 3：只做覆盖，不进模型）

### 4.1 语义区分表（**板块价格强 ≠ 板块资金流入——永久红线**；术语按验收裁定规范）

| 字段族 | 规范术语 | 来源 | 覆盖 | PIT | 语义 |
|---|---|---|---|---|---|
| etf_total_shares（1,672 只） | **资金证据** | capobs facts | 2024-01-02→2026-09-15；p50 每只 655/661 日，min=2 | **22:00，100% 盖章** | 真实申赎资金（份额变化=净申赎） |
| etf_new_exposure（份额×NAV） | **资金证据** | research_context | 仅 15 只配对 ETF | 22:00 | 真实净暴露增量（官方口径，非二级买入） |
| margin_balance/margin_buy（31 行业） | **资金证据（仅 2025+）** | capobs facts | **仅 2025-01-02→2026-09-15** | 已盖章 | 杠杆资金 |
| sw_close / sw_amount（31 申万一级） | **价格动能** | capobs facts | 2024-01-02→2026-09-09（DB 另有 2023-08 起） | 15:30 | 非资金流入 |
| index_close / index_volume（6 指数） | **价格动能** | capobs facts | 2024-01-02→2026-09-09 | 15:30 | 非资金流入 |
| etf_close/volume/amount（15 只配对） | **价格动能** | capobs facts | 2024-01-02→2026-09-09 | 15:30 | 非资金流入 |
| margin_fin_*（交易所汇总，2018 起） | ❌ 不用 | capobs DB | 2018-06→2026-09 | **available_at=NULL** | strict PIT 不可用，不入主特征（用户裁定维持） |
| sf_* 大小单净流（496 只票） | ❌ 不用 | capobs DB/facts | 2026-03 起（facts 内仅 2026-09-16 一日过 PIT） | 部分 | ❌ 历史太短，**不入任务三** |
| membership 行业归属 | **当前分类回溯标签** | membership_history | 2021-12-13 快照+新股补录 | 快照 | 非时变，见 §4.2 禁令 |
| 15 只 ETF→主题 | **descriptive theme tag** | 约定式标签 | — | — | 仅描述性，见 §4.3 |
| 板块突破比例/上涨股比例/板块换手 | 结构强度（价格侧派生） | **派生**：per_stock × membership 聚合 | 2021-01 起（membership 2021-12-13 起） | 15:30 | 派生字段（§4.2 限定随之） |

### 4.2 行业映射的 PIT 限定（含验收禁令，冻结）

membership_history = **2021-12-13 静态快照 + 新股上市日补录**（5,216 行全部开区间，
31 行业，每股 20~540 只，p50=122 只/行业）。因此：
- "个股→申万行业"字段语义 = **当前分类的历史回溯标签**，不是历史时点分类；
- 2021-12-13 前的行业归属不存在；行业迁徙（如股票调类）不可见；
- **禁令（验收裁定，冻结）**：静态 membership 只可用于描述性分组与背景解释聚合；
  **禁止**进入"当时市场知道该股票属于某行业"的 PIT 主研究解释——否则数年后的
  成分调整会形成 retrospective classification；
- 行业级序列本身（sw 价格、行业 margin）不受此限，但个股↔行业连接经 membership，
  连接语义随本条；
- 此限定沿用任务二以来"行业/板块聚类只作背景与风险解释"的总规则。

### 4.3 ETF→行业映射现状（如实披露，不硬造）

- **不存在** ETF→申万行业的直接映射表；fund_industry_weight 是 55~56 只**主动公募**
  × 中信行业 × 半年度（2025-03→2026-06），与个股-申万体系不同轴，仅作参考层；
- 唯一可用结构 = 15 只配对 ETF 的**约定式主题标签**（510300 宽基 / 512480 半导体 /
  512690 酒 / 512800 银行 / 515790 光伏 / 512010 医药 / 159928 消费 / 515030 新能源车
  等）。任务三阶段一**只登记标签，不构造"行业=ETF"等式**；
- 板块生命周期（任务四）落地时再决定：行业轴（申万聚合）为主、ETF 份额为资金证据旁证。

---

## 5. Point-in-Time 可用性审计（汇总表）

| 数据 | available_at 规则 | 实测 | 结论 |
|---|---|---|---|
| 个股 EOD 价格/量/额/换手 | T 日 15:30（收盘即知语义） | 库 fetched_at=2026-09-19 批量，历史研究按语义使用（既有裁定） | ✅ |
| 复权因子 F | 跟随行情日（除权日当日可知） | 库行缺因子 0.494%（24 只股：sz.000970/sh.600313/sz.000981 等近全历史缺失）；**缺因子日跳过、不默认 F=1**（任务二规则沿用） | ✅ 带规则 |
| ETF 份额/NAV | T 日 22:00 | facts 内 100% 盖章 | ✅ |
| 申万/指数/ETF 行情 | T 日 15:30 | 100% 盖章 | ✅ |
| 行业融资余额 | 已盖章（2025-01 起） | 100% | ✅（短） |
| margin_fin_*（2018 起） | NULL | 0% 盖章 | ❌ 不用 |
| sf_* 资金流 | 部分 | facts 内仅 1 日 | ❌ 不用 |
| membership 行业 | 快照（非时变） | 2021-12-13 | ⚠️ 限定语义（§4.2） |
| 未来数据总闸 | 未来信息只准进**结果标签**（§6），不准进任何实时特征 | — | 沿用七阶段硬约束 |

**与任务二口径差异披露**：任务二 RISKSET_V2 记因子缺失 28,944 行=0.432%（按
identify 消费路径的日期键交集）；本审计按"库全行 vs 因子表全键"=33,075 行=0.494%
（含 24 只无因子股的全部行）。两者定义不同、都对；冻结稿以本审计口径为准并注明。

---

## 6. 5/10/20/40 日路径标签定义（冻结候选稿 path_label_v1）

主体 = **突破事件**（breakout_event_id，§7）。窗口 = 上证日历 T0 起含 T0 共 H+1 个
市场日（与任务二 forward_y40 完全一致）；T0 = breakout_day；基准价 p0 = T0 复权收盘。
复权 = unadj close × F（因子缺失跳过，不默认 1）。全部指标先算**绝对口径**，
相对口径（vs 行业指数）为旁注列（行业轴 2024-01 起、快照语义）。

### 6.1 收益族（裁定 1 冻结版；实现细节全部继承任务二，不在 T3 重新定义）

**继承条款（冻结）**：价格复权方式（unadj close × F，缺因子跳过不默认 1）、
市场基准（sh999999 上证收盘，int32/100 口径）、交易日对齐（上证日历 T0 起含 T0
共 H+1 市场日）——**逐项继承 `forward_y40_lib.py` 冻结实现，T3 不重新定义**。

| 字段（冻结名） | 定义 |
|---|---|
| y5/y10/y20/y40_mkt_excess_log | log(P(T+H)/p0) − log(指数(T+H)/指数(T0))，**主口径=市场超额对数收益**（任务二 y40 完全同式，全套 H） |
| y5/y10/y20/y40_raw_log | log(P(T+H)/p0) 绝对对数收益，**全套保留**（不只 y40） |
| win_coverage_H | 窗口内实际有复权价的市场日数 /（H+1），<1 时必读 §6.5 删失列 |

**明确排除（裁定 1）**：本版**不做行业超额收益**——行业 membership 非 PIT、
ETF→行业映射不存在（§4），硬做会把干净研究搞脏。待任务四板块生命周期建立后，
再增加 `sector_relative_return` 作为第二套**背景**指标（背景语义，非主口径）。

### 6.2 风险与恢复族（窗口内、复权价、含盘中高低点两口径）

| 字段 | 定义 |
|---|---|
| mdd_close_H | 窗口内复权**收盘**序列 max drawdown（任务二已有实现，沿用） |
| mdd_intraday_H | 窗口内复权**low**相对截至前日复权 high 的最大回撤（更严口径，新加） |
| dd_peak_day_H | MDDclose 发生峰值日 offset；dd_trough_day_H 谷值日 offset |
| recover_days_H | 峰值日后复权收盘重新 ≥ 峰值的最少交易日数；窗口内未收复 = NULL + recovered_H=false |
| time_to_new_high_H | T0 后首次创 **T0 前历史最高收盘**（复权，截至 T0 全历史）的 offset；未创 = NULL |

### 6.3 趋势持续族

| 字段 | 定义 |
|---|---|
| n_new_high_H | 窗口内创"T0 前历史最高收盘"新高的**天数**（连续只按收盘价上台阶计一次亦可，冻结为逐日计、另附 n_new_high_runs） |
| trend_alive_days_H | 自 T0 起收盘 ≥ MA20（窗口内滚动，复权）连续保持天数；断即止 |
| above_ma20_last_H | T+H 当日收盘是否 ≥ 窗口内 MA20（布尔） |
| path_efficiency_H | (P(T+H)/p0) 的绝对值 / 窗口内累计日对数收益绝对值之和（趋势效率） |

### 6.4 回调与量能族（B1 消费）

| 字段 | 定义 |
|---|---|
| pullback_depth_H | 窗口内自任意前高 ≥5% 的最大回撤深度（<5% 记 0，"基本不回头"） |
| pullback_len_H | 该回调段交易日数；pullback_vol_ratio_H = 回调段日均量/突破前 20 日均量 |
| vol_ratio_mean_H / vol_ratio_last_H | 窗口内逐日量比（/前 20 日均量）的均值 / 末 5 日均值 |
| turn_cum_H | 窗口内累计换手（turn 缺失日跳过并记 turn_miss_days_H） |
| vol_miss_days_H | 窗口内量能缺失/零天数（§3.1 规则的显式落列） |

### 6.5 删失与可得性（裁定 3 修改后冻结版——四态 + label_avail 仅审计）

**删失四态（冻结）**——delist 与 gap 经济含义不同（退市=可能与个股表现相关的
终局事件；缺口=观测问题），合并会产生 survivorship bias，故拆开：

| censored_reason_H | 定义 |
|---|---|
| `none` | 窗口 [T0, T0+H] 全部市场日均有有效复权价 |
| `sample_end` | T0+H 越过样本末端（全局数据末日 2026-09-18 或日历末）——纯右边界删失，与个股无关 |
| `security_history_end` | 个股有效历史在窗口内终止（末有效日 < T0+H）——经济终局候选；附 `terminal_reason`（delist/…，V2 用外部退市名单核实后填；核实前=unknown） |
| `data_gap` | 个股历史延续到窗口后，但窗口内有缺口（停牌/数据缺）——观测问题 |

**主分析样本规则（冻结，防未来信息）**：固定 H 的 primary 样本 =
`breakout_day ≤ dataset_end − H 个交易日`（dataset_end=全局数据末日）。
该规则在观察时点 t 可判定、不含个股未来信息，右边界删失天然排除。
**禁令（冻结）**：`label_avail_H` / `censored_reason_H` 一律只作
数据审计 / attrition table / censor bookkeeping——**不得作为模型特征、
不得作为风险集分层变量**（按"未来最终有没有标签"分层 = 提前使用未来时间位置；
2026-08 突破无 Y40 而 2025 年都有，分层即泄漏）。后续若要利用删失事件，
上 survival/hazard 框架，不做简单标签分组。动态风险集（T3 V4）一律
"在观察时点 t，只用截至 t 已知信息构建 risk set"。

**实测（全事件集，`event_coverage_audit.json`）**：Y5/Y10：none=27,422 全量；
Y20：none 27,289 + sample_end 133；Y40：none 26,237 + sample_end 1,185。
**security_history_end=0、data_gap=0、mean win coverage=1.000**——四态机制
为正确性而设，当前数据只出现右边界删失（2024 起的生命周期事件集内无个股
中途死亡；2021-2023 原始层扩展时须重跑本审计确认）。

**敏感性口径（冻结）**：T+H 无价时向前取最近可得日（imputed_last_available）
**只进敏感性文件，不进主标签**（任务二先例）；主样本与敏感性样本物理分开
（两个文件），主样本 = win_coverage=100% 且非 imputed 且 censored_reason=none。

### 6.6 明确不做（本版冻结即排除）

- 不做路径分类标签（直接延续/浅回调创新高/深回调恢复/突破失败/高位衰减五分类）
  ——那是任务六的输出，且必须在本标签表之上派生，**不提前固化为标签**；
- 不做任何"成功/失败"二元标签；
- 相对 ETF 超额（15 只主题 ETF）不进主表（映射未冻结，§4.3）；
- 不引入 sf_*、margin_fin_*。

---

## 7. 突破事件与生命周期唯一 ID 规范（冻结候选稿 t3_id_v1）

### 7.1 code 统一规范（现状四种并存 → 新产物唯一规范）

| 约定 | 出现处 | 处置 |
|---|---|---|
| 裸 int（1） | signal_panel / membership | 存量表不动；读取时 zfill(6) |
| `sz.000001` 带交易所前缀 | identify_* / per_stock 文件名 / retcalc | 存量表不动；读取时去前缀 |
| `000001` 6 位零填充字符串 | lifecycle / weekly_state | **= 新产物唯一规范** |
| 6 位含交易所可推导 | 前缀→交易所映射唯一（sh/sz/bj） | 保留推导函数：code6→前缀（sh 6xxxxx / sz 0/3xxxxx / bj 4/8xxxxx 以存量文件名为准建映射表，不用规则猜） |

**冻结条款**：任务三全部新产物 code 一律 6 位零填充十进制字符串；与存量表连接时
显式做一次映射并在 manifest 记录映射表 md5；映射歧义（前缀冲突）= 构建失败，不静默。

### 7.2 事件与生命周期 ID（全部对齐 lifecycle_v1 已有事实）

| ID | 格式 | 实测（本次审计） |
|---|---|---|
| lifecycle_id | 16 位 hex（lifecycle.py 生成，不动） | 55,646 唯一，0 重复 |
| pullback_event_id | `{code6}_{YYYY-MM-DD}`（已有） | 沿用，不动 |
| **breakout_event_id（新）** | `{code6}_{breakout_day}`（每生命周期首突 ≤1，lifecycle.breakout_day） | 27,422 唯一、0 冲突、0 坏 code |
| path_label 主键 | breakout_event_id（一事件一行，H 分列，§6） | 新表 |
| 阶段内演化表主键（阶段二用） | `{breakout_event_id}@{offset}`，offset∈{0,1,5,10,20,40} | 新表（本版只登记格式） |

**边界条款**：breakout_event 仅取 lifecycle 内**首个** breakout_day（已由 lifecycle 契约
保证每生命周期 ≤1）；"同一行情一个事件不重复计数"沿用七阶段硬约束；生命周期重开产生
新 lifecycle_id → 新 breakout_event_id，不合并。

---

## 8. 缺口与风险清单（如实；含门禁一实测更新）

1. **Y40 右删失 4.3%**（1,185/27,422，全为 sample_end）集中在 2026-07 后突破——
   主分析按 §6.5 primary 规则（breakout_day ≤ dataset_end − H）处理；
   **禁止**拿"有标签"当入选条件或分层变量做隐式筛选（任务二教训 + 裁定 3 禁令）。
2. **因子缺失 24 只股近全历史无复权价**——这些股的事件在 A1/B1/标签层全部自然缺席；
   不补、不估、进覆盖披露。（本事件集实测：27,422 个 T0 全部有有效复权价，无一缺失。）
3. **行业轴短**（sw 2024-01 起、行业 margin 2025-01 起）+ 行业超额本版不做（§6.1）：
   2021-2023 原始层扩展研究只有绝对 + 市场超额两口径。
4. **membership 静态快照**（§4.2 禁令）：行业聚合字段全部带"快照回溯"语义标记，
   禁入 PIT 主研究解释。
5. **量能缺失 0.12–0.15% + 量零 0.15%（库级）**：所有量比/换手特征带显式缺失传播，
   vol_miss_days_H 落列；**事件级实测**（门禁一）：chip vwap 严格口径缺 0.31–0.79%、
   事件后 20 日换手全在率 98.50%——真实覆盖率已登记，V2 完整性报告须逐字段对账。
6. **四态删失当前只见 sample_end**（§6.5 实测）——机制保留；2021-2023 扩展或
   换数据源时必须重跑事件级审计，防"本数据集无退市"被误外推为"机制不需要"。
7. **本审计未验证**：盘中高低点复权口径的一致性（mdd_intraday 需在实现时对
   high×F 抽样对账 hfq high）；**V2 实现批次第一道门禁**。
8. **退市终态核实**（terminal_reason=delist）本版=unknown，V2 需接外部退市名单
   （当前事件集 security_history_end=0，此项不阻塞）。

---

## 9. 验收记录（2026-09-23 用户条件验收 → 两门禁补齐 → 正式冻结）

| 裁定项 | 结论 | 落实 |
|---|---|---|
| 1 收益主口径 | **通过** | §6.1：y{5,10,20,40}_mkt_excess_log 主口径 + y{H}_raw_log **全套**；实现继承任务二；行业超额不做，留任务四 sector_relative_return |
| 2 60 日最高收盘 | **通过** | §2.2 冻结：ref60_T0=max(close[T-60…T-1])，T0 不入窗、严格 >、不 ffill、前 60 个有效观测；事件去重不动；事件数变化须 old/new diff |
| 3 删失 | **修改后通过** | §6.5 四态（none/sample_end/security_history_end/data_gap）+ terminal_reason；primary=breakout_day≤dataset_end−H；label_avail 仅审计，禁特征禁分层 |
| 4 板块克制 | **通过** | §4 术语规范（资金证据/价格动能/当前分类回溯标签/descriptive theme tag）+ §4.2 静态 membership PIT 禁令；板块生命周期留任务四 |
| 门禁一 | **已补** | `event_coverage_audit.json`：27,422 全事件集 chip/A1/B1/标签覆盖实测（§0/§3.4/§6.5） |
| 门禁二 | **已补** | §6.5 primary 规则 + 禁令条款 + §8.1 措辞修正（原"按 label_avail 分层"作废） |

其余首轮 §9 各项（量能缺失处置、mdd_intraday、新高定义、code 统一、breakout_event_id、
派生板块字段不进模型、盘中口径对账放 V2 门禁）随本轮一并冻结，无异议记录。

**本文件自此刻起为 `path_label_v1` + `t3_id_v1` 冻结版。**

---

## Erratum E-2026-09-23：lifecycle 事件定义、字段级覆盖与审计字段

本节是对冻结文本的规范性勘误；不回写或重建历史事件结果。旧文本保留，以下新语义优先。

### E1. 事件宇宙与 ref60 的职责

- `lifecycle breakout event` 正式定义为既有 lifecycle 规则：**TDX 未复权 close 突破前 20 个 TDX close 的最高值**。
- 事件宇宙保持 27,422，不改成 ref60 重构宇宙。
- `ref60` 是 T0 的 A1 趋势强度/位置特征：前 60 个有效复权观测的最高收盘；不是事件成立条件。
- `a1_ref60_close_margin` 为正式字段名：`adj_close(T0)/ref60 - 1`。旧字段 `a1_breakout_margin` 保留为 deprecated compatibility alias，数值相同。
- lifecycle20 reproduction 是门禁；ref60-universe reconstruction 仅为 descriptive diagnostic，不再是 Gate。

### E2. 112 个因子不可得事件

112 个事件保留在 27,422 事件宇宙中。事件存在、复权特征可用性、未来标签可用性是三个不同概念。

- 个股价格/成交行仍存在但复权因子不可用时，主删失原因为 `data_gap`，`data_gap_reason=adj_factor_missing`；不得记为 `security_history_end`。
- `security_history_end` 仅用于个股价格历史在窗口前真实终止的情形；退市/证券终态仍需外部名单确认。
- 依赖 F/hfq 的字段保持 missing；不依赖因子的原始量、换手、原始价格字段按字段级规则继续计算。
- `adj_factor_available`、`data_gap_reason_H` 及三类 flag 均为 audit-only，不得进入模型或风险集分层。

### E3. 字段级覆盖与删失 flag

覆盖必须按字段报告，不得把整个 A1/B1 family 粗暴降级。正式矩阵为 `field_coverage_matrix.csv`，含 `field / n_valid / n_missing / coverage_pct / missing_reason_counts`。

四态 `censored_reason_H` 仍保留单一主原因，优先级为 `sample_end > none > security_history_end > data_gap`；同时保存互不排斥的：
`is_sample_end_H`、`is_security_history_end_H`、`is_data_gap_H`。
因此右边界与因子缺失可同时出现：主因可为 `sample_end`，同时 `is_data_gap_H=true`。

修订后的冻结数字：A1 ref60 可用 27,310/27,422；B1 `vol_ratio_20` 可用 27,422/27,422；chip VWAP 5/10/20 可用均为 27,422/27,422；T0 后 20 个市场日换手审计为 partial=279、missing_days=1,202；所有 112 事件不再计入 security_history_end。

### E4. B1 九态与 chip 成本带

原文“六态”为字面计数错误。按现有实现冻结为 3×3 九态：
`high_up, high_down, high_flat, norm_up, norm_down, norm_flat, low_up, low_down, low_flat`；只修正文档数量描述，不改变 state machine。

chip V2 只冻结连续、可复算原始量：rolling VWAP、price-to-VWAP distance、累计换手、成交成本代理、有效观测数。`chip_cost_zone_pos_{60,120}` 保留为 audit-only candidate，不升格为 V2 primary feature；离散成本带阈值留待 V3 预注册。

---

## 10. 冻结后的任务三边界（验收裁定原文固化）

不做大模型工程，分四段推进，每段独立验收：

- **T3 V2（下一步）：事件级特征层 + 路径结果层的实现与完整性验证。**
  实际生成 breakout_event_id、A1_*、B1_*、chip_*、yH_*、censor_*，完成：
  事件数（27,422 对账 + ref60 复算 diff）、缺失率、PIT、唯一性、边界日期、
  **任务二收益复算一致性检查**（同事件 y40 与 forward_y40_lib 冻结值对账）。
  仍不训练任何预测模型。实现顺序：ID/映射层 → 标签表 → 特征层 → 完整性报告，
  一提交一层语义。
- **T3 V3：事件内演化研究。** T0→T5→T10→T20→T40 期间价格、量能、换手、
  成本位置、回调状态如何变化（状态变化研究，非预测）。
- **T3 V4：动态风险集比较。** 在观察时点 t 只用截至 t 已知信息构建 risk set，
  回答"同样存活到第 5/10/20 天的趋势，为何有些延续、有些回调、有些衰减"。
  label_avail/censored 类字段全程仅审计（§6.5 禁令）。
- 正负路径五分类、入场方式重评：仍在任务六/交易策略阶段，本任务三不碰。
