# CL-R3 — Effort vs Result 预注册

状态：ACTIVE（2026-10-14 用户裁决启动；R1/R2 已 CLOSED）

## 0. 研究问题（冻结）

**市场付出了多少成交努力，得到了多少价格结果？——努力—结果结构是否具有稳定行为意义？**

顺序纪律（用户裁定）：先证明 **Effort-Result State** 存在稳定行为意义，再考虑资金生命周期解释。

禁止：在任何 Gate 通过前把状态命名为 absorption / distribution / 吸筹 / 派发（R1/R2 教训：不因方向漂亮提前命名）。禁止 Factor→Return、参数搜索、换 outcome 救假说。

## 1. 构造定义（冻结）

在决策日 T（要求 ≥21 日前置历史）：

```text
Effort(T) = log( amount_T / ADV20_prior(T) )     ADV20_prior = 前 20 日 amount 均值（不含 T）
Result(T) = |ret_T| / σ20_prior(T)               σ20_prior = 前 20 日收益标准差（不含 T）
State(T)  = (Effort 高/低) × (Result 高/低)，按主样本合并分布中位数二分
sign(T)   = sign(ret_T)                          记录为条件变量，不入状态
```

- 单位：amount=元；ret 基于 qfq（Gate U 声明：不涉及 volume 手/股换算；amount 与价格分属水平/相对量纲）；
- 归一化动机：Effort 与 Result 均为相对量，构造上排除规模与波动水平的机械共变（R1 控制教训前置到构造层）；
- 机械退化检验（Gate S 前置）：若合并 Spearman(Effort, Result) 或股票内中位 |ρ| > 0.7 → 二维状态退化，判 INSUFFICIENT_SUPPORT。

## 2. 结果变量（冻结族，禁晚挑）

1. **λ_next**（主结果）：T+1..T+20 窗口 λ（B1 同法：Δclose_adj ~ OF 无截距斜率，OF=amount×sign(Δclose_adj)）——推进效率的行为延续性；不含 T 及以前数据，与状态输入无共享项（Gate S 合规）；
2. **realized_vol_ratio**：未来 20 日收益标准差 / σ20_prior(T)；
3. **max_drawdown20**：未来 20 日内最大收盘回撤。

禁止使用 distance-to-level 类命中结果（Gate M 不豁免；如未来需要，必须先建机械基线）。

## 3. 条件变量（冻结集，用户指定方向的可观测化）

- **价格位置**：close_T 在过去 60 日 [low,high] 的位置（0–1）——低成本/高浮盈区域的可观测代理（不使用 R1 已关闭的筹码模型）；
- **episode 阶段**：T 是否落在 CD-5 L4 episode 内及处于前/后半——突破前后代理；
- **市场强弱**：中证全指 000985（冻结日线库）close 与其 120 日均线之比——regime 代理，PIT。

## 4. 混杂控制（冻结）

log ADV20、当日换手、σ20_prior、log close、ret20、PIT log 市值（close×outstanding_share）。分析层另做股票 cluster bootstrap（1000 次重采样）。

## 5. Gate（预注册）

- **G1 构造有效性**：普查通过 Gate U（单位事前实证）+ 退化检验 + 状态分布平衡（每象限 15%–35%）；
- **G2 稳定性**：State → λ_next 关联在全部控制 + 股票 cluster bootstrap 下方向稳定（P05/P95 同号）；
- **G3 条件结构**：至少一个条件变量（价格位置/episode 阶段/市场强弱）下，状态→行为映射出现显著分化（同一状态在不同条件下意义不同）——R3 核心问题。

停止条款：G1 失败 → INSUFFICIENT_SUPPORT 报告并停止；G2 失败 → CLOSE（不换 outcome、不调窗口、不加核）；G2 过 G3 不过 → 保留为"无条件 Effort-Result 描述"，仍禁生命周期命名。

## 6. 解释边界

Effort/Result 是成交额与价格位移的可观测结构，不识别参与者身份与意图；λ_next 为机制结果非交易信号；全部结论 PIT、非因果；不修改生产、不建 CapitalState。
