# EI-1 Market Breadth → P3 预注册（冻结于执行前）

边界：不是研究 Market alpha；breadth 只修改 target exposure，不碰候选进入/排序/退出。全部输入继承 R2-11（CONFIRM 流/T2/T3/BEAR门/HL/BROKEN/成本/帽，一字不改）。

## 四变量（日频，全市场截面，事前冻结"weak"二值条件）
- **B50**：close>MA50 股票占比；weak = B50<0.5
- **NHNL**：(20日新高数−20日新低数)/总股数；weak = NHNL<0
- **SB**：20日累计为正的 L2 板块占比；weak = SB<0.5
- **LC**（Leader Concentration，单独重点报告）：当日涨幅前20股票的正收益和 / 全市场正收益和；weak = LC>0.25（上涨过度集中于龙头=假健康）

## 臂（全部事前冻结，禁止跑后挑组合）
- **P3-base**（R2-11 原版，对照）
- P3×B50 / ×NHNL / ×SB / ×LC：weak 日 exposure×0.75，否则×1.0
- **P3×COMBO**：score=Σ(非weak)；4-3 分→×1.0，2 分→×0.75，≤1 分→×0.5
（乘在 P3 目标仓之上；与 regime 乘数叠乘——增量信息检验即在此）

## 判定（冻结）
PASS = maxDD 或 tail/BROKEN-loss 明确改善 ∧ MAR 不恶化 ∧ capital efficiency 不恶化 ∧ 两 era 方向一致。
总收益升但风险指标不动=不算 PASS；风险降但 exposure 大砍致 cap_eff/MAR 变差=不算 PASS（机械降仓）。
FAIL → Breadth 冻结为 diagnostic only，不救。
附带报告：各变量与 regime 的重叠度（防同信息换皮）。
