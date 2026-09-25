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

## 1. 首中顺序与五类机械定义

判定对象=F6 episodes 全体（每 episode 按 D1→D2→D3→D4→D5 首中即止，皆不中→F6'）：

- **D1 反复 REDUCE↔ADD 振荡**：episode 内 REDUCE→ADD cycle 数 ≥OSC_N(3)
  且 episode 终态为亏损（final outcome ∈ CONTROLLED_LOSS/SEVERE，或 censored
  且末仓浮亏）。
- **D2 热反弹后失败（迟发假恢复）**：存在 false_recovery=True 的 RECOVERED_ADD
  cycle（T6.2 冻结 60 日窗语义——T6.3 的 F3 已截获 A0 后 5 有效日内再破位者，
  D2 截获**其余**迟发破位，与 F3 窗口语义互补不重叠）。
- **D3 持续缓慢恶化**：不中 D1/D2；episode 有效跨度 ≥GRIND_SPAN(60) 日；期间
  最大回撤达 [GRIND_DD(−5%), severe) 区间（阴跌到位但从未触发 severe 结构
  断裂）；REDUCE 次数 ≤1；终态亏损或 censored 浮亏。
- **D4 无明显信号突然破坏**：不中 D1-D3；末段 TAIL_W(5) 个有效日内存在单日
  ret_1d_log ≤BREAK_RET(−7%)，且该日之前 episode 最大回撤 < severe（破坏前
  无预警）；终态亏损或 censored 浮亏。
- **D5 长期高暴露滞留**：不中 D1-D4；exposure_after_ref 加权占用占比 ≥
  STAG_EXPO(80%)（有效日均值/满仓比）且无任何 RECOVERED_ADD cycle；终态亏损
  或 censored 浮亏。
- **F6' mandatory residual**：以上皆不中——含全部 GOOD、纯 censored 盈利、
  以及任何未覆盖形态。**不要求小**；报告如实给占比。

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

## 4. 待您拍板

1. 五类机械条件与阈值（OSC_N=3 / GRIND_SPAN=60 / GRIND_DD=−5% / BREAK_RET=
   −7% / STAG_EXPO=80% / TAIL_W=5）——数字可改，改后冻结；
2. 首中顺序 D1→D2→D3→D4→D5（振荡/迟发假恢复优先于慢形态；可重排）；
3. "终态亏损"边界是否含 censored 浮亏（当前：含）；
4. D2 与 F3 的窗边界复述确认（5 有效日=T6.3 冻结口径）。
