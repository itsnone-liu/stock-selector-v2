# R2-9 Structural Rebase — 预注册合同（冻结于执行前）

按用户裁定 2026-10-08：研究问题=「已确认 BROKEN 的旧成本结构，经价格与筹码重组后，何条件能形成**再次具有支撑持久性**的新成本结构」。不预测上涨；不输出 BUY；户数集中只作解释性 descriptor。

## R9-1 BROKEN cohort（复用冻结定义，不得重定义）
close < 500日成本带下沿×0.95，连续 5 日；锚点 tB=第5根确认 bar。事件抽取复用 breakdown_aftermath.py（commit 0c9f2bc，20,660 事件口径），一股票一旧带一事件。

## R9-2 Rebase formation（新可观测成本结构形成，全部冻结）
自 tB 起滚动计算 **120日短窗成本带**（cost_band 同算法、窗口120）。tF = 满足以下全部的第一个 bar（搜索窗 tB+40 .. tB+250，逾窗未成 → NO_REBASE）：
- F1 新带有效（cost_band 非 None）；
- F2 带宽收窄：width(tF)=(hi−lo)/mid，width(tF) < width(tF−20)；
- F3 close(tF) ∈ [lo, hi]；
- F4 带下停留结束：近20根无 close < 新带lo×0.95。
状态机：BROKEN → REBASE_PENDING (tB,tF) → NEW_SUPPORT_CANDIDATE (tF)。

## R9-3 First retest（完全复用 R2-6 指标，不发明新标准）
tR = tF 后首根 close < 新带 lo。度量（与 R2-6 同名同义）：
penetration_depth=min(close[tR..tR+9])/lo−1；recovery10=close[tR+10]/close[tR]−1；
time_below=tR..tR+19 中 close<lo 的天数；breakdown_rate=对**新带**的 5 日确认破位在 60 日内发生；fwd R60=close[tR+60]/close[tR]−1。
单事件判定：SURVIVED = 60日内无新带破位 ∧ recovery10≥0；否则 FAILED。

## R9-4 Verdict（三分类，冻结数值）
cohort 层对比 R2-6 基线支撑存活率：
REBASE_VALIDATED：SURVIVED 率 ≥ R2-6 基线（R2-6 已发表存活口径）；
REBASE_WEAK：带形成但 SURVIVED 率显著低（≥10pp 差距）；
NO_REBASE：250 日内未形成合格新带。

## Ownership redistribution descriptors（仅解释性，禁预设方向）
比较组按 tB 前后两个季度股东户数变化 pct：CONCENTRATING(<−3%) / FLAT(±3%) / DISPERSING(>+3%)；
比较因变量：formation speed (tF−tB)、SURVIVED 率。**方向由数据决定**，top10/户均持股只作辅助描述。

## PIT 边界（可交易性硬线）
季度数据 available_at = 季末+45 自然日（保守冻结）。Explanatory layer 可用事后数据；**tradable layer 只允许 available_at ≤ decision_time 的季度**，再强也不得产品化超前数据。

## 停止线
单次全量执行；不改窗口、不调阈值、不加特征族。产出 = 各 cohort 三分类计数 + R2-6 复用指标表 + ownership 三组对比；无 BUY 输出。
