# T7.4 F6 Taxonomy 设计（pre-freeze 材料——本文写就前未读取任何 F6 子集分布）

> 对象：T6.3 首中分类 F1→F3→F2→F4→F5 之后落入 **F6（其余）** 的 episode
> （val 5,780 / conf 3,283 / dev 部分未拆——全段一起拆）。已知 F6 含 censored、
> 全部 GOOD、多数 PAINFUL_WIN——**非纯失败类**；五类均为失败形态判定，
> GOOD/censored 预期自然落入 F6'（mandatory residual，允许占比大，plan 明文
> F6'=40% 也可接受）。
>
> 纪律：分类器**首中判定**（T6.3 纪律）；五类不增删（用户已拍板类名）；本文
> 只定义机械条件与阈值——**在读任何 F6 outcome 分布之前**须 freeze 进
> contract（G-F6 Lock：sha256 + commit 时序）。

## 0. 数据基础（全部已冻结，不新造变量）

- T6.2 cycle master：per-cycle type（RECOVERED_ADD 等）、a0_day、false_recovery。
- T6.2 episode 层：exit/终态、final outcome 四分类（GOOD/CONTROLLED_LOSS/
  PAINFUL_WIN/SEVERE）、episode 内 REDUCE→ADD cycle 计数。
- T6.0 daily master：delta_day、exposure_after_ref、ret_1d_log、close_adj。
- 冻结常量：severe_dd_depth_log=0.1053605156578263（T6）、FR 窗=60 有效日（T6.2）。
- 新阈值（本预注册引入，读分布前写死）：OSC_N=3、GRIND_SPAN=60、GRIND_DD=−0.05、
  BREAK_RET=−0.07、STAG_EXPO=0.80、TAIL_W=5。

## 1. 首中顺序与五类机械定义（用户拍板冻结版）

**ORDER（classification precedence，非风险排名）：D4 → D1 → D2 → D3 → D5 → F6'**
突然破坏最局部最具体先截出（否则暴跌+多轮振荡的 episode 会被 D1 吃掉，
看不见突然破坏机制）；D1/D2 描述动态失败路径，D3/D5 描述慢滞留路径。

通用字段（全类共用）：
- `end_mark_loss = observed_endpoint_return < 0`（不叫 terminal loss）；
- `endpoint_status ∈ {terminal, censored}`——D1/D3/D5 含 censored 浮亏，
  报告拆 completed / censored 呈现（防把观察窗截止浮亏误读为已实现终局失败）。

- **D4 sudden_break**：末段 TAIL_W=5 个有效 observation 内存在单日
  ret_1d_log ≤ BREAK_RET(−7%)，且破坏前 episode 最大回撤保持 non-severe
  （pre-break max DD 未达 severe）。
- **D1 oscillation**：episode 内 REDUCE→ADD cycle 计数 ≥ OSC_N(3)；
  end_mark_loss。
- **D2 late_false_recovery（严格事件时钟）**：属 F6 输入集；存在
  recovery/ADD；**相同 frozen false-recovery failure condition 首次发生于
  A0 后第 >5 个有效 observation，且在 episode observation horizon 内实际
  观察到**。即：failure_offset ≤ 5 → 已由 T6.3 F3 捕获；failure_offset > 5
  → F6 内才有资格进 D2；**未观察到 failure（含 censored 截断）→ 不是 D2**。
- **D3 slow_grind**：有效跨度 ≥ GRIND_SPAN=60 市场日；DD 区间（负 log 口径）
  `−severe < dd_log ≤ log(0.95)`（≈−5.13%）；REDUCE 计数 ≤1；end_mark_loss。
- **D5 high_exposure_stagnation**：exposure occupancy ≥ STAG_EXPO(80%)；
  无任何 RECOVERED_ADD cycle；end_mark_loss。
- **F6' mandatory residual**：皆不中——含全部 GOOD、censored 盈利、未覆盖
  形态。**F6' 大完全不是失败**：GOOD 大量进 F6' 反而可能证明 F6 的本质是
  "现有 failure taxonomy 没有理由把这些 episode 判成失败"。T7.4 **不以
  residual rate 低作为成功标准**；Freeze 后即使 D4=0、D3 极少或 F6'=60%
  也不回头调阈值。

## 1b. F3/D2 窗边界（冻结复述）

F3：首次 recovery/ADD 后，接下来 5 个有效 observation 内满足 frozen
false-recovery failure condition（T6.3 冻结口径）。
D2：F6 输入集 + 存在 recovery/ADD + 相同 frozen failure condition 首次发生
于第 >5 个有效 observation + horizon 内实际观察到。
时钟变量=冻结 trigger_day 与 a0_day 的有效 observation 间距（T6.2 冻结列）。

## 2. 为什么这些条件（预注册理由，非分布拟合）

- D1 用 cycle 计数不依赖阈值形状；≥3 次"退出再进"是机械振荡语义。
- D2 直接复用 T6.2 冻结 false_recovery 标志，零新语义；与 F3 的关系是
  时间窗划分（5 日内=F3、其余=D2），边界即 T6.3 已冻结的 5 有效日。
- D3 的 −5% 下界=severe 的一半（阴跌语义），60 日=FR 窗口径同源；两者都只做
  "够格"判定，不做程度排序。
- D4 的 −7%≈A 股单日跌停邻域（机械"突然破坏"），要求破坏前 dd<severe 是
  "无明显信号"的可判定化。
- D5 用占用占比而非绝对收益，避免与 GOOD 重叠（终态条件已排 GOOD）。

## 3. Freeze 与 Gate 计划

1. 本设计经您拍板（类内条件与阈值可改，五类不增删）→ 写
   `t7_4_f6_taxonomy.json`（五类条件+阈值+首中序+设计文档 sha）→
   contract 增补 commit（**G-F6 Lock**：此 commit 早于任何 F6 拆解产物）。
2. `run_t7_4.py`：全段 F6 episodes 判定 → 五类+D 内交叉表（×终态四分类×段）；
   首中序机械执行。
3. `gate_t7_4.py`：G-F6 Lock 时序（taxonomy sha 在 contract、早于产物）；
   G30 taxonomy 不增删（五类+F6'）；G31 首中重放（抽样逐 episode 独立重判）；
   G32 全段覆盖（F6 全体 100% 落入五类或 F6'，无丢失）；G33 禁 policy 语义
   （F6 拆解不参与 policy derivation——产物无 policy 字段）。

## 4. 拍板记录（2026-09，用户四项）

1. 阈值冻结：OSC_N=3 / GRIND_SPAN=60 / GRIND_DD=log(0.95)（负 log 口径，
   `−severe < dd_log ≤ log(0.95)`）/ BREAK_RET=−7% / STAG_EXPO=80% /
   TAIL_W=5——round-number semantic thresholds，机械 taxonomy 非最优搜索。
2. ORDER 改为 D4→D1→D2→D3→D5→F6'（classification precedence 非风险排名）。
3. end_mark_loss + endpoint_status 双字段（censored 浮亏计入判定但报告拆分）。
4. D2/F3 边界=严格时钟定义（上文 §1b），非文字"互补"。

新增 Gate：**G34 component provenance replay**——D1-D5 每个条件的变量
（cycle count、endpoint return、exposure occupancy、pre-break dd、single-day
return、D2 failure clock）逐项从冻结 T6/T7 fact 独立重放比对，禁 runner
临时重算"差不多等价"版本。

## 5. Freeze 执行

本文档拍板版 → `t7_4_f6_taxonomy.json`（ORDER+五类+阈值+end_mark_loss
定义+§1b 时钟+F6' 非失败声明+设计文档 sha）→ contract 增补 commit
（G-F6 Lock：早于任何 F6 拆解产物，sha+时序 gate 校验）。Freeze 后禁止
回头调阈值让分类"好看"——独立预注册的价值所在。
