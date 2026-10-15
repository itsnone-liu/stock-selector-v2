# CD5-EVIDENCE-AUDIT — EpisodeState 证据依赖 + 敏感性审计（2026-10-15）

范围冻结：审计+敏感性重放，不改任何生产权重/代码。触发：CL Radar R5 OOS-A 判负 F2（episode×effort amplification，−52.4%→+19.9% 符号翻转）。

## 1. 证据依赖定型：**A 型**

- **时间线证据**：CD-5 完成 2026-10-04（commit 161993d）；R3-B amplification 结果产生于 2026-10-13，晚于 CD-5 九天——R3-B 证据在 CD-5 设计时**不存在**，物理上不可能进入其证据链。
- **文本证据**：`grep -rl 'R3-B|amplification|交互放大|episode×effort' docs/cd/` → **零命中**（全部 19 份 CD 文档无一处引用 R3-B/CL Radar 结果）。
- **代码证据**：CD-6 决策引擎（cd6_decision_engine.py）、CD-7 entry zone（cd7_entry_zone.py）、CD-7D risk budget（cd7d_risk_budget.py）中 episode = L4 episodes 数据结构（交易序列单元：episode_id/start/end/origin），源自 CD-5 自身的 L4 状态合同；无任何 Effort/EffortPenalty/amplification 交互项。
- **CD-5 自身证据基础**（与 R3 无关）：L4 状态时间衰减结构（短期延续/中期回归/长期弱段，dev/holdout 复验一致，见 CD5_COMPLETION_REPORT）。

**结论：CD-5 EpisodeState 证据 = 100% pre-R3 独立支持（A 型）。R3-B amplification 从未进入 CD 生产证据链；F2 判负对 CD-5/6/7 零污染。**

## 2. 敏感性重放：**零敏感性（by construction）**

- Current vs without-EpisodeState vs preR3-weight 三对比中，"preR3-weight" 不存在——CD 侧没有任何 R3 派生权重可撤销；
- "without-EpisodeState"（拆除 episode 数据结构）针对的是 CD-5 自身证据（未被 R5 触及），不属于本轮停止规则范围，不做；
- 候选集/exposure/action/历史样本路径：**无变化**（无可移除项）。

## 3. 裁决（按冻结停止规则）

A 型 + 零敏感 → **不动**。唯一动作：本审计存档，CL Radar 侧叙事已自行更正（episode 降级为 context variable，见 CL_R5_OOSA_REPORT.md）。

## 4. 边界

- CL Radar 文档中 episode_state 作为 conditioner 的使用（R3-B/R4）属 CL Radar 分析层，已在其程序内裁决（F2 永久判负），与 CD 生产无关；
- 本审计未重新研究 Episode 决策价值本身（如未来需要，另立项目）。
