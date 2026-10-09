# EI-3 RPS / Sector-neutral RS — 预注册 descriptor（冻结于执行前）
不改 gate。cohort=R2-11 CONFIRM 流事件（与 EI-1/2 同一事件集）。四表达（入场可见，逐月横截面五分位，PIT 同 EI-2A 法）：
RPS_S=20日收益排名 | RPS_M=120日 | RPS_L=250日 | RS_SN=个股20日−板块20日（sector-neutral，主判决）
Outcome（主20d辅60d）：fwd均值、conv(fwd>0)、winner-tail(事件内P90)、brk率、brk均损、入场DTC均值、DTC-Q5占比。
分层：ALL / era / BULL-BEAR。
判定：主判决 RS_SN——winner质量稳定单调 ∧ 不显著恶化离带距离(DTC/Q5占比) ∧ tail不恶化 ∧ 两era同向 → 才有资格进 T3 增量验证；若高质量伴随Q5占比大升 → 只作 HOLD/REDUCE 描述。单次执行，不调窗口不换排名法。
