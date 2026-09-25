# T7.4 报告：F6 Taxonomy 拆解（全段，独立预注册）

> **身份**：taxonomy 于 `3067d22` 冻结进 contract（G-F6 Lock：早于任何 F6 拆解
> 产物，git 历史序 0 个 freeze 前产品提交）。首中 ORDER
> **D4→D1→D2→D3→D5→F6'**（classification precedence 非风险排名）。全段
> 10,277 个 F6 episodes（val 5,780 / conf 3,283 / dev 1,214）。不参与 policy
> derivation（G33）；**不以 residual rate 低为成功标准**（Freeze 明文）。

## 1. 结果（全段）

| 类 | n | 占比 | 其中 end_mark_loss | completed / censored |
|---|---|---|---|---|
| **F6'** | **8,135** | **79.2%** | 12 | 6,458 / 1,677 |
| D1 振荡 | 1,289 | 12.5% | 1,289 | 1,250 / 39 |
| D4 突然破坏 | 497 | 4.8% | 41 | 452 / 45 |
| D5 高暴露滞留 | 356 | 3.5% | 356 | 356 / 0 |
| D2 迟发假恢复 | **0** | — | — | — |
| D3 持续缓慢恶化 | **0** | — | — | — |

F6' 构成：**GOOD 6,941 + PAINFUL_WIN 1,161 + CONTROLLED_LOSS 33**。

## 2. 两个结构零（数据域原因，非分类器故障）

- **D2=0（限定期表述）**：在当前 frozen false-recovery 定义与 R+40
  observation horizon 下，没有发现 >5 个有效 observation 才首次满足该
  failure condition 的 F6 episode（6,953 个 FR cycle 的 effective trigger
  offset 无一 >5，max=5——G34 negative witness 直接证明）。不扩大为
  "市场中不存在迟发假恢复"。
- **D3=0（structurally untestable）**：episode 有效观察上限 = 41 个有效日
  （R0..R+40），预注册的 ≥60 日 slow-grind taxonomy 在当前 horizon 下
  **无法检验**（G34 negative witness：max span=41<60）。这是**设计不可
  识别**而非经验零——它标记的是研究窗口本身的识别边界，值得进入 T7
  synthesis；按 Freeze 纪律不回头调 60 日阈值。

## 3. 核心发现

1. **F6 的 79.2% 是盈利类**（GOOD+PAINFUL_WIN 8,102/8,135）——印证 Freeze 时
   的预判：F6 的本质是"现有 failure taxonomy 没有理由把这些 episode 判成
   失败"。F6 不是隐藏的失败黑洞，而是**非失败大本营 + 少量可命名形态**。
2. **F6 中 observed-end-loss episodes 共 1,698**；其中 1,289 被 D1 捕获、
   356 被 D5 捕获、41 **同时呈现 D4 sudden-break morphology**、12 留在 F6'
   （11 个为 censored 浮亏）。注意 D4 是 morphology taxonomy 而非 failure
   class（其定义不含 end_mark_loss；497 个 D4 中 GOOD 399 / PAINFUL_WIN 57 /
   CONTROLLED 36 / SEVERE 5）——不应表述为"失败面被三类覆盖"。
3. **在 F6 的 endpoint-loss episodes 中，反复 REDUCE→ADD cycle 是最主要的
   预注册形态**（75.9%）。这是 morphology decomposition，不是 treatment
   comparison——D1 定义本身含 n_add≥3 AND end_mark_loss，因此**不能**推出
   "反复进出导致损失"，更不构成"减少振荡次数"的政策依据。

## 4. Gate

`t7_4_gates.json` 全 PASS：G1（4 输入）/ **G-F6 Lock 时序**（taxonomy 在
contract、freeze 前零产品提交）/ G30 taxonomy 不增删（五类+F6'）/ G31 首中
重放（分层 120 抽样独立重判，0 mismatch）/ G32 覆盖守恒（10,277 全分类唯一）/
G33 无 policy/sector / G34 component provenance（60 抽查：dd_ep/n_add 与冻结
anatomy 列逐位一致；span/occupancy/pre-break dd/tail ret 从 T6.0 冻结列重放）。

## 5. 段协议与解释边界

- 分类零（D2/D3）的读法遵守 T6.3 纪律：**classification absence ≠ mechanism
  absence**——D3 的机制可能在更长观察窗下存在，本 fact layer 无法检验。
- F6' 的 GOOD 主体不应被解读为"系统很好"：F6 的定义就是"未命中任何失败
  首中类"，盈利主体只是确认该定义工作正常。
- 无 policy 含义：本段不产生任何 policy 建议；D1 的 prominence 是描述事实，
  不构成"减少振荡次数"的策略依据（那是未来独立预注册的问题）。
- **T7 synthesis 候选张力（open question，非结论）**：T7.3 显示等待确认/
  延迟错过快速 recovery（est median=R+3）且不降低 False ADD；T7.4 显示
  endpoint-loss episodes 高度集中在多次 REDUCE→ADD 的反复 recycling。合成的
  正确问题形态："如何区分**第一次合理 re-expansion** 与**后续无效重复
  re-risk**，同时不把第一次有效再扩张延迟到 recovery 已发生之后"——
  而非"等更久"或"减少振荡"的单边答案。

## R1 审计记录（2026-09，用户 PASS WITH MINOR ISSUES 后）

- G34 重写为**全组件** provenance replay：D1/D4/D5/F6' 分层各 15 episode、
  330 次组件比较（span/occupancy/dd_ep/n_add/n_reduce/D4 break_ret/
  pre_break_dd）与 classification parquet 逐项对账，0 mismatch；新增
  **negative witness**：D2 零类直接证明（全量 FR 的 max failure_offset=5）、
  D3 零类直接证明（全量 episode max span=41<60）——结构零不再只依赖 runner
  运行结果。
- 报告表述收紧："失败面"→"observed-end-loss episodes"；D4 明确为 morphology
  非 failure class；D2/D3 加 horizon 限定；D3 标记 structurally untestable。
- 分类数字 8,135/1,289/497/356/0/0 **完全不变**（纯审计型 R1：未改 taxonomy、
  runner 分类逻辑或任何 class count）。
