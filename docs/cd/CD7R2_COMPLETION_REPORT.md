# CD-7R2 — Secondary Entry · Completion Report

*预注册: `cd7r2_preregistration.json` · 结果: `cd7r2_results.json` · 引擎: `scripts/cd7r2_secondary.py`*

## 判定：停止规则触发（诚实否定）

SECONDARY_ZONE（时间整理型：带升向价格 + 距离收敛）在冻结定义下**未能找回有意义的 missed upside**，按预注册双条件（保留位置改善 AND 找回机会）缺一即停 → **timing 研究终止**。

## 数据

| | n | top-decile 率 | MAE | ret_rel | adverse |
|---|---|---|---|---|---|
| ARM B（PRIMARY，冻结）holdout | 1,178 | 2.4% | −5.3% | −1.2% | 0.249 |
| ARM C（P+S）holdout | 1,216 | 2.3% | −5.4% | −1.2% | 0.247 |
| **SECONDARY-only** | **241** | **3.3%** | −8.8% | −3.4% | 0.253 |
| PRIMARY（C 臂内） | 2,629 | 5.8% | −8.9% | — | 0.243 |

Pareto 标准逐条：capture ❌（要求 SECONDARY-only ≥500 且 top-decile ≥8%；实际 241 和 3.3%）；MAE ✅（持平）；adverse ✅（+0.2pp 内）；ret_rel ✅（持平）。**capture 是唯一目的，而它失败了。**

## 三个结构性发现（如实）

1. **SECONDARY 大部分是截胡而非找回**：真增量（C−B 总入场）仅 57 笔；241 笔 SECONDARY 中约 3/4 来自"本来会 PRIMARY 入场的 episode 提前入场"（median delay 45 sessions——SECONDARY 在 PRIMARY 之前触发）。要找回的 never-entered 池（无深回撤直线强股）几乎没被触及——它们恰恰不满足"距离收敛 ≤3%"（直线强股 d 持续扩大）。

2. **"时间整理消化"在 A 股日频上窗口极窄**：band_rising（20 日 P75 上移，需高位放量换手）× 距离收敛 ≤3% 的联合条件触发率低——机制本身可能真实存在但被 3% 收敛门排除了大部分。

3. **SECONDARY-only 质量不差但也不优**（MAE/adverse 与 PRIMARY 池持平）——问题是它没有打开新的机会集。

## 停止规则处置（按用户预冻结裁决执行）

> "如果 SECONDARY 无法同时做到保留位置改善 + 找回有意义的 missed upside，说明当前可观察数据可能不足以稳定解决 timing。"

**处置：停止 timing 扩展（无 R3）。信息边界正式入档：L0 OHLCV 可观察数据下，PRIMARY_ZONE（价格回撤型）是唯一经验证的非追高入场机制；无深回撤直线强股的捕获问题在该数据边界内无解。**

## 下一步（留用户裁定，按 R1 冻结的选项）

- **路径 α**：以风险管理系统进入 CD-7D（绝对风险预算）——L1 权限 + lifecycle 持有/退出 + PRIMARY_ZONE 已是可用的风险管理骨架；ret_rel>0 非必要条件
- **路径 β**：shadow monitoring 部署（市场风险监控 + 候选观察 + 生命周期退出提醒），entry 机制保持现状
- 数据边界备注：EM 依赖数据（amount/turnover/free-float/真实换手）若未来可用，"时间整理"机制或可重开（换手驱动的 band 上移比成交量 proxy 更真实）——但这是新数据源问题，不是 R3 调参问题

**口径披露**：strata never（n=4,827）只覆盖 rows 非空 episode，与 R1 全池口径（26,500）不同；主判定不受影响（SECONDARY-only 3.3% 在 C 臂内直接可比）。

**全局状态**：`CD-7R2 COMPLETE · timing 研究停止（信息边界入档）· CD-7D/部署待裁定 · CSR-8 不变`
