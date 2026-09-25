# T8 Synthesis：第 N 次 Re-risk 的边际价值——成立 / 否定 / 开放

> 纯 synthesis：零新统计，数字全部来自冻结产物。链：T8 Plan v2 `91924c5` →
> T8.0 `a5a8cf9` → T8.0-R1 `5e1b555` → T8.1 `28fe5d6` → T8.1-R1 `42e23d3` →
> T8.2 `b579b80` → T8.2-R1 `94261a6`（全 FROZEN）。
> Provenance：T7 synthesis 暴露的 open question——非 T7.4 D1 派生。

## 1. 成立（established）

1. **Sequence Fact Layer**（T8.0）：31,260 冻结 cycles 全量重构，competing
   path（无 ADD 的 REDUCE cycle，15,614）完整保留——"停止下注"的一半在表；
   k 分布 k1=10,125 / k2=3,723 / k3+=1,798（固定三组主分析，无数据依赖
   规则）。
2. **边际 order anatomy**（T8.1 描述 + T8.2 primary=VAL+CONF pooled、双
   cluster、Holm 确认）：随 re-risk order 增加——
   - False ADD **≈ flat**（三 contrast 全 ns）；
   - Recovery **↓**（k1vsk3+ **+9.95pp**，CI [7.18, 12.76]）；
   - DD **worsening**（k1vsk3+ +1.15pp***）；realized return / contribution
   **↓**（递减集中早期：k1vsk2 显著、k2vsk3+ ns）；**MFE median ≈ flat**。
3. **Conditional structure（描述层）**（T8.2）：k2→k3+ association 的观测
   模式随 outcome₁ stratum 而异——FR stratum（ADD₁ 假恢复；1,686/931）
   内 recovery/dd/mfe/ret/contrib **五指标 Holm 后一致显著**；CYCLE_OK
   stratum（=true_recovery₁ AND NOT false_recovery₁；1,631/750）内**未出现
   同型跨指标一致恶化**（MFE 反向显著）。非 interaction 证明。
4. **时钟语义**：re_reduce_day（REDUCE 动作日）≠ next_r0_day（下一 cycle
   确认锚）——nan-pattern 逐位同、间隔中位 1 天/最大 27 天；cycle 生命期
   用 frozen 动作日。
5. **方法论**：estimand A/B 分层纪律（observed profile vs conditional
   contrast，禁因果词）+ G40 守恒（competing path 不消失）+ G42 全量
   15,646 replay + G47 Holm 全族重放——全部实际走通。

## 2. 否定（falsified / 无证据基础）

1. **"越加越容易错"**（k↑ → False ADD↑）：三对比全 ns，分层内也不升；
2. **统一"第 N 次停止 ADD"次数门**：同样 k3+ 在 FR stratum 内多指标一致
   更差、CYCLE_OK stratum 内无同型模式——纯计数器规则无数据基础；
3. **"order 已被证明具有独立信息"**：粗粒度 outcome₁ 条件化后梯度残留
   ≠独立信息（未控制 path selection 大量存在）——未决解释，非结论；
4. **正式 effect modification**：interaction contrast 未预注册未检验——
   "一 stratum 显著另一不显著"不构成证明；
5. **因果性"第 k 次 ADD 导致更差"**：Estimand B 是 conditional
   association，risk set 在选择路径上。

## 3. 开放（open）

1. **剩余 gradient 的来源**：order 本身 vs outcome₁ 三分类未捕获的更细
   prior-path state——T8 无法区分；
2. **decision-time PIT 状态变量**：在下一次 ADD 决策时点，哪些可观测
   （无前视）路径状态能表达这种 prior-path deterioration——**未研究**；
3. **policy 可转化性**：conditional structure 能否转化为真正改善风险—
   机会成本 frontier 的 policy——须条件门后完整 Design→Freeze→VAL。

## 4. 对 T8 原始问题的回答现状

"及时 re-expansion 很重要，但 repeated re-risk 是否仍具有相同的风险收益
结构？"——回答：**不相同，且差异的形态出乎预注册直觉**。错误率（False
ADD）不随次数上升；衰减发生在**恢复捕获与已实现路径质量**（ret/contrib
↓、DD 加深），而中位上行潜力保留（MFE flat）；且该衰减模式依赖前序路径
状态（FR 内一致恶化、CYCLE_OK 内无同型）。"允许资金循环再进入"与"停止
下注"的边界**不是次数**，而是尚未找到的路径状态。

## 5. 下一步建议（不立即开 Policy Amendment）

T8 证明了"前序 path state × order"值得研究，但**尚未找到 decision-time
可执行状态变量**。现在直接做 policy 会重演 T7 C1（把事后结构翻译成实时
规则的失败）。自然顺序：先研究"下一次 ADD 决策时哪些 PIT 路径状态能表达
prior-path deterioration"；找到稳定、及时的变量后，再进入 Design →
Freeze → VAL（候选结构形态：前序 path state × re-risk order → 是否改变
后续 risk budget；非 order≥N → stop）。

## 6. 纪律层收束（可复用）

- **estimand 预注册**（A observed profile / B conditional contrast）在
  开工前写死，使"描述"与"条件分解"的解释边界可审计；
- **competing path 守恒**：只重构"发生过的行为"会条件化掉问题的一半
  （"什么时候停止"的样本不能消失）；
- **统计解释三层边界**（事实层 pattern / 统计层显著性 / 解释层归因）：
  分层内对比 ≠ interaction 检验；failure-to-reject ≠ equality；条件化后
  残留 ≠ 独立信息——三句边界句均已进冻结报告；
- **gate 自身被审计**：G42 抽样→全量、G43/G44 纳入 Markdown、G47 从盘上
  p 重放 Holm——名实相符的 gate 才算 gate。
