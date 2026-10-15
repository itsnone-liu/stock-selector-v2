# CL-R3-B — Conditional Interaction Closure 预注册

状态：ACTIVE（2026-10-14 用户裁决；R3 唯一补充轮，结束即 CLOSE）

## 唯一问题

\[
Effort\ effect \times Context \stackrel{?}{\neq} 0
\]

不再看四象限差值；不新增条件变量；不造综合 ContextScore。

## 模型（冻结）

行 = R3 mechanism1 同一构造（110,508 行，确定性复算）。每条件变量独立拟合：

\[
Y = \beta_0 + \beta_E E + \beta_C C + \beta_{EC}(E\times C) + \gamma'X_{ctrl} + \epsilon
\]

- `E = log(amount_T / ADV20_prior)`（与 R3 相同）；
- `Y = λ̃_next = λ_next × ADV20_prior(T) / close_qfq(T)`（无量纲化：每 ADV 规模成交额产生的相对价格位移；全部 T 日量，PIT）；
- `X_ctrl` = R3 冻结控制（log ADV20、换手、σ20_prior、log close、ret20、log 市值）；**Result 不入模型**（首轮已证无独立贡献，不为框架强留）；
- Y 在合并分布 **P1/P99 缩尾**后进 OLS（防 λ 重尾支配；固定，非调参）；稳健性副报告：Y 全局秩 z 同模型仅报 β_EC 符号一致性，不作判据。

## 条件变量二值化（冻结）

| 条件 | C=1 | C=0 | 中间组处理 |
|---|---|---|---|
| PricePosition | 60 日位置 ≥2/3（高位） | ≤1/3（低位） | 中位三分组**剔除**，保组间干净 |
| EpisodeState | CD-5 L4 episode 内 | episode 外 | — |
| MarketRegime | 000985 close/MA120−1 > 0（强） | ≤0（弱） | — |

## G3 判据（三条件须同时满足，缺一不可）

- **A（稳定）**：β_EC 股票 cluster bootstrap（1000 次重采样，逐股 Gram 矩阵求和再解）P05/P95 区间**不跨零**；"一组显著另一组不显著"不算交互；
- **B（量级）**：|β_EC / β_E| ≥ 0.20（条件间 Effort 斜率差至少 20%；只看 p 值不算）；
- **C（结构）**：方向可解释（先见结构再解释；禁预设低位=吸筹/高位=派发）。

任一条件变量 A∧B∧C → 该交互通过。

## 终止树（用户裁定原文执行）

- **0 个通过** → R3 CLOSE；保留无条件 effort effect：异常高成交努力 → 未来资金推进效率下降（描述层命名待交互结果后定，候选 Impact Exhaustion / Effort Persistence Penalty）；
- **恰 1 个通过** → 保留 Effort + 该单交互，其余明确判负；仍 CLOSE；禁二层交互挖掘；
- **≥2 个通过** → 仍 CLOSE；作为下专题输入（重新预注册，R3 内不扩展）。

## 解释边界

β_EC 显著≠机制识别；条件主效应 β_C 不作独立性主张；全部 PIT、非因果、不建 CapitalState、不修改生产；G3 无论结果，absorption/distribution/吸筹/派发/主力 命名禁令在 R3 内持续有效。
