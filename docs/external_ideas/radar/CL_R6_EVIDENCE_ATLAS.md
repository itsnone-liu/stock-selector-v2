# CL-R6 Evidence Atlas：A 股资金供需四轴外部证据地图（基础稿）

**用途**：CL-R6 = PRE-RESEARCH ONLY。本文档只汇编外部文献/研究证据，用于回答"哪些轴有足够外部证据与数据支持值得以后研究"，不构成任何本地分析、不产生 Regime、不形成机制结论。
**检索方式**：本会话 web_search（18 次查询），仅收录检索真实返回的来源；未能核对全文的仅按标题/摘要页/检索片段如实标注。
**可信度分级**：A = 同行评议学术期刊（金融研究、国际金融研究、中国管理科学、PBFJ、JF 等）或央行/交易所/官方智库；B = 券商研报（宏观/金工）、准学术期刊（NAFMII 等）、学位论文、官方媒体；C = 量化社区/平台博客（BigQuant、掘金、GitHub）。
**纪律对照**：外部证据映射时始终对照三条禁令（M2⇒牛市 / ETF申购⇒国家队 / 解禁⇒实际卖出）与 Episode Evidence Contract（E0/E1/E2：宏观 episode 有效自由度极小，禁止日观测回归伪装大 N）。

---

## 域 1：宏观流动性 → 股市传导（M1M2/社融）

**外部证据判断：中等偏弱——协整类学术文献样本老旧，主力证据是券商宏观/策略体系；时变性与口径断点是最大风险。**

**卡 1-1**｜海通宏观·信贷数据对 A 股的积极意义（2022-10）｜B｜[东方财富转载](https://finance.eastmoney.com/a/202210172531124364.html)、[海通研报PDF](https://www.htsec.com/jfimg/colimg/upload/20221017/65271665989801470.pdf)
- 证明（按检索可见内容）：9 月社融/信贷总量超预期、企业中长贷改善被解读为对 A 股积极；属"社融→股市"同步解读传统的代表。
- 失败/分歧：这是时点解读而非机制验证；未处理社融数据的事后修订。
- PIT 启示：社融是月度、发布滞后且历史上有口径调整与修订 → vintage vs latest-revised 必须区分，2020 年当时市场看到的值 ≠ 现在数据库里的值。
- 轴映射：**Funding**（定义轴，不是 outcome）。

**卡 1-2**｜广发宏观·剩余流动性与资产表现｜B｜[原文（微信）](https://mp.weixin.qq.com/s?__biz=MjM5NDA1OTQ5NQ==&mid=2653042570&idx=2&sn=95605cbd4cf4f974231cc82910510477)
- 证明：以"剩余流动性"（货币增速相对名义增长之差）框架讨论资产表现，是 A 股策略圈最常用的宏观流动性代理。
- 失败/分歧：该类框架本质是"M2−名义GDP"复合指标，直接从它跳到"牛市"即踩我们第一条禁令（M2⇒牛市）。
- PIT 启示：复合指标的分母（名义 GDP）本身大幅修订，可回溯 vintage 几乎不可得。
- 轴映射：**Funding**。

**卡 1-3**｜李迅雷·货币政策对股市的影响趋弱（2017）｜B｜[原文](https://economy.china.com/news/11173316/20170907/31309061_3.html)
- 证明（标题即结论）：货币宽松对股市的传导在减弱——**时变性/状态依赖的直接证据**。
- 失败/分歧：观点文章，无严格计量；但方向与学术文献"相关关系不稳定"一致。
- PIT 启示：任何用全样本估计的 Funding→权益系数都隐含"传导强度恒定"假设，外部证据不支持。
- 轴映射：**Funding**（时变性风险来源）。

**卡 1-4**｜同花顺股指专题·货币、信用与股票指数周期研究（2026-06）｜B｜[原文](https://stock.10jqka.com.cn/20260612/c677432258.shtml)
- 证明（检索片段给出具体数字）：2022/05 以来"宽货币、紧信用"组合下上证50 仅 +4.52%、沪深300 +18.52%、中证500 +41.87%、中证1000 更高——货币×信用状态对规模风格有强条件效应。
- 失败/分歧：单一样本期（2022-2026）驱动，正是 Episode Evidence Contract 警告的"单一特殊时期"风险。
- PIT 启示：货币-信用二分状态本身可机械构造，但"四象限→风格"映射跨期不稳。
- 轴映射：**Funding**（状态定义）→ EquityFlow/Absorption 的条件变量。

**卡 1-5**｜华泰·新口径货币供应量的风格轮动择时策略｜B｜[原文（新浪研报页）](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/794160803497/index.phtml)；知网老一代协整研究（存在性证据）：《[我国货币供应量与股市价格关联性的实证研究](https://www.cnki.com.cn/Article/CJFDTotal-JJWT201210019.htm)》（2012）、《[货币供应周期对股市波动周期影响的实证研究](https://www.cnki.com.cn/Article/CJFDTotal-ZQQH201202010.htm)》（2012）｜A（期刊，样本止于 2010 年代初）
- 证明：华泰报告处理 2024 年 M1 统计口径调整（新口径纳入个人活期与备付金）并重建择时序列；知网两篇是"M1/M2 与股指协整"的老一代范式。
- 失败/分歧：老协整文献样本均止于 2010 年前后，之后金融脱媒、利率市场化、口径调整多次打断序列；华泰报告本身承认需要"新口径"重建。
- PIT 启示：**M1 口径 2024 断点是 G0 Data Source Census 的必检项**（单位/定义断点栏）。
- 轴映射：**Funding**。

---

## 域 2：Credit Impulse（信用脉冲）在中国的应用

**外部证据判断：薄弱——检索未发现严格同行评议的中国信用脉冲实证论文；证据几乎全部由券商宏观方法论承载（B 级）。**

**卡 2-1**｜广发宏观·广义信贷脉冲与利率周期｜B｜[原文（新浪研报页）](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/675827538719/index.phtml)
- 证明：系统构造中国"广义信贷脉冲"（新增信贷流量占 GDP 比重的变化），刻画其与利率周期的关系——信用脉冲在华主流定义来源之一。
- 失败/分歧：方法论报告，无 OOS 检验；分母用名义 GDP 同样引入修订问题。
- 轴映射：**Funding**（信用维度核心候选原子量）。

**卡 2-2**｜中信建投·长期信贷脉冲有领先意义（宏观变量与资产价格系列）｜B｜[智通财经](https://www.zhitongcaijing.com/content/detail/971349.html)、[新浪研报页](https://stock.finance.sina.com.cn/stock/view/paper.php?symbol=sh000001&reportid=744613361821&autocallup=no&isfromsina=no)
- 证明（按标题与转载）：声称长期（低频）信贷脉冲对风险资产有领先意义，并给出当期配置观点。
- 失败/分歧：结论以个位数"宽信用周期"episode 为基础，样本极小；且是行情判断（会话内无法核实其事后对错），不能当机制复现。
- PIT 启示：信用脉冲 = 社融/信贷流量二阶变换，月度、修订频繁 → episode 级有效自由度（≈108 个月甚至更少）直接封顶可检验强度。
- 轴映射：**Funding**。

**卡 2-3**｜中金·主题策略：捕捉资产轮动的高阶信号｜B｜[原文（新浪研报页）](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/674011506225/index.phtml)；新时代宏观·[从信贷脉冲看经济](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/632829050951/index.phtml)｜B
- 证明：把信贷脉冲类变量作为资产轮动"高阶信号"的体系化用法（中金）；新时代宏观用于经济领先判断。
- 失败/分歧：全部为卖方框架；**学术级验证缺位是本域最大空白**（检索多轮未命中知网/PBFJ 级中国信用脉冲论文——如后续有人工检索知网条件，值得补查）。
- 轴映射：**Funding**。

---

## 域 3：ETF 资金流对成分股流动性/价格效率的影响

**外部证据判断：较扎实——有国际期刊 + 国内博士论文 + 准学术期刊 + 卖方系统研究，多层次证据；但"效率改善 vs 崩盘风险"方向分歧真实存在。**

**卡 3-1**｜吴偎立、朱菲菲（中央财经大学）·ETF ownership and informational efficiency of underlying stocks: Evidence from China，Pacific-Basin Finance Journal（2023）｜A｜[ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X23000719)、[SSRN 4142034](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4142034)、[作者主页介绍](https://sf.cufe.edu.cn/info/1157/13016.htm)
- 证明（严格按可核对内容）：用中国数据检验 ETF 持股对成分股信息效率的影响；作者为高校学者、发表国际期刊。具体方向性系数未在检索片段中展示，**引用前须下载原文核对**。
- 失败/分歧：同作者团队另有 [Wu & Zhou：ETF ownership and stock price crash risk: evidence from China](https://www.semanticscholar.org/paper/ETF-ownership-and-stock-price-crash-risk%3A-evidence-Wu-Zhou/1cba7e3d35f9e293e534a126a5e67a836089b97f)——ETF 持股的另一面（崩盘风险）。
- PIT 启示：ETF 申赎/份额数据 T 日发生、确认与公布滞后 → EquityFlow 原子量的 available_at 必须逐字段核。
- 轴映射：**EquityFlow**（主）× **Absorption**（效率后果）。

**卡 3-2**｜《资本市场开放对股价同步性的影响：ETF 纳入互联互通的视角》，《金融市场监管研究》2024 年第 1 期（NAFMII 主管期刊）｜A-｜[PDF](https://www.nafmii.org.cn/yj/jrscyj/qk/2024/20240101/202402/P020250324514969802270.pdf)
- 证明：以 ETF 纳入互联互通为准自然实验，检验 ETF 渠道对股价同步性的影响。
- 失败/分歧：准官方期刊，审稿标准弱于顶刊；结论适用范围受互联互通标的限制。
- 轴映射：**EquityFlow** → **Absorption**（同涨同跌程度）。

**卡 3-3**｜华泰·后明星时代公募基金研究系列之二：ETF 规模的大发展如何影响资本市场？｜B｜[原文（新浪研报页）](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/11/rptid/787011239621/index.phtml)；中金·[“被动化”趋势下的量化投资](https://www.163.com/dy/article/JOTK3TLR05568W0A.html)（2024）｜B
- 证明：卖方系统梳理 ETF 扩容对市场微观结构（流动性、定价、风格）的影响路径。
- 失败/分歧：叙述性框架为主，无因果识别；且卖方有自身 ETF 业务立场。
- 轴映射：**EquityFlow**。
- 禁令对照：所有来源均无"ETF 净申购⇒国家队"的合法推断路径——申购主体不可从公开申赎数据识别，该禁令与数据现实一致。

**卡 3-4**｜博士论文·ETF 投资活动对我国股票市场运行质量影响研究（知网 CDFD，2026）｜B｜[知网镜像页](http://cnkimirror.clcn.net.cn/KCMS/detail/detail.aspx?filename=1025200684.nh&dbcode=CDFD&dbname=CDFD2026)
- 证明：以"市场运行质量"（流动性/波动/效率）为对象系统研究中国 ETF 投资活动——存在性证据，说明该问题在国内已有成体系学位论文。
- 失败/分歧：学位论文可信度低于期刊；未见结论细节。
- 轴映射：**EquityFlow**×**Absorption**。

---

## 域 4：融资融券（margin）对 A 股的作用与状态依赖

**外部证据判断：较扎实（设计质量高）——顶刊 + 自然实验设计；但"抑制波动 vs 放大波动"两派并存，恰说明效应是状态依赖的。**

**卡 4-1**｜王永钦 等·杠杆、信息与流动性：融资融券对股票流动性的非对称影响，《金融研究》2026 年第 3 期｜A｜[期刊页](http://www.jryj.org.cn/CN/Y2026/V549/I3/151)、[复旦经济学院转载](https://econ.fudan.edu.cn/info/1236/41647.htm)
- 证明（按标题与转载信息）：区分融资与融券两条渠道，论证其对个股流动性的**非对称**影响，机制桥为"杠杆×信息"。
- 失败/分歧：结论是"非对称/条件效应"而非单向改善——margin 对市场质量的作用依赖杠杆方向与信息环境。
- PIT 启示：两融余额/买入额 T 日盘后披露（T+1 早间可得）→ EquityFlow 两融原子量 PIT 可行性高，但标的池多次扩容是定义断点。
- 轴映射：**EquityFlow**（杠杆资金子轴）。

**卡 4-2**｜《融资融券渐进式扩容的政策效应研究——基于多期 DID 模型与 Hausman 的检验》，《国际金融研究》2016 年第 5 期（被引 34+）｜A｜[知网页](https://wap-cnki-net-443.webvpn.imac.edu.cn/touch/web/Journal/Article/GJJR201605008.html)
- 证明：利用两融标的分批扩容构造多期 DID，识别两融制度对标的股票的政策效应——该域识别设计的标杆。
- 失败/分歧：DID 估计的是扩容事件的平均处理效应，外推到"存量两融余额状态→市场"链条需另证。
- 轴映射：**EquityFlow**。

**卡 4-3**｜方意·P2P 借贷市场与股票市场间的溢出机制：中国股市 2015 年异常波动期间的证据｜A｜[央财学院转载](https://sf.cufe.edu.cn/info/1228/11070.htm)；《融资交易、杠杆牛市与股灾危机》（2016，据检索编码为《统计与决策》，需核）｜[检索页](https://search.napstic.cn/literature/periodical/010tongjyj201611006)
- 证明：2015 加杠杆—崩盘 episode 中，场外加杠杆资金与股市之间的溢出机制有数据支持——**margin 效应强状态依赖**（平静期 vs 杠杆牛末期）的典型案例。
- 失败/分歧：单 episode 证据，按 E0/E1/E2 只能支持 E1（descriptive），不可当跨期恒定机制。
- 轴映射：**EquityFlow**；对**Absorption** 有条件外溢含义。
- 禁令对照：杠杆资金"撤退"在 2015 episode 有公开数据痕迹，但那是极端期特例，不得外推为常态指标。

**卡 4-4**｜清华五道口/PBCSF 研讨会综述·从真实数据看本轮股市异常波动风险传导机制｜A-（官方智库）｜[原文](https://www.pbcsf.tsinghua.edu.cn/info/1154/4086.htm)；万方收录《[融资融券能否抑制我国股市波动](https://d.wanfangdata.com.cn/periodical/shangygc202603024)》（2026，一般期刊）
- 证明：监管侧对杠杆资金传导链条的数据复盘；后者标题直接呈现"能否抑制"之争。
- 失败/分歧：正反两派文献并存——设计差异（标的扩容 DID vs 2015 episode 研究）对应不同状态区间，综合读法是**条件效应**而非恒定符号。
- 轴映射：**EquityFlow**。

---

## 域 5：解禁 / IPO / 再融资供给对流动性与波动的影响

**外部证据判断：公司/事件层面中等偏扎实（公告效应文献丰富），市场层面（解禁总量→大盘）证据薄弱；"解禁⇒实际卖出"越界推断正是文献明确反对的。**

**卡 5-1**｜《限售股解禁、资本运作与股价崩盘风险》，《金融研究》（年份待核，官网摘要页可查）｜A｜[期刊摘要页](http://www.jryj.org.cn/EN/abstract/abstract12.shtml)、[PDF](http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=12)
- 证明（按检索可见表格）：事件研究设计——比较"减持前有资本运作"与"无资本运作"样本的 CAR 差异，把解禁—资本运作—崩盘风险串成公司层面链条。
- 失败/分歧：公司层面公告效应 ≠ 市场层面流动性冲击；样本期较老，减持规则（2017 减持新规等）已多次改变行为。
- 轴映射：**Supply**。

**卡 5-2**｜《股东为什么在解禁后会减持股票？——基于背景风险分析的股票解禁效应研究》，《中国管理科学》2018 年第 7 期｜A｜[期刊页](https://www.zgglkx.com/CN/10.16381/j.cnki.issn1003-207x.2018.07.002)
- 证明：解禁后是否减持由股东背景风险等异质性因素决定——**解禁日历与实际卖出行为是两件事**，解禁只是解除约束而非行为本身。
- 失败/分歧：行为异质性大，解禁规模对实际抛压的映射不稳定。
- 禁令对照：这条文献直接支持我们的禁令三（解禁⇒实际卖出不成立）；Supply 轴应把"解禁日历（事前已知）"与"减持公告（事后披露）"作为两个不同 PIT 属性的原子量。
- 轴映射：**Supply**。

**卡 5-3**｜谢德仁 等·上市公司"高送转"与内部人股票减持：“谋定后动”｜A｜[清华 PBC 工作论文 PDF](http://cfrc.pbcsf.tsinghua.edu.cn/__local/F/06/34/E4115369D12D963015BBAFDB92C_E24F7E06_130198.pdf)
- 证明：公司资本运作（高送转）与内部人减持在时序上系统配合——供给行为有"配合出货"维度，非随机。
- 轴映射：**Supply**。

**卡 5-4**｜中金量化事件月报·哪些因素影响限售股解禁期表现？（2018-12）｜B｜[BigQuant 转载](https://bigquant.com/wiki/doc/9TrkvC0hV5)；招商证券·[历史上解禁高峰前后市场表现如何？](https://m.cls.cn/detail/763013)｜B
- 证明：对解禁期个股表现与市场解禁高峰复盘——量化事件研究传统的代表。
- 失败/分歧：此类复盘常发现解禁总量对大盘指数的冲击弱于直觉（事前已知信息被提前消化），与公司层面显著公告效应并存 → "Supply 冲击"更可能是结构/个股层面而非总量层面。
- PIT 启示：解禁日历在上市/定增时即确定、事前完全已知 → 天然 PIT 干净（历史 T 时点已知的解禁 vs 回看最终记录差异小），是 Supply 轴 G0 最可能通过的数据。
- 轴映射：**Supply**。

**卡 5-5**｜华创策略·大型 IPO 是否会对股市形成抽血效应——策略周聚焦｜B｜[原文（新浪研报页）](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/836617920211/index.phtml)；武汉大学学位论文·[定向增发短期公告效应以及股价长期表现的实证分析](https://openir.whu.edu.cn/AchievementDetail/degree_12ea0b77-f16f-4e0e-8330-f7296521e0c4)｜B
- 证明：把"IPO/再融资抽血"作为可检验问题而非教条；定增公告效应+长期表现的学位论文级证据。
- 失败/分歧：IPO 节奏是政策变量（历史上多次暂停/收紧），与市场状态内生相关——供给冲击识别天然困难。
- 轴映射：**Supply**（IPO/再融资原子量）。

---

## 域 6：2024 后资本市场专项工具（互换便利 SFISF、回购增持再贷款）

**外部证据判断：最薄弱——工具 2024-10 才创设，检索全部命中为官方媒体 + 券商点评，零学术实证；episode 数≈1-2，天然 E0 域。**

**卡 6-1**｜财联社·互换便利工具的 Q&A｜B+（官方细则转述）｜[原文](https://www.cls.cn/detail/1821496)
- 证明：工具机制的权威事实源——"以券换券"（债券/股票ETF/沪深300成分股 换入国债/央票，只能用于融资增持股票）、首期额度、招标方式等制度细节。
- 轴映射：**EquityFlow**（政策性入市资金）× **Funding**（央行流动性渠道）。

**卡 6-2**｜券商细则点评三篇（2024-10）｜B｜[非银·互换便利细则点评：鼓励券商加大权益投资](https://data.eastmoney.com/report/zw_industry.jshtml?infocode=AP202410201640374011)、[证券行业互换便利政策的三重影响：夯实底部，储备空间，强化弹性](https://data.eastmoney.com/report/zw_industry.jshtml?infocode=AP202410201640374556)、[央行SFISF助力红利价值重估（新浪研报页）](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/782217285694/index.phtml)
- 证明（按标题与摘要）：机制解读（非银互换扩表）、工具对高股息资产的定向影响假说、"底部支撑/弹性储备"的功能定位。
- 失败/分歧：全部为事前点评，无事后效果检验；对"利好哪类资产"的判断属预测而非证据。
- PIT 启示：SFISF 实际操作量只有央行公告频率的披露 → EquityFlow 原子量粒度=事件级，无法支持日度状态构造。
- 轴映射：**EquityFlow**（政策性子轴）。

**卡 6-3**｜官方媒体周年综述｜B｜上证报·[互换便利项下股票配置引猜想，机构预计高股息资产成首选](https://www.cnstock.com/commonDetail/287290)（2024-10）；人民网·[两项货币政策工具落地满一年，长钱入市增强资本市场内在稳定性](http://finance.people.com.cn/n1/2025/1119/c1004-40607000.html)（2025-11）；经济参考报·[同题](https://finance.china.com.cn/news/20251020/6272819.shtml)（2025-10）；经济网·[落地逾7个月，两项新工具有何进展？](https://www.ceweekly.cn/news/important/2025/0529/474375.html)（2025-05）
- 证明：工具落地的规模/进展数据（官方口径）与"增强稳定性"的官方定性——**可用的只有这类进程性事实**。
- 失败/分歧：官方定性不是可检验结论；"稳定性增强"无对照、无反事实。
- 结论：本域按 Episode Evidence Contract 属 **E0（INSUFFICIENT_SUPPORT）**——episode 太少、available_at 粒度太粗，未来若有学术检验出现再升级。
- 轴映射：**EquityFlow**（政策性资金）→ **Absorption**（假想的稳定性后果，未证）。

---

## 域 7：市场 breadth / 吸收能力类指标

**外部证据判断：概念有国际理论但构念效度本身有争议；A 股本土证据以卖方金工"扩散指标"与社区实践为主（B/C 级），学术空白——正是内部 R5-λ 之类自有研究要补的位置。**

**卡 7-1**｜Chen, Hong & Stein·Breadth of Ownership and Stock Returns，JFE 66（2002）｜A｜[引用文献 PDF（FMA 会议稿）](https://www.fmaconferences.org/Atlanta2022/Papers/Kim__Correlated_Demand_Shocks_.pdf)
- 证明：持股广度（ownership breadth）下降预示后续负收益，机制为卖空约束下的悲观者离场。
- 失败/分歧：这是"持股广度"非"涨跌家数广度"；NBER 后续工作论文 [What Does Stock Ownership Breadth Measure?（w16591, 2010）](https://www.nber.org/papers/w16591) 直接质疑该指标测的是"隐藏负面信息"还是"情绪"——**breadth 类指标的构念效度争议本身就是文献的一部分**。
- PIT 启示：与我们"同痕异因"防线同构——同一 breadth 痕迹可由完全不同机制产生，指标不得直接贴机制标签。
- 轴映射：**Absorption**。

**卡 7-2**｜Herding for Profits: Market Breadth and the Cross-Section of Global Equity Returns（Economic Modelling）｜A｜[检索页](https://searchworks.stanford.edu/articles/edsair__edsair.doi...........d856555950434c5c689f8b15df65c8b2)
- 证明：跨市场检验市场宽度（涨跌参与度）与股票截面收益的关系，机制为 herding。
- 失败/分歧：全球样本为主，A 股特定结构（涨跌停、退市少）未必适用。
- 轴映射：**Absorption**。

**卡 7-3**｜东北证券金工·扩散指标择时研究之一：基本用法（2019-09）｜B｜[BigQuant 转载](https://mf.bigquant.com/wiki/doc/35HqU6qPtI)
- 证明：A 股"扩散指标"（上涨个股占比类宽度的平滑/阈值化）择时的规范化用法——国内 breadth 研究的主力形态是金工择时报告。
- 失败/分歧：择时信号阈值化后过拟合风险高；发布方为卖方，回测独立复现缺失（与我们"作者回测=作者事实"纪律一致）。
- PIT 启示：宽度类指标由全市场截面行情即时可算，PIT 干净——但正交性契约要求每实验前声明它是 **state constructor 还是 outcome**，禁两边同用（"高 breadth 状态未来 breadth 更高"是机械自证）。
- 轴映射：**Absorption**（主）。

**卡 7-4**｜社区/平台实践｜C｜BigQuant·[基于市场存量状态择时的小市值策略](https://bigquant.com/wiki/doc/wakLPy74aD)、掘金·[市场宽度指标 Python 实现](https://juejin.cn/post/7548714406729875496)、GitHub·[a-share-market-breadth skill](https://raw.githubusercontent.com/aifinlab/FinClaw/refs/heads/main/skills/a-share-market-breadth/SKILL.md)
- 证明：宽度指标（涨跌家数、新高新低、站上均线比例等）的工程实现与策略化实践存在且成熟。
- 失败/分歧：无同行评议、无样本外纪律声明；只可作指标构造参考，不可作证据。
- 轴映射：**Absorption**。

**卡 7-5**｜吸收能力近邻方法：Pacific-Basin Finance Journal·Unlocking the True Price Impact: Intraday Liquidity and Expected Return in China's Stock Market（2025）｜A｜[ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25002768)；广发宏观·[抱团的宏观规律](https://stock.finance.sina.com.cn/stock/view/paper.php?symbol=sh000001&reportid=832253504493&autocallup=no&isfromsina=no)｜B
- 证明：中国市场日内价格冲击与流动性定价的最新学术证据（价格冲击 = 吸收能力反面）；广发报告从宏观侧解释宽度退化/抱团。
- 失败/分歧：价格冲击指标依赖高频数据可得性；与内部 R5-λ（推进效率）高度近邻，外部增量有限（Q6 检验点）。
- 轴映射：**Absorption**。

---

## 汇总：外部证据强度分级

| 域 | 强度 | 证据类型结构 | 关键分歧/风险 | 对 R6 的含义 |
|---|---|---|---|---|
| 3 ETF 资金流 | **较扎实** | A 级国际期刊 + 博士论文 + 准学术 + B 级卖方 | "效率改善"vs"崩盘风险"两支并存；申赎主体不可识别 | EquityFlow 轴外部支持最强；ETF flow→成分股微观后果链有文献背书 |
| 4 融资融券 | **较扎实** | A 级顶刊 ×2 + 官方智库 + episode 研究 | 抑制 vs 放大波动两派并存 = 状态依赖 | EquityFlow 杠杆子轴可立；效应必须条件化（杠杆水平×信息环境） |
| 5 解禁/IPO/再融资 | **中等**（公司层）/**薄弱**（市场层） | A 级公司层事件研究多；市场层仅 B 级复盘 | 解禁≠实际卖出（文献直接证实）；IPO 节奏政策内生 | Supply 轴解禁日历 PIT 干净可立；"供给冲击→大盘"链条缺外部证据 |
| 1 宏观流动性 | **中等偏弱** | 老协整文献（A 但样本旧）+ B 级研报体系 | 传导时变性强（李迅雷 2017）；M1 口径 2024 断点 | Funding 轴可用但必须 vintage-aware + 口径断点处理 |
| 2 Credit Impulse | **薄弱** | 几乎全为 B 级券商方法论 | 学术验证缺位；episode 有效自由度极小 | Funding 轴信用维度：只能作 E1 级候选，先过 G0 |
| 7 Breadth/Absorption | **薄弱（本土）** | 国际 A 级理论（但构念效度有争议）+ B/C 级本土 | 同痕异因（信息 vs 情绪）；择时报告过拟合 | Absorption 轴外部证据不足以直接借指标，需自有识别（正交性契约） |
| 6 SFISF/再贷款 | **最薄弱** | 官方媒体进程性事实 + 券商事前点评 | 零学术实证；episode≈1-2；披露粒度=事件级 | 天然 E0 域，只进观察清单不进机制验证 |

**三个横向结论**：
1. **传导链整体（Funding→EquityFlow→Supply/Absorption）没有任何外部文献做过链式检验**——所有证据都是 pairwise（单环节），且各自样本期、频率、识别设计互不兼容。外部证据只能支持"单环节有先例"，不能支持"链条成立"。
2. **质量最好的证据（域 3/4）集中在微观公司/标的层面，而我们的状态轴是市场层面**——微观结论向总量状态外推本身就是外部文献没做过的事，E1 是本阶段可声明的上限。
3. **三条禁令与文献现实一致**：M2⇒牛市被"影响趋弱"类证据削弱；ETF申购⇒国家队无数据路径；解禁⇒实际卖出被《中国管理科学》2018 直接证伪。禁令不是保守，是外部证据的要求。

**检索局限声明**：①仅用 web_search，无法下载多数付费全文，"作者真正证明的结果"栏凡未能核对全文处均已标注"按标题/摘要/片段"；②知网直接命中以老文献为主，2020 年后国内顶刊（金融研究/经济研究）新文献可能因检索方式遗漏，建议后续用知网/万方人工补检域 1/2/7；③域 6 无任何学术来源不是检索失误，是工具太新的事实。

（本稿为 CL_R6_EVIDENCE_ATLAS.md 基础稿，检索来源均为 web_search 真实返回，可信度分级见文首。）
