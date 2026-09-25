# T7.2 报告：DEV-only Separator Discovery（发现允许、证明不允许）

> **身份声明（contract segment_protocol.t7_2）**：本阶段第一次允许"发现 candidate"，
> 但**不证明任何 candidate**——无 VAL/CONF 计算（G22 强制）；候选空间冻结为
> same-clock hot-bounce 三元组 + 27-cell 交叉（G23 强制）；全部跑过的对比进
> exposure log（G24 强制，防选择性报告）；candidate 清单由**机械规则**产出，
> 人的选择推迟到 Policy Amendment Freeze。数字全部来自
> `output/research/t7/02_separator_discovery/t7_2_report_data.json`。

## 1. 设计

- 样本：**DEV only**，3,764 anchors（G22：源码硬过滤 + 行数断言 + n_hi+n_lo ≤ 3,764）。
- 冻结候选空间（不增删）：`max_bounce_R5` / `vol_load@maxbounce_R5` /
  `turnover@maxbounce_R5`（T7.0 三表隔离层产出的 same-clock 三元组）。
- 分箱：各特征 **DEV tertile**（q1/q2 边界值落盘 `t7_2_bins.json`，G23 从冻结
  anchor_features 独立重放逐位一致）。
- Discovery 对比（预注册、穷尽）：两个目标族 × 三特征，hi vs lo tertile：
  - **FR_within_recovered**（RECOVERED_ADD 内 FR vs clean 的率差）——C/D policy
    family 的直接研究对象；
  - **TR_all**（全 anchors TR vs no_TR 的率差）。
- 统计：T6 冻结 `cluster_boot_diff`（双侧 bootstrap p + CI），**双 cluster 单位
  各自独立报告**（stock_code / T0_date 两套），**Holm within (target, cluster)
  family**（3 tests/family）。27-cell 表为**描述性**（率 + 双 cluster level CI），
  不做逐 cell 检验。

## 2. Discovery 结果（12 contrasts，Holm 后）

**FR_within_recovered**（判别真假恢复）：

| 特征 | est (hi−lo) | stock CI | t0date CI | Holm reject（双 cluster） |
|---|---|---|---|---|
| max_bounce_R5 | **−0.299** | [−0.375, −0.213] | [−0.378, −0.230] | **是 ×2** |
| vol_load@maxbounce_R5 | −0.048 | [−0.119, +0.025] | [−0.137, +0.034] | 否 |
| turnover@maxbounce_R5 | −0.021 | [−0.087, +0.043] | [−0.089, +0.048] | 否 |

**TR_all**（判别真恢复）：

| 特征 | est (hi−lo) | 双 cluster Holm reject |
|---|---|---|
| max_bounce_R5 | **+0.461** | 是 ×2 |
| vol_load@maxbounce_R5 | +0.210 | 是 ×2 |
| turnover@maxbounce_R5 | +0.168 | 是 ×2 |

**机械 candidate 清单**（规则：FR 目标 hi−lo CI 不含 0 且 Holm reject，在两个
cluster 单位上同时成立）：**仅 max_bounce_R5 通过**；vol_load 与 turnover 均不通过。

两点如实记录（不带规则含义）：
1. **turnover 在 DEV 的 FR 判别上不显著**（est −0.021，双 CI 含 0）——T7.1 观察到的
   early-hot 结构没有转化为 tertile 主效应层的判别力；且方向为"高换手 tertile 的
   FR 率略低"。**DEV 没有发现"高换手=危险"的简单结构**。
2. TR_all 上三特征全显著正向——但 TR 判别不是 C/D policy 的直接目标（False ADD
   cost 挂在 FR 上）；这些只作为路径背景记录。

## 3. 27-cell 描述表

27 cell（3×3×3 tertile 交叉）× 2 目标的率 + 双 cluster level CI 已落盘
（`t7_2_cells.parquet`）。最小 cell n 及空 cell 如实记录；本报告不引用个别 cell
作任何条件规则表述——cell 层结构若需进入 Amendment Freeze，须整表附上。

## 4. Gate

`t7_2_gates.json` 全 PASS：G1 lineage（3 输入）→ G2b T7.0 产物不可变（5 products）→
**G22 DEV-only**（硬过滤 + 行数 + n 断言）→ **G23 冻结空间与 bins 重放**（特征集
== 三元组；DEV tertile 独立重算逐位一致）→ **G24 exposure 完整 + 机械规则重放**
（6 组对比全落盘；candidates 从 discovery parquet 独立重算一致）。

过程修正（诚实）：G24 首版集合断言表达式写错（语义混乱的嵌套推导），简化为
(target, feature) 对集合直接比较后通过——gate 自身也要被审计的又一例。

## 5. 下一步（不属本阶段）

- 机械 candidate（max_bounce_R5 的 FR 判别结构）+ 27-cell 表 + bins 边界 = Policy
  Amendment Freeze 的**全部输入**。人的选择（哪些条件进 C1/C2/D family）发生在
  Freeze，且 Freeze 必须**早于任何 VAL/CONF 验证产物**（contract 段协议）。
- VAL 后段换手方向反转（T7.1 记录）= 未来验证环境的已知压力测试，**不得**用于
  本阶段或 Freeze 的规则调整。
