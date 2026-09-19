# Progressive V1 全量分析清点与结论（2026-09-19）

- 数据源：`momentum_panel_v3`（v3_progressive_contract），2024-01～2026-09，5,191 股，971,463 事件行
- 运行：`run_progressive_analysis.py`，09-19 09:56 启动（前夜 OOM 轮重启后），13:03 干净退出，全程 3h07m，峰值 RSS 3.8G
- 口径：EOD 无成本；组间 bootstrap = **行业超额收益中位数差**（500 次，min_n=30，block=code/date 双通道）
- 本轮不回写选股逻辑；全部对照为明确组间比较

## 一、产物清点（全量闭合 ✅）

| 产物 | 规模 | 校验 |
|---|---|---|
| designs/ 24 张 CSV（3 设计 × all+7 horizon 切分） | 13G | 24/24 ✅，all==h1，行数随 horizon 单调降 ✅ |
| progressive_summary.csv | 196 行组汇总 | — |
| bootstrap_contrasts.json | 364 对照 | **113 显著**（CI 不含零） |
| strategy_episode_report(_raw).csv | 101,427 事件 | 5 类退出求和=101,427 ✅ |
| pattern_episode_report.csv | 195,586 事件 | sv 121,350 + td 74,236 ✅ |
| within_structure_contrast.csv | 池龄×周基态×周内路径 | — |
| holding_context.csv | 48M 行级持有上下文 | — |
| PROGRESSIVE_MANIFEST.json | ✅ | events=971,463 与面板行数一致 ✅ |

对账三例（精确）：①design① cohort 和 93,842+298,806=392,648=总行数；②design② 392,648+56,258+507,823=956,729；③design③ 三形态和=184,245。

## 二、核心结论

### 1. 排除逻辑是本轮最稳健的信号（design② 周频直接资格）
eligible − excluded 超额中位差全程显著且随 horizon 放大：h1 +0.068pp → h5 +0.128pp → h10 +0.362pp → h20 **+0.587pp**；7/7 horizon、all+对应 nonoverlap、code/date 双 block 全稳健。excluded 在 raw 均值与超额中位两个口径下**都是最差组**（h20 超额中位 −0.888%）——排除规则真实筛掉了差股票。

### 2. 但 observation 组超额中位数反超 eligible（口径分歧）
raw 均值：eligible(1.22%) > observation(0.68%) > excluded(0.66%)（h20）；超额中位：**observation(−0.16%) > eligible(−0.30%) > excluded(−0.89%)**，差 0.142pp 显著。eligible 的 raw 优势含行业β与右尾贡献；观察池不是垃圾池。**资格的价值应表述为"排除差者"，而非"选入优者"**。

### 3. TD 形态×周状态正交互，SV 形态负贡献（design③）
- td_legacy：eligible vs observation 显著为正（h1 +0.059 → h10 **+0.277** → h20 +0.170pp）；h20 eligible vs excluded **+0.652pp**
- sv_legacy：反向，eligible/excluded 均显著差于 observation（h1 −0.026、h2 −0.057、excluded h10 −0.169pp）
- sv+td 混合：h1/h2 显著为负

与上轮（DECISION_EVAL_20260915）"TD 独立优势是分配假象"相容：**TD 的真实价值在门控交互，不在独立触发；SV 门控无正贡献**。

### 4. 日增触发：中位/胜率有信息含量，短中期 raw 均值被左尾拖累（design①）
triggered 超额中位差 h3～h20 全显著为正（h5 +0.090 → h20 +0.287pp，nonoverlap 稳健）；胜率 h5+ 持续更高（h20 0.496 vs 0.473）；但 raw 均值 h5 反而 −0.09pp（左尾肥），h15/h20 才转正。**触发信号真实，但无尾部风控的长持有会吃掉优势**。

### 5. 策略退出原因与事件质量强相关（101,427 事件）
| end_reason | 占比 | 中位 fwd5 | 胜率 |
|---|---|---|---|
| daily_signal_inactive（善终） | 62.5% | **+0.79%** | 56.9% |
| weekly_not_eligible | 33.7% | **−1.46%** | 35.8% |
| monthly_pool_exit（中位池龄仅3天） | 3.8% | **−2.81%** | 28.5% |

资格持续本身就是选股信号：因资格丧失而结束的事件，从首触发日起收益就系统性差。

### 6. 形态事件孤立无 raw 优势
sv/td 形态事件 raw 中位 fwd5 均略负（−0.15%/−0.08%，胜率 48.3%/48.7%）——形态的价值只在与资格/池状态的交互中兑现（见 3）。

## 三、边界与风险
- 单窗口 2024-01～2026-09，无 regime 拆分（上轮教训：regime 结论窗口依赖，禁止直接晋升生产）
- 无成本口径；实盘需扣交易成本
- raw 均值 vs 超额中位的系统性分歧（结论 2、4）本身提示行业β与尾部结构主导差异，后续可做分位数展开
