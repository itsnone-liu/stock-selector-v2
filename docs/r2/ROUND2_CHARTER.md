# Round 2 — Capital & Chip Intelligence System（用户 2026-10-05 下发，权威章程）

## 0. 第一原则
- **禁止以"无法绝对证明"为理由停止分析和判断。** 市场天然不完全信息。
- 目标不是证明主力持有多少/成本精确多少，而是：利用全部可得公开数据与行为痕迹，推断最可能的资金主体、筹码结构、成本区域、行情阶段，并用历史数据验证判断是否真的提高后续行情概率。
- 三条硬底线：不造数据；不使用未来信息冒充当时信息；不允许程序静默错误。
- 缺数据→降置信度；数据冲突→标记矛盾；无法精确→给区间；无法证明→给概率判断。不再"无法百分百确认→UNKNOWN→不分析"。

## 1. 三个最终交付
1. **当前资金与筹码地图**：大盘（国家队增持/稳定/减持/不可判断、政策资金方向、公募/ETF/机构/外资方向、各主体成本区、盈亏状态）；板块（每 L2/SW2：国家队/政策参与度、机构持仓强度与变化、ETF 状态、筹码集中度、估计成本中心/成本带、价格相对成本、资金状态、行情阶段、置信度）；个股（主导资金类型、机构/大户集中趋势、估计主力成本区、距成本、锁定程度、浮筹压力、吸筹可能性/完成度、拉升准备度/活跃度、派发风险、置信度、支持证据、反证、缺失数据）。
2. 成本允许为估计区间（如 12.1–13.4 元，中心 12.7，置信度 MEDIUM-HIGH），不假装精确。
3. 每日系统：新数据→国家队/机构/ETF/ownership 更新→Market Capital Map→Sector Capital Map→全市场 Chip & Capital State→ACCUMULATION/MARKUP 状态推断→历史模型概率→当前候选→人工可读解释。日报回答 7 问（大盘资金状态/国家队在哪/哪些板块筹码健康/哪些板块吸筹或拉升准备/哪些股票成本结构有利/哪些值得观察参与/哪些强股已远离成本应避追高）。

## 2. 研究对象：潜在资金状态（Latent Capital State Inference）
隐藏状态：ACCUMULATION / ACCUMULATION_MATURE / MARKUP_READY / MARKUP_ACTIVE / DISTRIBUTION_RISK / DECLINE-FAILED。由价格成交、筹码成本分布、股东户数、机构持仓、ETF、龙虎榜、大宗、融资、板块联动、市场背景综合推断，不是单指标。

## 3. 数据体系（能拿多少用多少，不等完美）
A 行情成交：OHLC/volume/**amount/turnover_rate/free_float**（高优先补齐）/市值/复权/涨跌停停牌ST。
B 股东筹码：股东户数、户均持股、十大股东/流通股东、股东性质、持股变化、机构新进退出、集中度、香港中央结算、基金/保险/券商/QFII/社保/汇金/证金→形成 **ownership_history**（不只最新一期）。
C 机构持仓：基金季/半/年报、个股机构持仓、行业配置、增减仓、ETF 持仓/份额/申赎；区分主动/指数/ETF/保险/社保/券商/QFII。
D 国家队：**NATIONAL_TEAM_ENTITY_REGISTRY**（汇金系/证金系/国家资管/社保等已公开确认账户）；另设 **POLICY_CAPITAL_PROXY**（不能确认所有者但行为集中于政策相关宽基 ETF/指数工具）——两者不可混叫，都进判断系统。
E 交易行为：龙虎榜、机构席位、大宗、融资融券、回购、增减持、解禁、定增、股权激励、质押、调研——存在即 evidence boost。

## 4. 成本与筹码估计
1. 市场成交成本：价格×量/额 → volume-price distribution → cost_center/P25/P50/P75/major_volume_nodes。
2. 机构增仓成本：季度持股差×区间成交分布 → institution_cost_distribution（区间+概率中心）。
3. 国家队成本：公开持仓变化+ETF 资金+指数权重+区间成交成本 → national_team_cost_band（推断非流水）。
4. CHIP_LOCKING（LOW/MED/HIGH）：户数下降+机构稳定增+低位换手后缩量+成本带收敛+回调缩量+拒绝跌回旧成本区。
5. FLOATING_SUPPLY_PRESSURE：上方密集套牢+高换手+机构减+户数升+反弹放量价滞涨。

## 5. 阶段计划
- **R2-0 数据扩展**：amount/turnover/free_float/股东户数/十大流通/机构持仓/ETF/融资/龙虎榜/大宗——不等待全部完成，有多少先用。
- **R2-1 当前资金/筹码快照**（第一批交付，不等历史研究完成）：当前国家队/机构持仓估计、成本区、板块与重点股票筹码结构。
- **R2-2 历史大行情库**：五年 MARKUP_EPISODE_LIBRARY（60d+50%/120d+100%/250d+200%/3×/5×/10×），每 episode 前看 20/60/120/250 日。
- **R2-3 吸筹共性发现**：必须 matched control（同期同板块/相似市值流动性/相似前期跌幅/相似市场环境但无大行情），比较价格/成交/筹码/ownership/市场板块五组证据；回答"哪些现象真比普通股多"。
- **R2-4 发展规律**：阶段顺序、持续时间、可跳过阶段、失败模式、吸筹→拉升准备标志、吸筹假设失败标志；允许多路径（A 长期吸筹→突破 / B 快速换手→整理→突破 / C 机构增仓→缓趋势→加速 / D 政策资金→龙头→扩散）。
- **R2-5 历史验证**：HIGH confidence 后进入大行情概率是否显著高于全市场与匹配基线。
- **R2-6 概率模型+仪表盘**：规则(可解释)+统计(CatBoost/logistic/survival)双轨；目标 probability lift（如全市场 120d 翻倍 1.5% vs MARKUP_READY 12% vs +强板块+机构增仓 20%）；评价含命中概率/赔率/MAE/等待时间/失败率/regime 与板块稳定性。每日输出 Market/Sector/Stock×Capital State/Chip/Cost/Stage/Probability/Risk/Recommendation。

## 6. 状态判断与选股分类
- 证据矩阵（SUPPORT/STRONG_SUPPORT/NEUTRAL/反证/缺失）+confidence，允许错；价值判据=HIGH confidence 的概率提升。
- 分类：A 重点参与候选（ACCUMULATION_MATURE/MARKUP_READY+证据强+板块不差+未严重脱离成本）；B 观察（吸筹迹象未达准备）；C 已启动（MARKUP_ACTIVE，判断持续性/等回撤，不简单追高）；D 高风险（DISTRIBUTION_RISK）。

## 7. 与 Round 1 关系
Round 1 不删除：保留 PIT 数据基础、market regime、sector/candidate/episode 基础设施、cost proxy、Shadow runtime，作为**基础设施+风险控制组件**。Round 2 不受 Round 1"必须证明才能判断"方法论约束，成为资金行为推断+选股研究主线。Shadow 继续独立 operator-fed 运行，不阻塞 Round 2。

## 8. 成功标准
每天能给国家队/机构/板块/个股资金筹码估计；能给成本区/集中状态/阶段概率；历史证明 HIGH ACCUMULATION/MARKUP_READY 相对普通股未来大行情概率明显提升；能扫描当前市场形成重点板块/股票/优先级/建议/风险；判断允许对错与不确定，但整体必须证明"判断比不知道更有价值"。最终原则：不追求知道真相，追求"在不知道全部真相前提下，比市场平均更接近真相"。数据是侦察，价格成交是痕迹，股东机构持仓是有限情报，筹码结构是推断，吸筹拉升派发是作战判断，选股风控是决策。

---
**工程现状起点**：`data/csr8_national_capital/raw/{etf_shares,holdings,publication_dates}`（357MB，CSR-8 已收集的国家队/ETF 原始数据）可直接服务 R2-0/R2-1 国家队组件。
