# IS-0 — 现有数据实物盘点与周频可匹配性（Phase 1）

- 生成：2026-10-29（Phase 1 执行日）
- 模式：只读盘点 + 小样验证；不改任何生产数据与冻结合同
- 伴生产物：
  - `scripts/cfis/is0_weekly_sample.py` — 周频样表构建器（可复现）
  - `data/cfis/weekly_sample_202401_202412.csv` — 2024 全年 52 周样表
  - `docs/research/cfis/is0_field_inventory.json` — 机器可读字段盘点表

## 1. 结论先行

1. **周频共同工作频率可行**。2022-01 起四层（L1 支持 / M 杠杆 / L4 情绪 / L3 市场承接）在同
   一张 ISO 周表上全部对齐；2024 全年 52 周样表无一周出现"某层零观测"。
2. **无需新建任何采集**。四层的日频原料已经存在且带 PIT 时间戳（`available_at ≥ date` 全量校验
   通过，0 违例）。
3. **共同稠密覆盖窗口 = 2022-01 → 今**（受 L3 市场轴起点约束）；更长历史（L1 自 2012、M 自
   2018）可作为"仅 L1/M 两层"的低频背景使用。
4. 小样已捕捉关键行情结构：2024-02 救市周（L1 STABILIZATION_ACTIVE × M 加速去杠杆 × L4
   PANIC→EUPHORIA）与 2024-W39/40 政策脉冲周（L1 +4.25% 家族中位扩张 × 两融单周 +458 亿 ×
   breadth 0.998 × 新 episode 1523）——四层同向/分化的研究对象在现有数据上直接可读。

## 2. 各层数据盘点

> 详细机器可读版见 `is0_field_inventory.json`。此处只列与周频匹配相关的要点。

### L1 政策稳定行为代理（宽基 ETF 份额）

- 主用源：`data/cf/derived/atoms/l1_history.jsonl`（日频原子，2012-01-04 → 2026-10-27，3595
  行，同日重复 0）。字段含 `state`（INSUFFICIENT_SUPPORT 296 / NORMAL 1309 / WATCH 979 /
  STABILIZATION_READY 338 / NORMALIZING 392 / STABILIZATION_ACTIVE 281）、
  `family_median_delta`（各族份额日环比变化率的**中位数，无量纲比例**）、`families_observed`
  （<3 判 INSUFFICIENT）、`available_at`（= `{date}+1 conservative`，T 日记录保守 T+1 可用）。
- 家族定义（冻结）：`docs/cf/cf1a_probes/l1_broad_etf_universe_v1.json` — 7 族 / 20 个
  name_pattern（CSI300/SSE50/CSI500/CSI1000/STAR50/CHINEXT/CSI_A500）；成员按日动态重建
  （简称匹配且不含 50 个排除词），自然 PIT；生成代码 `src/stock_selector/cf/atoms.py replay_l1`。
- 原始明细：`data/cf/raw/sse_etf_scale/`（日 CSV，2012-01-04 → 2026-10-15，3587 有效日 + 272
  个 0 字节 EMPTY，单位**份**）与 `data/cf/raw/szse_etf_scale/`（区间 CSV，2016-12-01 →
  2026-10-15，2395 唯一交易日**无缝**、无 (日期,代码) 重复，单位**份**）。→ **两市合并家族
  覆盖自 2016-12 起**；2012–2016 沪市单市。csr8 的 etf_shares（万份、仅沪市、停在
  2026-09-18）为冗余源，不用。
- 周频建议：`state`（周内最后有效值）+ `family_median_delta` 周均；键=ISO 周。

### M 杠杆场（两融）

- 主用源：`data/cf/derived/atoms/m_history.jsonl`（日频，2018-01-02 → 2026-10-27，2137 行）。
  字段：`state`（NEUTRAL/DELEVERAGING/DELEVERAGING_ACCELERATING/LEVERAGE_BUILDING/…）、
  `financing_balance_pressure`、`financing_flow`（日融资净流，元）。
- 原始：SSE `summary_*.csv`（2129 唯一日，单位**元**）+ SZSE 日 CSV（同样 2129 日，与沪市
  日期集**对称差=0**，单位**亿元**，`atoms.py` 生成 M 原子时显式 ×1e8）。两所单位不同，
  **必须经 m_history 归一后再用**；两市非空日集可直接当 2018→2026 两融交易日历。
- 周频建议：`financing_flow` 周求和（净流入）+ `state` 周末值。

### L4 情绪与跟随资本

- 主用源：`data/cf/derived/atoms/l4_history.jsonl`（日频，2021-08-02 → 2026-10-28，1268 行；
  底层数据=通达信 880005/880006 涨跌家数/涨停数）。字段：`state`（PANIC/APATHY/RECOVERY/
  FOMO/EUPHORIA/CAPITULATION/…）、`advancers`、`limit_up`、`advancers_percentile`、
  `amount_ratio20`。
- 可选补充：`data/r2/e5/csv/lhb_daily_stock.csv`（龙虎榜，日×个股，2021-01-04 → 2026-10-28，
  98,419 行，单位元，带 `available_at`）——跟随资本/席位行为的细粒度来源，第一版不进周表，
  Phase 2 案例层可用。
- 周频建议：`limit_up` 周求和、`advancers`/`amount_ratio20` 周均、`state` 周末值。

### L3 市场承接背景（广度/参与/集中）

- 主用源：`data/cd/sector_axes/l1_market_axes.json.gz`（日频，2022-01-13 → 2026-10-27，
  1157 行，无重复日期）。字段：`breadth`、`part`（参与度）、`conc50`（前50集中度）、`disp`、
  `eq_ret`、`vol`、`ret20d`、`regime`（R_RISK_ON_BROAD/R_RISK_ON_NARROW/R_REBOUND_MIXED/
  R_RISK_OFF/R_DEPRESSED）。
- 备选：`l2_four_axes.json.gz` / `l2_state_table.json.gz`（**2021-01-04 起**，83 个 l2 板块×日
  面板，116,781 行，(l2,date) 无重复；数值字段仅 status=OK 行存在）——板块级承接比市场轴早
  一年，Phase 2 若做板块维度可把稠密窗口前移到 2021-01。
- 周频建议：`breadth`/`part`/`conc50` 周均 + `regime` 周内众数。

### L3 个股承接事件（CD episode）

- 主用源：`data/cd/l4_episodes.json.gz`（live，30,312 条 episode；备份
  `sector_axes/backup_20261028/` 30,296 条）。覆盖 start 2021-04-06 → 2026-10-28、5,341 股；
  `episode_id`=`stock#ord` 零重复；terminal=INACTIVE_TERMINATION 25,636 / CENSORED 3,764 /
  STRUCTURAL_FAILURE 912；`sector_path_at_start` 87.5% null（不用该字段）。
- 周频建议：周内新发起 episode 数（按 origin L/M/S 分列可选）与周相交存活数；归属判据
  `start≤weekEnd 且 (end≥weekStart 或 terminal=CENSORED)`。个股明细留给 Phase 2 案例层。

### 成本带 proxy（cost_proxy）——需要时重算，不直接读产物

- **episode 产物落盘前已 strip 全部 cost 字段**（CD-5A 设计如此）。周频若需 P25 量权成本带
  或锚定 AVWAP，必须从 `data/cd/daily_fullmarket/`（5,430 股×2021-01-04→2026-10-28，qfq
  复权，amount 为声明式缺失勿用）+ episode 区间重算；现成实现：
  `scripts/cl_r2_avwap_census.py / census2.py / mechanism1.py`（episode 锚定
  AVWAP=Σamount/Σ(vol×100)，gap/retention/touch/bounce/drift）。
- `cl_radar/r3_effort_result` 与 `r2_avwap` 目录只有 **84 股试点的汇总统计**（无逐股逐日
  落盘），不能直接按周切片；Phase 2 需要时重跑脚本。
- 第一版周表不纳入 cost_proxy；Phase 2 引入时仍称 cost_proxy，不作真实机构成本解释。

### L2 长期/机构背景（低频注释层）

- 唯一候选：`data/csr8_national_capital/raw/holdings/`（**84 股 × 22 个季度端点**
  （2021Q1→2026Q2），东财十大流通股东，HOLD_NUM 单位股，1798 非空+50 空）+
  `publication_dates/`（每股新浪 report_date 列表 → PIT 披露时点）。**按真实披露日使用，
  不插值**；第一版只作案例注释，不进周表。同目录 etf_shares 为 L1 冗余源（仅沪市、停在
  2026-09-18），不用。

### 成本带 proxy（cost_proxy）

（已并入上文"L3 个股承接事件"小节：episode 产物 strip 了成本字段，需重算。）

## 3. 周频样表验证（2024 全年）

- 52 周全部四层有观测（`days_obs` 最小 2，为节假日短周）；同日重复 0；PIT 违例 0。
- 全历史干跑（2022-01-01 → 2026-10-28，仅验证未存档）：246 周全对齐，仅 2022-W01 缺市场轴
  （l1_market_axes 2022-01-13 才开始，属预期）；峰值内存 76MB。
- 抽查关键周的读数合理（见 §1 第 4 点）；episode 存活量级（3000–5000）与全市场人口一致。
- 周边界处理：以周内**最后有观测的交易日**为 `week_end`，不做日历填充，不制造假观测。
- **合规性**：周表只取状态驻留（周末值/众数）与原始量的周均/周和，不做加权合成指数——
  遵守 `capital_weather` 的 `aggregation: FORBIDDEN` 约束。

## 3a. 已知工程坑（Phase 2 编码时注意）

- 日期格式两套：cd/cl_radar 为 `YYYY-MM-DD`，atoms/market_axes 键为 `YYYYMMDD`——周表统一
  YYYYMMDD。
- r4 per_stock 的 code 带交易所前缀（`sz.000078`），daily_fullmarket/l4_episodes 用裸 6 位码。
- `daily_fullmarket` 的 `amount` 为声明式缺失（declared_gaps），算成交额相关量需自备口径。
- L2 无 atom（atoms 体系只有 L1/M/L4）——机构层只能走 csr8 holdings 案例注释。

## 4. 已知缺口与处理

| 缺口 | 影响 | 处理 |
|---|---|---|
| 深市 ETF 明细自 2016-12 起 | 2012–2016 L1 家族只覆盖沪市 | 家族数自适应+结论只写"沪市家族" |
| L3 市场轴 2022-01 起 | 四层共同稠密窗口被限死 | 接受；更早年只做 L1/M 两层背景 |
| 两融原始单位两所不一致（元 vs 亿元） | 直接拼原始 CSV 会错 100 倍 | 一律走 m_history 归一值 |
| SSE ETF 快照每年 16-20 个 EMPTY 日 | 家族日线有小缺口 | L1 原子已按 families_observed 自适应 |
| L2 机构持仓披露滞后 1-2 月 | 不能当周频当期输入 | 只作披露后案例注释 |
| r6_equityflow 归一 JSONL 仅近期窗口 | 不能当历史源 | 忽略，用 cf/raw + atoms |
| r2/shadow/breadth_history 仅 14 日且有同日重复 | 非历史源 | 忽略 |

## 5. v0 数据方案（Phase 2 输入定义）

- 周表 = `scripts/cfis/is0_weekly_sample.py` 的列集（L1/M/L4/L3 市场轴/episode 计数）。
- 全历史窗口：2022-01 → 今（稠密四层）；扩展窗口 2018-01→2021-12（M+L1 两层背景）。
- Phase 2 第一步把样表跑满 2022-01→2026-10，再做阶段标注与连续窗口检查；标签（如
  "支持代理偏强×承接弱"）仅在 Phase 2 中试做，不回填周表输入。

## 6. 停止点

Phase 1 到此为止：盘点、样表、缺口清单均已交付。是否进入 Phase 2（慢频历史图景）由用户决定。
