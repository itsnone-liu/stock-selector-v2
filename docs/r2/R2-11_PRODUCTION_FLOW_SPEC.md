# R2-11 Production-Flow Position Validation — 预注册（冻结于执行前）

R2-10 已 PASS 冻结：宽 BUILD 流上 P0 绝对收益最高/回撤不可实盘；P3 regime梯回撤减半、MAR 持平、资本效率最高。R2-11 = 最终验收，非翻案、非调参。

## 候选流（production CONFIRM 语义，冻结规则回放）
月末 t0：500日带 ∧ close∈[带low×0.95, 带high] ∧ **T2（板块20日累计>大盘20日累计，l2 行 mkt_eq）** ∧ **T3（个股20日>板块20日）** ∧ **BEAR 门（L1 五日多数票 BEAR 时需 HL_RAISE：min(low[-5:])>min(low[-10:-5])）**。每月截 150（seed 42）。
## 组合帽（两臂完全相同）
细分板块（L2）≤20%/月、行业（L2 前三位）≤35%/月、单股=等权 1/n；超额随机剔除（seed 42）。另报 uncapped→capped 差异（组合约束效果，不记入 P3 credit）。
## 仓位臂（原样带入，不改）
P0 全仓 vs P3（20 基座+T3 跳档+盈利跳档+regime 乘数 BULL1.0/BEAR0.5/OTHER0.75；UNDERCUT 减半；BROKEN 归零；成本 0.15% 单边）。退出=BROKEN 5日确认（跨臂统一）。
## 验收问题（预注册）
① CONFIRM 流 BROKEN 率是否较 BUILD 流 61.7% 大幅下降（WHERE+WHAT 质量验收）；
② P3 是否仍降 maxDD/tail/broken-loss（独立组合价值 vs 补偿宽流噪声）；
③ P3 资本效率是否仍最高（低敞口≈主动保留的风险预算）。
结果三形态 A（双政策）/B（链闭合·最理想）/C（P3 优势消失→简化体系）均闭环。
停止线：单次执行；不改任何门/梯级/成本/指标。
