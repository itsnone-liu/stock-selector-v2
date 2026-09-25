# T7 Synthesis：REDUCE 后资本再扩张——已成立 / 被否定 / 仍开放

> 收束 T7.0–T7.4 全部冻结结论。数字全部来自冻结产物（`t7_*_report_data.json` /
> 冻结 parquet，本文件零新计算）。冻结链：T7.0 `0e7f513` / T7.1 `63b5668` /
> T7.2 `c2795d7` / Design `1212c65` / Amendment Freeze `4a08d9e` / T7.3 `d6b9a48`
> / Taxonomy Freeze `3067d22` / T7.4 `8bdb6a2`。

## 0. T7 的原始问题与预注册结构

用户核心问题："发生 REDUCE 以后，什么情况下值得重新承担风险，什么情况下宁可
放弃后续上涨也不应该 ADD？"——研究 **False ADD Cost ↔ Missed Recovery Cost 的
交换结构**，非预测模型。分段纪律：DEV 可发现 → Freeze 人选 → VAL 验证（失败
记 NOT_VALIDATED 禁回 DEV）→ CONF 二次验证。T7 完整走通该管线一次，C1 是
第一个完整案例。

## 1. 已成立（validated / established）

1. **恢复生命周期非常快**（T6.2+T7.3 双源）：REDUCE→ADD 中位约 2 天；
   VAL 的 True Recovery establishment：median=R+3、p25=R+2、p75=R+3、
   P(est≤R+3)=77.5%。A 的 wret_R40=+2.08%；随延迟增加总体恶化，
   B1/B2 仍为正（+1.95%/+0.40%），B3/B5 及 C1/C2 转负。
2. **假恢复快速显形**（T6.2/T6.3+T7.4 witness）：frozen failure condition
   的时钟域全部在 A0 后 ≤5 个有效 observation（6,953/6,953，max offset=5，
   G34 全量 witness）。等待的"信息价值窗口"很小——要么很快破位要么撑过去。
3. **TrueRecovery 结构**（T7.0）：ref20 修复+non-severe 区域+K=5 persistence；
   9,463/31,260=30.3%。
4. **DEV separator association 真实但不可执行**（T7.2+T7.3 联合）：
   max_bounce_R5 在 DEV 上 FR hi−lo=−0.299（双 cluster Holm×2，hi FR 32.3%
   vs lo 62.1%）——association 成立；但转成 R+5 confirmation policy 后
   在 VAL 上两端皆失（见 §2）。
5. **F6 残差的本质**（T7.4）：79.16% 为盈利类（GOOD 6,941+PAINFUL_WIN 1,161），
   F6 不是"尚未解释的失败集合"而是"现有 failure taxonomy 没有理由判成失败"
   的大本营。1,698 observed-end-loss 中 D1 振荡形态占 75.9%（morphology
   decomposition，非因果）。
6. **方法论元结论（T7 最重要产出之一）**：一个事后具有很强区分力的路径特征
   **不等于**一个可执行的确认信号——**信息出现的时间本身就是策略价值的
   一部分**。这是 C1 完整案例（DEV 发现→Freeze→VAL 否定）的直接教训。

## 2. 被否定（falsified）

1. **C1（R+5 bounce confirmation，primary amendment candidate）**：
   VAL false_add_rate 17.47% vs A 16.16%（风险端未降反升 +1.31pp）、
   TR missed 82.23% vs 12.08%、wret −0.32% vs +2.08%。**NOT VALIDATED**，
   无 CONF 二次机会（段协议）。
2. **C2（q2 sensitivity）**：一致更差（21.13% / 89.60%）。
3. **B family 全曲线**：延迟不等价于安全——false ADD 不随等待下降
   （16.16%→17.6% 附近），missed 单调恶化（12%→85%），wret 单调走负。
   "多等几天确认得更清楚"在数据上不成立。
4. **D family（hot-bounce veto 方向）**：DEV 证据方向相反（高 bounce 组 FR
   最低 32.3%）；Freeze 时 D 留空，空 family 本身是研究结果。
5. **"既安全又少赚"的折中幻觉**：C1 在 VAL 上**既没有降低 False ADD 又付出
   巨大 recovery opportunity cost**——不是 risk-return 交换上的保守点，而是
   双输点。

## 3. 仍开放（open）

1. **re-risk order / recycling count（T7.3+T7.4 联合暴露的下一阶段候选）**：
   第一次 re-expansion 必须足够及时（est median=R+3），但**第一次之后是否还
   应该允许反复重新扩张风险是另一个问题**——endpoint-loss 中 75.9% 呈 ≥3 次
   ADD 的 repeated recycling（形态非因果）。正确问题形态：
   "REDUCE→第一次 re-expansion→（成功？维持 ：再次 REDUCE→第二/三次
   re-risk）的边际收益是否还值得"。**候选新研究，非政策结论，不得从 D1
   反推**。
2. **slow-grind 形态**（T7.4 D3）：structurally untestable——当前 R+40
   horizon 无法检验 ≥60 日 taxonomy（max span=41）。需要更长观察窗的 fact
   layer 扩展才能变成可检验问题。
3. **迟发假恢复**（T7.4 D2）：observed structural zero **under the frozen
   definition and R+40 horizon**——更长 horizon 下 >5 日版本是否存在未检验。
4. **VAL 后段换手反转**（T7.1 压力测试记录）：clean>FR 的 R+5 后结构差异
   是已知验证环境特性，未用于也未解释任何 policy 规则。
5. **sector QUASI-PIT sidecar**（T7.0）：冻结未用（EXPLORATORY，禁入 C/D/
   primary）——板块同步修复 vs 个股独立反弹的结局差仍是未打开的描述性问题。
6. **2D frontier 的扩展呈现**：A vs C1 只是一对；frontier 坐标（false-ADD
   风险 × recovery upside）已有全部数据，未来任何新 policy 家族（如 re-risk
   order 类）应直接在 frontier 上报告而非单轴。

## 4. 对 T7 原始问题的回答现状

"什么情况下值得重新承担风险？"——T7 结束时的**部分**回答：

- **当前支持**：不应为了等待 R+5 confirmation 而系统性延迟 frozen A
  policy 的及时 re-expansion；恢复建立本身很快（est median=R+3）。
- **不值得**：为"确认"而等待到 R+5 之后（错过 82% 的恢复建立点，且风险
  不降）；以 bounce 强度为过滤条件（区分力不转化为可执行性）。
- **未回答**：第一次、第二次、第三次 re-risk 的边际价值是否递减，以及
  哪些 re-risk 值得执行（§3.1）——这是 T7 留下的结构最清晰的新问题。

## 5. 纪律层收束（对后续项目的可复用结论）

- 分段纪律（DEV 发现→Freeze→VAL→NOT_VALIDATED 禁回选）完整走通；Freeze
  早于任何 VAL 产物（git 时序可验）是 blind validation 可审计性的前提。
- Policy design ≠ discovery：非对称成本决定规则形态，机械 candidate 不自动
  变规则（C1 的 C 表达、D 留空、C2 永不升 primary 均按此拍板）。
- Gate 体系演进（G20-G34）：描述纪律（G20）→防污染（G22 产物 segment+计算
  路径扫描）→守恒（G25 反事实全等）→双 clock（G26/G29 feature-decision
  identity）→sizing 继承（G27）→taxonomy 溯源与结构零 witness（G34）。
  "gate 自身也要被审计"贯穿全程（G24 首版语义混乱、G34 首版名实不符均被
  用户审计抓住）。
- 结构零的三种性质要分开报：observed structural zero（D2）/
  structurally untestable（D3）/taxonomy 结构零（T6.3 F2）——均为"当前定义
  与 horizon 下"的陈述，不外推。
