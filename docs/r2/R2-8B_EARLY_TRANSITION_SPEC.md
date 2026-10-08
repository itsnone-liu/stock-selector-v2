# R2-8B Early Transition Microstructure — 预注册规格（冻结于执行前，末轮）

按用户裁定 2026-10-08：仅此一轮；M1–M4 之外无任何特征；PASS 需真 ADD 增量；FAIL 则 ADD_TRIGGER=UNRESOLVED、Activation 研究关闭、转 R2-9。

## Cohort（嵌套口径，回归产品真实漏斗）
月末 bar 事件 t0：500日成本带 ∧ 结构未破 ∧ **T2 ∧ T3**（板块20日累计>大盘 ∧ 个股20日>板块，与 R2-7 嵌套 T3 行同轨）。

## 四个特征（t0 收盘可观测，逐日数据，布尔；不得改窗调参）
- **M1_RECLAIM**（Support Position Phase）：近15日内出现过 close<带中值（曾落中值下方）∧ 最近3根 close 全部 ≥ 带中值（收复中值并站住）。
- **M2_DPE**（Downside Pressure Exhaustion）：w1=[t0-19..t0-10], w2=[t0-9..t0]；DPE(w)=Σ|下跌日收益|/Σ(下跌日成交量)；M2 = DPE(w2) < DPE(w1)（单位卖量推动价格下跌的效率衰减）。
- **M3_REB_EFF**（Recovery Efficiency Emergence）：hd=argmax close[t0-19..t0]，lo_=argmin close[hd..t0]；下跌效率 eff_dn=(close[hd]−close[lo_])/Σ|close[j]−close[j−1]|, j∈(hd..lo_]；反弹效率 eff_up 同式 j∈(lo_..t0]（需 t0>lo_）；M3 = eff_up > eff_dn。
- **M4_VPHASE**（Volume Phase Shift）：dv(w)=Σ下跌日成交量/Σ全部成交量；M4 = dv(w2)<dv(w1) ∧ w2 上涨日均量 > w1 上涨日均量（卖方量缩+买方量回）。

## Outcome / 判定（继承，冻结）
conv=fwd60 max(high)/close−1≥30%；brk=fwd60 内 5日确认破位。
**PASS = conv 较嵌套 T3 基线 +3pp 以上 ∧ brk 恶化 ≤2pp ∧ 两时代方向一致 ∧ n(on)≥100。** 单次执行，不调参不重跑。
