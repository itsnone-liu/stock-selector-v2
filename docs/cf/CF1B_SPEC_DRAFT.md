# CF-1B Atom State Engines — 预注册 Spec v0.3（框架稿；阈值 [TBD-post-CF1A]）

*前置:* CF-1A 闭合报告 v1.0 + 用户确认（**本 spec 在此之前不执行**）· *Contract:* `cf0_contract_freeze.json` v2 · *Gates:* G1-G8 全程适用

## 0. 工程原则（冻结）

- **Atom-Only（G4）**：L1/M/L4 三引擎独立实现、独立运行、独立输出；禁跨层构造特征（M 引擎不得读 ETF 份额，L4 不得读两融）。
- **无未来 outcome（G5）**：任何阈值/状态判定只用 decision_time 当日及以前数据；backfill 用途限白名单六项。
- **Fail-closed（G6）**：核心传感器缺失/NOT_YET_OBSERVABLE → 状态输出 `INSUFFICIENT_SUPPORT`，禁补值猜态。
- **禁聚合（G7）**：三引擎输出不汇总、不加权、不产生任何市场级复合量。
- 每引擎输出 = 合同 3 的 20 字段 schema 子集（evidence/counter_evidence 必填）。
- 阈值预注册于本 spec v1.0（CF-1A 闭合后、任何历史回放前填写并冻结）；看过回放结果后改阈值禁止。

## 1. L1 — Policy Stabilization Behavior Engine（五态）

**输出语义**：stabilization behavior 强度，非身份断言（P1）。状态集（合同 v2）：NORMAL / WATCH / STABILIZATION_READY / STABILIZATION_ACTIVE / NORMALIZING。

| 传感器 | 来源（CF-1A 裁决） | 用途 |
|---|---|---|
| 宽基 ETF 份额日变化 | SSE 官方（T 晚）/ SZSE 官方（T 晚） | 核心七只宽基〔510300/510050/510500/512100/588000/159915/A500 待代码定案〕单日与多日份额净增 |
| 宽基 ETF 成交额 | sina_etf_bars（2005+，第三方标注） | 放量倍数〔相对自身 N 日基线，N 待预注册〕 |
| 价格承接 | 指数日线（本地） | 尾盘/日内跌幅收窄结构 |

**判据方向（阈值 [TBD-post-CF1A]）**：STABILIZATION_ACTIVE ← 宽基份额异常净增 × 成交异常放量 ×（当日或前日指数跌幅超过 [TBD]）；NORMALIZING ← ACTIVE 后份额增速回落 + 指数修复。反证向量：份额增长但成交萎缩、净增集中于非宽基/行业 ETF。

**数据质量前置（CF-HX/Resonance 审计引入，L1 强制）**：族聚合份额变化必须先过**折算中和**——份额拆分/合并会产生假天量净申赎（515880 案例 +333.13 亿份假申购）。判据=复权因子(bfq/qfq 双口径收盘比)按 k 跳变 ≈ 份额按 k 跳变 → 写回折算后真实净申赎 + `share_adjust=k` 标记 + 尾随 10 日窗口按折算后基准重算。禁用幅度阈值判折算（真申购也会超幅度，512100 案例 +132.8%）。复权因子来源=[TBD-post-CF1A]（双口径 K 线比值 vs 官方因子接口）。

## 2. M — Margin Atom Engine（五态 + 三派生量）

状态集：LEVERAGE_BUILDING / NEUTRAL / DELEVERAGING / DELEVERAGING_ACCELERATING / DELEVERAGED。
派生量（不猜庄家成本，纯官方汇总口径）：`financing_balance_pressure`（余额/N 日基线比）、`financing_flow`（日变化额）、`deleveraging_velocity`（日变化额的变化率）。**v1 不构造爆仓概率**（合同 v2）。

| 传感器 | 来源 | 用途 |
|---|---|---|
| SSE 融资余额/买入额 | 上交所官方（T+1 晨，待定案） | 双所合并序列（单位归一：SSE 元 / SZSE 亿元→统一） |
| SZSE 融资余额 | 深交所官方（发布时点待同批采样） | 同上 |
| 指数价格 | 本地 | 价格×余额四象限基础事实 |

**判据方向**：LEVERAGE_BUILDING ← 余额 N 日连升 + 买入额占比上行；DELEVERAGING_ACCELERATING ← 余额下降且 velocity 负向扩大；急跌×急降 → 标注强制去化风险（描述性，非概率）。断点表（2019-10 扩容/2023 融券新规）作为解释附注随输出。

## 3. L4 — Sentiment Atom Engine（六态）

状态集：APATHY / RECOVERY / FOMO / EUPHORIA / PANIC / CAPITULATION。

| 传感器 | 来源 | 状态机角色 |
|---|---|---|
| 上涨家数 + 全市场成交额 | TDX 880005（2021-08+，第三方标注，T 晚） | 核心：家数历史分位〔窗口 N 待预注册〕+ 成交额相对基线 |
| 涨停家数 | TDX 880006（2021-08+） | 辅助：FOMO/EUPHORIA 判据 |
| 乐咕当日快照（15:00 统计） | 第三方 | **仅当日交叉验证哨**（非回放输入） |
| 涨停池明细（30 日窗口） | 东财 | **仅当日观察增强，非回放输入**（UNSUPPORTED-for-replay） |
| 下跌家数 | — | **v1 不依赖**（UNLOCATED；PANIC/CAPITULATION 用"上涨家数极低分位+成交额结构"表达）|
| 题材扩散 | — | NOT_AVAILABLE v1 |

**明示取舍（需用户确认）**：①下跌家数不进 v1；②回放深度=2021-08+，2018-2021 段 L4 输出 INSUFFICIENT_SUPPORT；③乐咕/东财池仅做当日哨兵，日报注释用。

## 4. CF-1C Capital Weather v0.1 模板（并排展示，禁聚合）

```text
Capital Weather v0.1  (data as of: 逐传感器标注 available_at)
L1 Policy Stabilization  state=... pressure=... velocity=... confidence=...  [evidence: ...|counter: ...]
M Margin                 state=... financing_balance_pressure=... flow=... velocity=...
L4 Sentiment             state=... velocity=... confidence=...
（自然语言一句：允许。Market Regime / Net Capital Pressure / 概率预测：禁止。）
```

## 5. 交付与验收

- `research/cf/atoms/{l1_policy.py, m_margin.py, l4_sentiment.py}` + `scripts/cf/capital_weather.py`
- 验收 = 回放白名单六项检查全过 + 五个交易日连续日报产出 + G1-G8 自检表
- 数据落盘：`data/cf/`（分区：raw/官方源原样 + derived/引擎输出；单文件≤2G，内存≤2.5G 继承）
