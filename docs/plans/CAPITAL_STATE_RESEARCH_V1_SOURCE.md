# Capital-State Research V1.0 落地方案（原文存档）

> Source of truth: 用户 2026-09-25 飞书文档 Capital-State_Research_V1.0_落地方案.docx
> 承接 T8 FINAL FROZEN 97879ca。本 md 为机械转存，任务书=§20。

Capital-State Research V1.0
资金结构与主导资金状态研究落地方案
研究范式重构基线｜承接 T8 FINAL FROZEN（97879ca）
定位：T3–T8 作为既有 Portfolio / Execution Layer 保持冻结；新建 Capital-State Research 主线，以“资金主体 → 行为约束 → 资金行为 → 筹码/资金状态 → 可观测证据 → 数据验证”为研究因果方向。第一轮不产生交易规则，不以收益优化反向定义资金状态。
1. 研究目标与范式
旧路线偏向“价格/成交量数据 → 统计规律 → 状态 → 未来结果 → 仓位”。新路线改为：先明确资金主体、目标、约束和时间尺度，再提出资金行为机制与状态假说，最后寻找直接证据或代理变量进行验证。
核心目标：尽可能识别当前市场、行业和个股中决定价格趋势的资金是谁、处于什么状态、正在做什么，以及这种行为是否仍具持续条件。数据分析从“规律生成器”降为“测量仪、验证器和审计工具”。
2. 总体架构
Layer 1 — Market Capital State：市场风险资本供给、风险预算扩张/收缩、长期配置与短期交易结构。
Layer 2 — Sector Capital State：行业资金流入/流出、集中/扩散、相对强弱及拥挤/撤离。
Layer 3 — Dominant Capital / Chip State：个股主导资金、筹码控制权、吸筹—锁筹—拉升—换手—派发—退出。
Layer 4 — Marginal Capital Behavior：价格、成交量、换手、效率、动能、突破及现有 ADD/REDUCE/EXIT 等末端观测。
原则：个股信号必须结合 Market 与 Sector 背景解释；量价只作为上层资金行为留下的观测结果，不能单独证明某类资金主体或“主力行为”。
3. CSR-0：Research Contract
3.1 C1 — 因果方向
Capital Actor → Constraint / Incentive → Capital Behavior → Chip / Flow State → Observable Evidence → Price / Volume。
禁止从某个 K 线或量价形态直接倒推“主力一定在吸筹/出货”。
3.2 C2 — 隐变量原则
主导资金、吸筹、锁筹、派发等均视为 latent state。除非存在直接证据，否则只能表述为“与某资金状态假说一致的证据”，不得把代理变量写成主体事实。
3.3 C3 — 证据等级
硬约束：单独 Level C 不得证明 Level A 的资金主体状态。
3.4 C4 — Mechanism First
任何正式变量必须能写出：Capital Actor → Behavior Mechanism → Expected Observable → Variable。禁止先扫描大量 feature，再依据显著性事后编写资金故事。
3.5 C5 — Policy Firewall
Capital-State discovery 阶段禁止以收益、Sharpe、回测表现选择状态定义；禁止修改 T3–T8 冻结规则。
4. CSR-1：Capital Actor Ontology
第一版按行为约束而非账户标签划分七类主体：
每个 actor 至少记录：Scale、Horizon、Entry Constraint、Exit Constraint、Objective、Observable Footprint。
正式产物：CAPITAL_ACTOR_ONTOLOGY.yaml。所有后续 hypothesis 必须引用 actor_id。
5. CSR-2：Capital Lifecycle Ontology
不强制线性状态机。允许 D2→D1、D4→D2、D5→D4、D6→D4 等回退/重构路径；尤其不得预设 D6 必然进入 D7。
6. CSR-3：首批六个机制假说
H01 Accumulation
大资金在市场冲击约束下持续建立库存。预期表现：累计成交显著，但价格位移相对有限，成本区逐步形成。
H02 Locking
稳定持有者控制更多筹码后，有效流通供给下降；同等价格推动所需新增成交可能下降。缩量上涨/效率提升仅为 C-level 证据。
H03 Markup
筹码锁定 + 新增边际需求 + 有限供给形成高价格效率；健康回调应体现卖压弱于上涨阶段推动力。
H04 External Participation
主升赚钱效应吸引机构、趋势、游资和散户；重点区分健康接力与为原主导资金退出提供流动性。
H05 Distribution
外部需求增加同时主导库存供给增加，可能形成巨大换手但价格效率下降；放量滞涨本身不能等同于派发。
H06 Loss of Control
主导资金退出后仍可能出现强反弹，但趋势持续能力下降。T8 的 MFE flat + Recovery↓ + Return↓ + DD↑ 仅作为研究动机，不构成证明。
每个 hypothesis 必须包含：Economic Mechanism、Expected Observations、Direct Evidence、Proxy Evidence、Counter Evidence、Alternative Explanation、Historical Test、PIT Requirements。
7. CSR-4：Evidence Map
建立 CAPITAL_EVIDENCE_REGISTRY.parquet，一行一个 evidence。建议字段：
evidence_id / actor_id / hypothesis_id / capital_layer
evidence_name / economic_mechanism / evidence_level
data_source / raw_field / frequency / publication_delay / historical_depth
point_in_time / revision_risk / coverage
expected_direction / counter_evidence / alternative_explanations
confidence / status
capital_layer 固定为 MARKET / SECTOR / STOCK / MARGINAL。
8. Data Feasibility Audit：先审数据，再写抓取器
不立即全量抓取。先审计每类数据是否能获得可信历史记录、是否 PIT、覆盖多久、披露延迟、修订风险与成本。
Market
ETF份额/申赎；融资融券；市场成交额；市场宽度；大小盘结构；跨境资金可得口径；长期资金公开行为
Sector
行业ETF份额；行业成交额；行业相对强弱；breadth；资金集中程度；龙头贡献度
Stock
股东人数；十大股东/流通股东；基金持仓；大宗交易；龙虎榜；股东增减持；回购；融资融券；解禁；成交/换手；筹码成本分布
9. PIT 审计
所有披露型数据必须区分 observation_date、publication_date、available_date。实时研究只能使用 available_date <= decision_date 的信息。
例如季末持仓日期不等于市场当日已知日期；披露延迟必须进入数据契约，否则视为 future leakage。
10. 数据可用性评级
A — DIRECT_PIT：直接且可在决策时点使用。
B — DIRECT_DELAYED：直接证据但有披露延迟。
C — RELIABLE_PROXY：可靠代理。
D — WEAK_PROXY：弱代理，仅作辅助。
E — UNAVAILABLE：现实不可可靠获取。
同时记录 coverage、frequency、latency、revision、cost。允许理论状态最终被判定为 UNOBSERVABLE。
11. Relative Capital Framework：Market → Sector → Stock
任何 stock-level observable 尽量同时构造 RAW、MARKET_RELATIVE、SECTOR_RELATIVE 视角。目标不是机械线性相减，而是尽量剥离系统性资金活动后再讨论 stock-specific capital activity。
典型解释框架：个股强+行业强+市场强可能主要是系统性风险资金扩张；个股强+行业强+市场弱更可能体现行业配置；个股强+行业弱+市场弱才更值得提出个股特异主导资金假说。
12. Capital Case Sheet：第一轮以案例为主
每个案例至少包含：
MARKET：风险资本状态、成交、breadth、大小盘结构。
SECTOR：资金方向、relative strength、breadth、集中/扩散。
STOCK：长期累计换手、筹码迁移、上涨效率、回调卖压等。
DIRECT EVIDENCE：机构持仓、股东人数、大宗交易、融资、增减持等可得信息。
HYPOTHESIS：H01–H06 的支持强度。
COUNTER EVIDENCE：反证与竞争解释。
首轮建议约 100 个典型案例：20 个完整大牛股、20 个突破后失败、20 个高位崩塌、20 个长期横盘后启动、20 个板块行情中的普通跟随股。目的不是训练模型，而是检验资金理论能否解释完整生命周期。
13. 第一轮禁止项
No ML
No feature selection
No return optimization
No threshold search
No policy backtest
允许：descriptive statistics、event study、cross-sectional comparison、trajectory analysis、case study、hypothesis testing。
14. 机制 Gate
统计显著性排在这些机制与证据 Gate 之后。
15. 防“数字迷宫”硬门禁
每增加一个正式变量，必须回答：
它对应哪一种资金行为？
为什么该资金行为理论上应该产生这个观测？
还有哪些机制也能产生同样数字？
有什么独立证据能够区分这些解释？
任何回答不完整的变量只能进入 exploratory appendix，不得进入 Capital State Engine。
16. 与 T3–T8 的关系
T3–T8 全部保持 FROZEN，不重写历史结论。重新定位为 Portfolio / Execution Layer：T3/T4 负责初始参与与 exposure；T5 负责动态仓位；T6 负责失败机制；T7 负责再扩张；T8 负责 repeated re-risk。
Capital-State Research 是 Market Understanding Layer。未来只有在资金状态研究成熟后，才允许研究“同样 T4/T5/T8 条件在不同资金背景下是否具有不同风险收益结构”。
17. Commit / 阶段路线
CSR-0 — Research Contract
CSR-1 — Capital Actor Ontology
CSR-2 — Capital Lifecycle Ontology
CSR-3 — H01–H06 Hypothesis Registry
CSR-4 — Evidence Map
CSR-5 — Data Source Feasibility Audit
CSR-6 — PIT / Availability Audit
CSR-7 — Case Study Protocol
CSR-8 — Pilot Cases
CSR-9 — Hypothesis Review
CSR-9 之前禁止产生交易策略。
18. CSR-9 结论状态
SUPPORTED
PARTIALLY_SUPPORTED
NOT_SUPPORTED
UNOBSERVABLE
UNOBSERVABLE 是正式且允许的结论。不得因为理论上重要但数据不可见，就用大量弱技术指标拼接成伪“主力指数”。
19. 第二轮：Capital State Engine 的进入条件
只有 CSR-0～CSR-9 证明部分资金状态具备可识别性，才允许构建 Capital State Engine V0。
V0 输出首先是状态与置信度，不是 BUY/SELL：
MARKET：risk_budget_expanding / contracting / stable 等。
SECTOR：capital_concentrating / diffusing / outflow 等。
STOCK：dominant_control_likely / distribution_evidence_rising 等。
MARGINAL：incremental_demand_strengthening / weakening 等。
CONFIDENCE：证据强度与冲突程度。
20. 第一轮执行任务书
启动 Capital-State Research，严格以 T8 FINAL FROZEN `97879ca` 为旧研究边界。不得修改 T3–T8 任何冻结定义、代码、Gate 或结果。第一轮只完成 CSR-0～CSR-4：Research Contract、Capital Actor Ontology、Capital Lifecycle Ontology、H01–H06 Hypothesis Registry、Evidence Map schema。禁止回测、禁止收益优化、禁止阈值搜索、禁止 ML、禁止产生任何交易规则。所有资金状态均视为 latent state；建立 Actor→Constraint→Behavior→Expected Observable→Evidence 的单向机制链；证据分 A Direct / B Chip / C Price-Volume，单独 Level C 不得证明资金主体状态。每个 hypothesis 必须包含机制、预期观测、直接证据、proxy、反证、竞争解释和 PIT 要求。完成后提交独立 commits，并停止，等待审计，不进入数据抓取。
21. 北极星问题
当前决定价格的主要资金是谁，它持有什么筹码、成本大致在哪里、当前是在增加风险、维持风险、转移筹码还是退出风险；市场与行业资金环境是在帮助它还是对抗它？
只有在回答这一问题之后，才进入“在该资金结构下，我们自己的资本应该承担多少风险”的 Portfolio / Execution 决策。
=== TABLE 1 ===
等级 | 名称 | 定义
A | Direct Capital Evidence | 直接反映资金主体、持仓、申赎、席位、增减持等变化
B | Chip / Ownership Evidence | 反映筹码集中、成本迁移、持有结构、换手结构等
C | Price-Volume Proxy | 价格、成交量、换手、效率、动能、MFE/DD 等末端代理
=== TABLE 2 ===
ID | 主体 | 说明
A1 | Policy / Sovereign-like Capital | 国家队、政策型长期资金
A2 | Long-Horizon Institutional Capital | 保险、养老金、长期配置机构
A3 | Active Institutional Capital | 公募、私募等主动管理资金
A4 | Cross-Market / Allocation Capital | 跨境、跨资产配置资金
A5 | Stock-Dominant Capital | 个股层面具有筹码影响力的大资金
A6 | Tactical / Momentum Capital | 游资、事件、趋势交易资金
A7 | Retail / Diffuse Capital | 分散跟随资金
=== TABLE 3 ===
状态 | 英文 | 经济含义
D0 | No Dominant Evidence | 无明显主导资金证据
D1 | Accumulation | 潜伏/吸筹
D2 | Concentration / Lock | 筹码集中/锁定
D3 | Probe / Activation | 试盘/启动
D4 | Markup | 突破/主升
D5 | External Participation / Acceleration | 外部资金进入/加速
D6 | High-Turnover Transfer | 高位换手/筹码交接
D7 | Distribution | 派发
D8 | Dominant Capital Exit | 主导资金退出
=== TABLE 4 ===
Gate | 要求
G-Hxx-1 Mechanism | 是否存在明确的资金机制链？
G-Hxx-2 Evidence Independence | 是否至少有两个不同来源/层级的 evidence，而非多个高度相关技术指标？
G-Hxx-3 Alternative Explanation | 是否登记竞争解释？
G-Hxx-4 Counterexample | 是否主动搜索反例？
G-Hxx-5 PIT | 所有实时解释数据是否满足 PIT？
G-Hxx-6 Generalization | 不同年份、行业、市值层是否仍可观察？