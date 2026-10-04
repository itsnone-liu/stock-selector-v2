# CSR-8 Phase J — Final State Freeze

*Freeze:* `phase_j_final_freeze.json` · **sha256 `73fc8dd3312b4a9d973c76bb7a4b966af732ae45e47e8f9dee185f536a13a0c3`**
*用户裁定 2026-10-04：J1 APPROVE · COMPLETE；INCONCLUSIVE = 一次成功的验证执行（协议未因想要方向答案而越过覆盖门）*

## 终态状态块（冻结）

| 项 | 状态 |
|---|---|
| PHASE H | IMMUTABLE |
| PHASE I | FROZEN — ETF 4v8 / 8v9 = CONDITIONAL |
| PHASE J | PROTOCOL COMPLETE / VALIDATION PRODUCTION COMPLETE / **VERDICT = INCONCLUSIVE** / CAUSE = TARGET-STATE COVERAGE INSUFFICIENT / OUTCOME DIRECTION = NOT OPENED |
| DISCOVERY MIRROR ORDERING | **NEITHER VALIDATED NOR REFUTED** |
| NEW OBSERVATION | TARGET ETF-EXPANSION STATE SUPPORT IS TIME-VARYING IN THE EXAMINED DOWN WINDOW |
| 129+ | UNAUTHORIZED |
| SECTOR | DEFERRED |

## 判决记录

覆盖：cell-4 = 2/12 日；cell-8 = 1/12 日；cell-9 = 0/12 日。H_J1 (4v8) 每侧 2/1、H_J2 (8v9) 每侧 1/0，对 ≥5/侧门均不足 → **INCONCLUSIVE — SUPPORT/COVERAGE FAILURE**。方向读出不开启（覆盖门已唯一决定判决；继续算 R5 无科研价值）；不补样本，不延长窗口。

## 规范语言（冻结）

- ✅ 允许：**"在本次独立后期 DOWN 验证窗口中，目标 ETF expansion states 的支持分布显著稀疏且与 discovery 时期不同"**
- ❌ 禁止："3 日低覆盖已证明是 DOWN 市场本身的固有属性"（证据不超出已检验窗口）
- 镜像排序唯一允许总结：**NEITHER VALIDATED NOR REFUTED**；Phase I 分类原样保持

## New Observation（科研资产）

ETF expansion count **不是在时间上稳定占据同一组状态值的变量**（验证窗 support {0,2,3,4,4,5,7,7,8,10,11,12} vs discovery 期 4/8/9 常态）。验证 4/8/9 ordering 从此不是纯统计问题，而是 **support / transportability 问题**：验证时期有没有足够概率进入理论所讨论的状态空间？——不升级为离散 regime 理论证明；记录的是变量的属性，不是假设的证据。

## Support-First 研究设计约束（未来所有验证阶段冻结）

```
预声明完整候选历史区间 → outcome-blind cell-availability census → 只判"能否验证"
→ 不能：终止该设计（不换窗口）→ 能：按事先规则冻结 validation dates → 才进入 outcome production
```
**禁止**：扫很多年代 → 挑 4/8/9 最多的年份 → 宣布为验证窗口——那只是把 outcome cherry-picking 换成 support cherry-picking。

## Phase K（概念冻结，不启动）

**Phase K — Support-Aware External Validation**：第一阶段只做 state-support feasibility，不生产 R5。AUTHORIZED AS CONCEPT, NOT STARTED——启动需显式裁定 + 全新预注册。

## CSR-8 累积的边界（H→I→J）

一个理论关系不仅需要方向可重复，还要求**验证环境实际进入理论所讨论的状态空间**。J1 证明了 "support" 必须在未来研究设计里成为一等公民。
