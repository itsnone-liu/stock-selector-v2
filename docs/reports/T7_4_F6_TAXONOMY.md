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

- **D2=0**：frozen false-recovery failure condition 的实际时钟域**全部**在 A0
  后 ≤5 个有效 observation 内（6,953/6,953 个 FR cycle 的 trigger offset 无一
  >5）。"迟发假恢复"在本系统不存在——假恢复要么 5 日内快速破位（F3 已捕获），
  要么撑过窗口成为真恢复。D2 的空集是 T6.2 冻结语义的直接结果。
- **D3=0**：episode 有效观察上限 = 41 个有效日（R0..R+40），**span≥60 机械
  不可达**（max=41）。"持续缓慢恶化"形态在当前观察窗内无法显形——这是 fact
  layer 观察窗的结构性质，不是阈值错误；按 Freeze 纪律不回头调 60 日阈值。

## 3. 核心发现

1. **F6 的 79.2% 是盈利类**（GOOD+PAINFUL_WIN 8,102/8,135）——印证 Freeze 时
   的预判：F6 的本质是"现有 failure taxonomy 没有理由把这些 episode 判成
   失败"。F6 不是隐藏的失败黑洞，而是**非失败大本营 + 少量可命名失败形态**。
2. **F6 的实际失败面（1,698 个 end_mark_loss）几乎被三类完全覆盖**：
   振荡 1,289（75.9%）+ 滞留 356（21.0%）+ 突然破坏中的亏损 41（2.4%）；
   F6' 内仅 **12 个亏损**（0.7%）无法命名（11 个为 censored 浮亏）。
3. 振荡是 F6 失败的主导形态——与 T7.3 的 B curve/C1 结论同向：反复进出
   （D1）是真实损失的主要来源，而"多等一等"（D3/D5 语义）要么观察窗不够长
   要么占比很小。

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
