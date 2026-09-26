# CSR-8 Phase A — FROZEN

- **冻结 commit：`1cabde8`（2026-09-26）**，用户最终对账裁决 PASS。
- 冻结基线：G1=4 / G2=20 / G3=20 / G4=20 / G5=20，总计 **84 cases**；multi-group=0。
- 守恒：五组 chosen/substitutes/excluded 两两不交、union=候选池，全部通过。
- G1 月首起点硬 gate 覆盖全部 episode；全池 99.5% = 26.1721928596×；
  recovery sensitivity = 1 / 4 / 7（15%/20%/25% @ 固定全池阈值）。
- G2 口径：reference = pre-20d max close（不含 T0）；检查窗 = T0+1..T0+120；444 候选。
- replay manifest 与输入/输出哈希已同步（commit B=67020fb 起的哈希链 + AUDIT-FIX2 刷新）。

## 唯一保留状态

> **G5 = PROVISIONAL_PENDING_PIT_REVALIDATION**

G5 当前基于现时行业快照（csrc_industry_snapshot.json）。Phase B 的 PIT 行业时点表
落地后必须做 G5 membership revalidation；若样本变化按同一冻结规则整体重放，
不得人工保留原样本。

## 后续推进约束

- Phase B：全部外部数据通道建设（不依赖样本 ID）。
- Phase C：以 `1cabde8` 的 84 案例为唯一冻结样本输入；G1–G4 可直接生成 blind packets；
  G5 在 PIT revalidation 后再正式封包。
- **不得重新打开 Phase A 样本选择逻辑**，除非发现输入资产本身存在事实错误。
