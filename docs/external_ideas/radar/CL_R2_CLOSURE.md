# CL-R2 — 正式关闭声明（CLOSED NEGATIVE MECHANISM RESULT）

关闭日期：2026-10-14（用户终审：接受预注册停止条款，不为 drift 另开补救轮）

## 裁决

\[
\boxed{\text{CL-R2 CLOSED — negative mechanism result}}
\]

## 冻结结论（用户审定原文）

> R2 established that event-anchored VWAP can be constructed cleanly in unadjusted transaction-price space after correcting volume units and corporate-action handling. However, the preregistered tests did not establish independent price-impact, touch-and-bounce, or price-center-migration behavior attributable to the AVWAP anchor. Apparent retention/touch gradients were dominated by mechanical distance effects, and the preregistered drift measure was invalid because it shared a price-level term with the explanatory variable. R2 is therefore closed as a negative mechanism result.

中文简写：

> R2 证明了事件锚定 AVWAP 可以在真实成交价空间中可靠构造，但没有证明该锚点具有独立的推进效率、回踩承接或价格重心迁移机制。retention/touch 梯度主要来自距离算术，原 drift 指标存在共同价格项污染。Event-Anchored Cost 只能作为描述量，不能进入 CapitalState 或生产决策。

## 成立的与不成立的

成立：

\[
\boxed{\text{AVWAP 是可以干净构造的事件后平均成交价描述量}}
\]

不成立（证据不足以升级）：

\[
\boxed{\text{具有独立行为意义的 Event-Anchored Cost State}}
\]

两者必须分开。

## 不补 drift 的理由（用户裁决）

换 outcome 救假说 = 机制救援。且 R2 已有两个有效独立行为族（PriceImpact、Touch→Bounce）均未支持原机制；即使 trend-adjusted drift 出现漂亮结果，也只说明新的趋势持续性问题，不能反推"AVWAP 是有资金意义的事件成本锚"。

trend-adjusted drift 已入 `CL_RADAR_BACKLOG.md`（future ideas，非 R2-B）；重启前提=出现新的、独立资金假说 + 重新预注册。

## 证据链存档

| 阶段 | 文档 |
|---|---|
| 预注册 | `CL_R2_AVWAP_PREREGISTRATION.md` |
| Support-First 普查（含单位/因子两大数据合同发现） | `CL_R2_AVWAP_CENSUS.md` |
| 首轮机制结果与判读 | `CL_R2_AVWAP_MECHANISM1.md` |
| 数据 | `data/cl_radar/r2_avwap/`（census.json、census2.json、mechanism1.json） |
| 方法门禁（R2 教训升级） | `CL_RADAR_METHOD_GATES.md` |

## R1/R2 连续负结果的程序意义

连续两个负结果不是研究停滞：它们证明 CL Radar 的"资金逻辑优先，但物理故事必须被数据否证"制度真实拦住了两个看起来合理的外部/直觉机制。过滤器在工作。

下一步：R3 Effort vs Result（见 `CL_R3_EFFORT_RESULT_PREREGISTRATION.md`）。
