# CD-7 — Entry-Zone & Participation Timing · Completion Report

*预注册: `cd7_preregistration.json` · 结果: `cd7_results.json` · 引擎: `scripts/cd7_entry_zone.py`（L1 权限冻结继承 CD-6 层 B）*

## CD-7C 三臂验证（每笔中位相对收益 / MAE）

| 臂 | dev ret_rel | holdout ret_rel | holdout MAE | adverse (holdout) |
|---|---|---|---|---|
| CHASE（对照，已否定不复活） | −6.2% | −2.9% | −8.5% | 0.209 |
| **ZONE（两阶段 entry-zone）** | **−3.7%** | **−1.2%** | **−5.3%** | 0.249 |

**完成测试判定（预注册三条件）：2/3 通过 + 1 项如实不通过**
- ✅ MAE 更低（−5.3% vs −8.5%，改善 3.2pp——downside 结构显著改善）
- ✅ 相对收益更好（−1.2% vs −2.9%；dev 同向 −3.7% vs −6.2%）
- ❌ adverse 率未更低（0.249 vs 0.209，高 4pp）：ZONE 入场位置更低，持有期内遭遇 DECAYING 的频率相当——入场更安全但持有路径暴露未变

**核心结论：非追高 entry-zone 改善了入场结构（位置语义有效），验证了「强势 ≠ 好的入场位置」。**

## 机会代价（诚实披露，与 L1 层性质不同）

| | ZONE 入场组 | 从未入场组 |
|---|---|---|
| episodes | 2,813 | 26,500 |
| 60d top-decile 率 | **5.7%** | **10.2%** |

ZONE 系统性错过直线强股（从不深回撤的 top-decile）——这是**真实的机会-风险交换**，不是纯改善（CD-6 L1 层拒绝组与放行组 top-decile 率几乎相等 11.2% vs 9.9%，所以 L1 是纯改善；ZONE 的未入场组确实更强）。每笔 MAE 改善 3.2pp 的代价是 top-decile 捕获率减半。

## CD-7B Pullback vs Failure 判别：方向反转（否定，如实记录）

| 回撤日 as-of 状态 | n | P(recovered) | P(broke) |
|---|---|---|---|
| intact（结构完好） | 151,820 | 58.4% | 38.2% |
| not intact（结构受损） | 23,589 | **64.6%（更高）** | 32.2% |

**判别方向与预注册预期相反**：结构受损组的"恢复率"反而更高。诊断：`recovered=20 日内回到 P75 之上` 的 proxy 有**位置距离偏置**——深回撤组离 running P75 更近，回到 P75 需要的涨幅更小，衡量的是位置距离而非真实恢复。as-of intact 判别在 CD-7 Round 1 **未获支持**，方法学警告入档。

## 停止规则判定

Entry-zone 在 holdout 改善了入场结构（MAE ✅ ret_rel ✅）→ 按 CD-7C 字面允许进入 CD-7D。但 adverse 条件未过 + top-decile 捕获率减半的代价 → **CD-7D（risk budget）是否开启留用户裁定**，可选前置：re-entry 规则（错过首次 zone 后的二次触发）以改善捕获率。

## 程序级状态

```
已验证继承+新增：L1 权限（冻结）· L4 lifecycle 持有/退出 · entry-zone 位置语义（MAE/ret_rel 双改善）
新增否定：chase 入场（再次对照确认）· CD-7B intact-判别（proxy 偏置）
未解决：top-decile 捕获 · re-entry · add timing · 绝对风险预算
```

**全局状态**：`CD-7 (Round 1) COMPLETE · CD-7D 待裁定 · CSR-8 不变`
