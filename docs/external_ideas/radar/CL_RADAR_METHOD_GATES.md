# CL Radar 通用方法门禁（Program-Level Method Gates）

来源：R1/R2 负结果教训，用户 2026-10-14 裁定升级为 CL Radar 程序级门禁。今后所有 CL Radar 研究（R3 起）预注册必须逐门声明如何通过；普查/构造/结果阶段逐门复核。

## Gate U — 单位合同门（Unit Contract）

**要求**：所有量纲与口径假设必须在 Support-First 普查阶段事前实证，不得默认。

- volume 单位：daily_fullmarket 为**手**（×100 才是股；实证 (amount/volume)/OHLC4 ≈ 99.97）；
- amount 单位：元（实际成交额，未复权口径）；
- 复权：qfq/unadj 因子为分段常数；以幅度（>2%）而非计数（1e-6 容差）判定真实除权断裂，断裂窗口单列；
- 任何新数据源接入先做单位 sanity（构造量 vs 同空间可证量的比值应≈1）。

**拦截方式**：事前普查；禁止靠事后异常值发现。R2 实证：naive VWAP 差 100 倍，只看最终相关根本发现不了。

## Gate M — 机械距离基线门（Mechanical Distance Baseline）

**要求**：凡 distance-to-level → touch/hit/retention/breakout-命中 类 outcome，必须先建立"纯距离算术"的机械 baseline（价格离锚越远，短期触及概率越低是算术必然）。

**证据标准**：观测梯度**超出**机械基线的部分才可作为行为证据；梯度方向与机械预期一致且量级未超基线 → 判"机械效应"，不计入机制 Gate。

R2 实证：retention 0.26→0.48→0.97 / touch 0.85→0.71→0.14 单调梯度被判距离算术，非"事件成本引力"。

## Gate S — 共享构造项污染门（Shared-Construction-Term Contamination）

**要求**：凡解释变量 X=f(P) 且 outcome Y=g(P) 共享构造输入（价格水平、成交量、同一窗口均值等），必须先检验相关是否由共同项直接制造。

**证据标准**：无法在构造上剥离共同项 → 该 outcome 无效，不计 Gate；不得用控制变量"洗"掉构造性污染后继续使用。

R2 实证：drift10 与 gap 共享价格水平项，ρ=0.79 / partial=0.998 判构造性污染，该族无效。

## 附：Future Ideas Backlog（非预注册，不编号为 -B）

| 想法 | 来源 | 重启前提 |
|---|---|---|
| trend-adjusted drift（相对前趋势的价格重心偏移） | R2 drift 族操作化失败后的一次性想法 | 出现新的、独立资金假说 + 重新预注册；禁作为 R2 补救 |
| LocalSupply 重启 | R1 关闭 | 真实持仓 / Level2 / 账户结构 / 直接卖出行为数据 |
