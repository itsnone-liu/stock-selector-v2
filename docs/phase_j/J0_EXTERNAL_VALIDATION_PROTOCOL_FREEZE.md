# CSR-8 Phase J / J0 — External Validation Protocol Freeze

*Protocol:* `j0_protocol_freeze.json` · **sha256 `5ddd286646c92ec38274130c4e1779abfe24b2ade1240d3788846134ef2d6159`** · 盲普查与 admitted 清单已冻结（`j0_down_date_census.json` / `j0_admitted_dates.json`）
*Status:* **J0 FROZEN 后才允许任何验证样本进入（J1+）· Phase J = 独立命名空间/ledger/corpus（pj-val-0001），非 Phase H 续跑 · PHASE H 129+ 仍 UNAUTHORIZED-HOLD · SECTOR 仍 DEFERRED**

## 唯一科学问题（锁死）

Discovery/UP 已冻结：4v8<0，8v9>0。独立 DOWN 验证假设：**H_J1: 4v8>0；H_J2: 8v9<0**。
问题：*UP 中已过理论门的 4<8>9 排序，在独立且日期多样的 DOWN 语料中是否复现为 4>8<9？*

## 日期优先硬门（防"为验证挑样本"）

```
枚举合格日历日（冻结 000985 序列）→ 冻结规则判 DOWN → 预注册机械规则 admit → 冻结 admitted 日期【J0 已完成】
→ 机械展开实体 → 构建 packet → 之后才观察 ETF cell → 最后算 R5
```
准入盲于 outcome 且盲于 ETF 构成；缺 cell 的 DOWN 日期保留为 **admitted-but-non-contributing**，绝不悄悄丢弃。

## 已冻结的机械产物

- **盲普查**：524 个合格 DOWN 日期（隔离排除 27 个 discovery 观察日；R10 前向窗完整）
- **窗口分离规则**：最新优先贪心 admit，与每个已 admit 日期交易日距 ≥11（**R10 outcome 窗两两不相交**——Phase I 聚类教训上移一层：相邻 DOWN 日=同一 regime episode）
- **Admitted 12 日（冻结）**：2024-08-23, 09-09, 09-26, 2025-01-14, 02-06, 04-15, 04-30, 05-20, 06-05, 06-24, 12-17, 2026-04-07
- **实体源**：Phase A 冻结 universe84（清单 sha `2cd7d202…`，canonical 顺序，零反挑）；每日期上限 32 case；skip 全入 ledger

## 停止规则（事先固定）

3 批 × 4 日期（冻结顺序）；两臂覆盖均达标（每侧 ≥5 contributing dates）即停（**覆盖条件，盲于效应方向**）；批 3 后无条件停；禁止依效应方向增减批；**禁止采到满意为止**。

## 资格门与判决表（冻结）

R4 逐字继承（naive/date-dedup/LCO 四口径同号为假设符号 ∧ 每臂每侧 ≥5 contributing dates）；contributing date = 该臂两侧 cell 同日各有 ≥1 case。报告强制 raw n / distinct dates / max multiplicity / dedup N，**distinct DOWN dates 为主单位，raw n 降为辅助**。

| 结果 | 判决 |
|---|---|
| 2/2 supported | **VALIDATED** — 独立验证支持 UP: 4<8>9 / DOWN: 4>8<9 的 market-conditional mirror ordering |
| 1/2 supported | **PARTIAL_VALIDATION** — 镜像整体不成立，仅保留通过臂的条件性证据 |
| 0/2 supported | **NOT_REPLICATED** — I4B 的 DOWN 镜像归入低覆盖 discovery 现象 |
| 任一臂覆盖不足 | **INCONCLUSIVE**（整体）— 分臂如实报告；绝不算失败，绝不构成继续采样的理由 |

## 零探索自由度

禁新增：ETF 档位（仅 4/8/9）/ outcome / horizon / 指数 / regime 算法 / sector / subgroup。探索性发现只进单独标注的 annex 与未来阶段，**永不进入 J 的 confirmatory verdict**。

## 成功语言上限

即使 2/2 通过，唯一允许的升级表述：*"在冻结的观测体系中，ETF 扩张 4/8/9 离散状态与后续 R5 路径的 market-regime-conditional ordering 在独立 DOWN 语料中复现"*。因果语言（"ETF 档位导致价格路径"）永久禁止。

**变更控制**：本协议随 commit 冻结；改动需 append-only erratum + 显式用户授权。
