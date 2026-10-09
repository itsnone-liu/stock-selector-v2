# EI-2A Overextension Information Test — 预注册（冻结于执行前）

不产生任何交易效果；只检验「过度扩张是否携带独立利润回吐信息」。生产链全冻结不动。

## Cohort（持仓日观测）
R2-11 CONFIRM 流事件为入场（t0 收盘=entry_cost，用入场时冻结成本带）；持仓期内每隔 5 根 bar 采样一个观测日 t（t0+5,+10,…至退出或 t0+120）；t 时刻未 BROKEN ∧ 曝光>0。BROKEN 确认即右删失（不含破位后数据）。报告 ALL 与 profitable-only（浮盈>0）。

## 四变量（t 收盘可见；当日持仓横截面内排名，PIT 正确）
- **O1 DTC** = (C − cost_mid)/cost_mid（cost_mid=入场冻结带中值）
- **O2 ATRD** = (C − cost_mid)/ATR20(t)
- **O3 MHE** = mean(rank(E20),rank(E60),rank(ECOST))，E20=C/MA20−1 等（预注册合成=均值，不跑后换）
- **O4 ACC** = R5 − R20/4

每变量按当日横截面五分位（20/40/60/80%）分桶 Q1..Q5。

## Outcome（t 后前视，主判决 20d，辅助 10d）
- MFE_N = max(high[t+1..t+N])/C−1；MAE_N = min(low[t+1..t+N])/C−1
- **GIVEBACK20** = 当前浮盈 − min(未来20日 close/entry−1)（负不下限截断）
- 效率 = MFE20 / GIVEBACK20（利润保护 vs 剩余上行）
- BROKEN_FIRST_40 = 40 日内先 5 日确认破位、先于任意收新高（>C）

## PASS（至少一变量同时满足，全预注册）
① giveback20 随 Q 单调恶化 ② MAE20 恶化 ③ 非仅 MFE 更高（效率比恶化，排除大牛股假风险）④ 两 era 同向 ⑤ HL_RAISE ON 子集仍保留 ⑥ 不依赖破位后数据（已删失）。
FAIL → REDUCE=UNRESOLVED，EI-2 关闭。单次执行，不开新窗不调阈值。

## EI-2B 裁定补充（2026-10-09，冻结）
O1=PRIMARY（唯一主变量）；三臂 R0=P3+B50 对照 / R1=Q5×0.75 / R2=Q5×0.50；Q5 定义原样继承 EI-2A（逐月横截面 80 分位，PIT）；无 hysteresis/cooldown；BROKEN→0 最高优先；指标三组：组合效用 + retained-profit（Σ终值-1 / Σ峰值-1）+ 大赢家保留（R0 top5% 事件在各臂的平均收益）。PASS 八条按用户裁定。单次执行。
