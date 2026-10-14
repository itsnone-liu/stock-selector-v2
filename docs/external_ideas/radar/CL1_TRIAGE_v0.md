# CL-1 雷达分诊 v0 — 2026-10-14

> 输入：`data/cl_radar/catalog_v0.{md,json}`（GitHub 28 查询 → 180 去重 repo；arXiv 10 查询 → 44 篇；0 错误）。
> 本文件：人工分诊 → idea family 去重 → Tier 分层。裁定动词沿用 CAPITAL_LOGIC_MAP §0。

## 0. 雷达信噪比（量化事实，第一批）

| 轨道 | 命中 | 量化相关 | SNR |
|---|---|---|---|
| GitHub | 180 | ≈60-70 | **35-40%** |
| arXiv | 44 | ≈25 | ≈55% |

关键词碰撞严重，Tier 判定必须人工过：`wyckoff` 命中晶体学（Wyckoff positions）、`order splitting` 命中 PDE 分裂法、中文词命中政治库/综艺库/NLP 语料、Bee Movie 剧本 ×4。**结论：关键词雷达只能给候选，分诊不能自动化省略。**

## 1. Idea Family 表（12 族）

| # | Family | 链上格 | Tier | 代表 | 学术锚 | 数据级 | 初判（待深读修正） |
|---|---|---|---|---|---|---|---|
| F1 | 筹码分布/换手衰减（A股） | ①③ | **A** | myhhub/stock ★14.8k、flutter_stock | — | 日线 | R1 对照研究的对手实现 |
| F2 | PIN/VPIN 知情交易强度 | ②⑥ | **A** | shuangology/PIN（**A股日线实现**）、PINstimation(R)、jheusser/vpin | Kyle-type stealth 理论簇 | PIN 日线可估；VPIN 需量桶 | POTENTIAL_INCREMENT：C2/C6 的 L1 机制量候选 |
| F3 | Kyle λ / 价格冲击系数 | ④ | **A** | qhw-isaac/kyles-lambda、toxicflow、nirajneupane17（λ+Amihud） | **arXiv 2607.01377：日线 order flow 估 λ 预测截面收益（CRSP 2020-25）**；Cont OFI 簇 | **日线可估** | **R5 最高优先：日线版有正主文献** |
| F4 | OFI/CVD/absorption 盘中工具 | ③④ | A 机制 / parked | orderflow-metrics、orderbook-heatmap、ModFlow 套件 | Cont 2010、广义 OFI（中国） | 4 级 tick | 思想吸收；实现等数据解锁 |
| F5 | Wyckoff/VSA effort→result（A股） | ②③⑥ | **A-** | **WyckoffTradingAgent ★748（A股筛选器，活跃）**、wyckoff_skill、srl-Weis 系统 | — | 日线 | R4 落地实现已找到，深读评分定义 |
| F6 | Anchored VWAP | ① | B+ | s-kust/anchored_vwaps、ak2k2（**机械锚点先例**：swing H/L 由量价时序自动提取） | VWAP execution 簇（5 篇） | 日线 | R2：机械锚点规则有先例可借 |
| F7 | Volume/Market Profile | ① | B | py-market-profile ★408、srlcarlg TPO | LOB volume profile 重尾（2012） | 日线 | CD-5 已覆盖大半；POC/value area 概念待对账 |
| F8 | 处置效应/行为金融因子 | ⑤ | **A** | ChenLifan0220 A股 PT/MA 因子(2018)、dispositionEffect(R) | 处置效应簇（含雪球证据、中国参照点依赖复制）+ realization utility | 日线 | C5 机制桥的直接文献+现成实现 |
| F9 | A股数据/平台 | — | C | adata、**free-stockdb（声称含分钟K）**、jqdatasdk、Ashare | — | — | 数据缺口候选：第二级阶梯的解锁路径 |
| F10 | LLM agent 投研（A股） | — | C | TradingAgents-astock（龙虎榜/游资/解禁接线）、aiagents-stock | — | — | 只参考数据源接线（龙虎榜/大宗是我们的 MISSING 项） |
| F11 | 灵均 A股微观结构 Kaggle | ④ | B | 4 个参赛仓库 | — | tick | C4 的 A股特征工程参考 |
| F12 | 微观结构阅读清单 | — | lead | dylantlwu/quant-research-notes（被否假设+书单） | — | — | 雷达线索源 |

## 2. 第一批五个高亮

1. **R5 学术锚（最重要发现）**：arXiv 2607.01377《Liquidity Premium and Investment Horizons》——直接从**日线** order flow 估 Kyle λ 并检验截面收益预测（CRSP 2020-2025）。R5"日线版 price impact"不是降级妥协，是有正主文献的路线。
2. **R4 实现找到**：WyckoffTradingAgent（★748、A股、2026-10 仍活跃）——absorption/dry-up/breakout quality/supply 的日线评分筛选器，正是方案 R4 要的东西，深读后定对照设计。
3. **C2/C6 日线 L1 候选**：A股日线 PIN 实现（基于 Yan-Zhang 改进估计法）——知情交易强度不用 tick 也能估（VPIN 才需要量桶）。
4. **R1 对手确定**：myhhub/stock（★14.8k）筹码分布+形态识别全链路——R1 对照研究的外部基准。
5. **数据阶梯状态更新（2026-10-14）**：第二级已由 **EI-5P 前瞻采集**启动（2026-10-12 起，T-1 cohort ~1025 股，竞价段+开盘 30 分钟 1 分钟线，raw 不可变，10-12 一致性校验 PASS）——但**仅前瞻累积、无历史回看**。历史分钟数据仍缺：free-stockdb（分钟K本地引擎）作为回测加速候选仍登记，属独立数据项目决策。

## 3. 深读队列（进行中）

- 代码侧：F1(myhhub/stock)、F5(WyckoffTradingAgent)、F2(shuangology/PIN)、F6(s-kust/anchored_vwaps)
- 论文侧：2607.01377（日线λ）、2112.02947（广义OFI/中国）、2308.01112（日本市场拆单行为九年实证）、2001.01860（冲击凹性）

## 4. 裁决待定项

- F2 PIN 全市场 5400 只×滚动窗的 MLE 计算成本与估计噪声 → 深读后评估可行性（或先 84 股试点）。
- F3 与 EI-5"更少成交推更大位移"的信息重叠 → λ 就是该思想的系数量化，需按 Q6 对照 T3。
- F9 分钟K解锁 → 独立数据项目，不在 CL-0 范围内自动触发。

## 5. 深读判定增量（代码侧，2026-10-14；详报告 data/cl_radar/deepdive/DEEPDIVE_CODE.md）

| Family | 判定更新 |
|---|---|
| F1 筹码 | R1 对照 baseline 确定：三角核（(O+H+L+C)/4 峰值、面积归一、一字板单 bin）×全 bin 统一线性衰减 (1−换手率)，150 bin/210 日/0.01 元精度。**对手两个致命伤：默认不复权（除权跳空错位历史筹码栈）+ 换手>100% 饱和——对照实验前必须先替它修 qfq，否则比较不公平。** 由此 R1 可做四轴消融：核形 / 典型价（OHLC/4 vs HLC/3）/ 衰减律（线性 vs survival 双模型）/ bin 分辨率 |
| F5 Wyckoff | 五个日线评分（absorption/dry_up/breakout_quality/supply_pressure/failed_breakout）公式全透明（量比+close_pos+影线+前高前低），A股制度处理认真（一字板按振幅≤1% 排除、价格阈值按板块×1.2/1.4、量比不缩放）→ **POTENTIAL_INCREMENT：先落 OBSERVE/shadow 特征**。注意：缩量承接条件与 R2-8 系实验同构=部分 ALREADY_COVERED，增量在其余四评分；阈值全手工调优且作者自设 shadow-only——**照搬公式不照搬总分** |
| F2 PIN | **修正初判：PIN 用纯 OHLCV 估不了**——需分型买卖单数据（Wind 四档金额÷档位下限≈单数；EKOP 模型+Lin-Ke(2011) log-sum-exp 稳定 MLE，30 日滚动窗）。免费替代=东财超大/大/中/小单资金流（口径同构）→ F2 降为**数据门控候选**：先资金流数据管线+合成数据单测，再谈可行性；且受"大单≠主力"测量误差上限约束 |
| F6 AVWAP | 机械结构锚可移植（ATR14×2.5 zigzag 摆动点确认，~40 行）；**PIT 规则=锚点以确认日入轴**（极值日≠可知时点，zigzag 是确认滞后不是 look-ahead，但回测必须校验确认日≤决策日）；零复权处理→A 股移植必须 qfq。注意其 Typical=(O+H+L+C)/4 与我们 (H+L+C)/3 不同——并入 R1 的典型价消融轴 |

**跨仓库两条通用教训（写进雷达操作规程）：**
1. **复权缺失是外部成本/筹码类实现的头号死因**（4 个深读对象里 2 个零处理）——任何外部实现接入前第一项检查。
2. **确认日≠发生日**：一切锚点/事件选择类构造必须以确认日入 PIT 轴，否则是精致的晚位选择器。
