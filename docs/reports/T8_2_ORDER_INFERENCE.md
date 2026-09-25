# T8.2 报告：Preregistered Order Inference（Estimand B — conditional order contrast）

> **身份**：固定预注册 contrast（边际 k1/k2/k3+ 三对比 + outcome₁ stratum 内
> k2 vs k3+），无事后新增条件变量（MAE/MFE/DD 分层明确排除）。Primary =
> **validation+confirmation pooled**（frozen t6 统计契约 primary_tests；
> 14,105 ADD：k1 9,033 / k2 3,372 / k3+ 1,700）；dev/全段为参考。B=2,000、
> seed=20260925、双 cluster（stock_code 主表、T0_date 稳健）、Holm 每指标
> ×cluster×族。**Estimand B 命名纪律：全部结果为 conditional association，
> 非因果**。outcome₁ 映射：FR > CYCLE_OK > OTHER（frozen ADD₁ 标签；
> both-true 冲突 1,347 计入 FR，如实报）。

## 1. 边际层（primary，stock_code，Holm 后）

| 指标 | k1vsk2 | k2vsk3+ | k1vsk3+ | 读法 |
|---|---|---|---|---|
| false_add_rate | +0.41 (p=.91) | +1.07 (p=.91) | +1.48 (p=.83) | **平坦确认** |
| recovery_rate | **+4.25pp (p<.001)** | **+5.71pp (p<.001)** | **+9.95pp (p<.001)** | **递减确认** |
| dd_w10 | **+0.47pp (p=.004)** | **+0.68pp (p=.006)** | **+1.15pp (p<.001)** | 恶化确认 |
| mfe_w10 | +0.14 (p=1.0) | +0.05 (p=1.0) | +0.19 (p=1.0) | **中位上行平坦确认** |
| ret_w10 | **+0.63pp (p<.001)** | +0.20pp (p=.46) | **+0.83pp (p=.004)** | 递减集中早期 |
| contrib_w10 | **+0.41pp (p=.004)** | +0.28pp (p=.27) | **+0.69pp (p<.001)** | 同上 |

T0_date 稳健：recovery 三对比全显著（p=.007/.002/<.001），false_add 全不
显著——方向一致。

## 2. 条件层（outcome₁ stratum 内 k2 vs k3+，primary，Holm 后）

| stratum | n(k2,k3+) | recovery | dd | mfe | ret | contrib | false_add |
|---|---|---|---|---|---|---|---|
| **FR**（ADD₁ 假恢复） | 1,686/931 | **+8.35pp*** | **+0.71pp*** | **+0.89pp*** | **+0.99pp*** | **+0.79pp*** | +1.55 (ns) |
| **CYCLE_OK**（ADD₁ 真恢复） | 1,631/750 | +3.84 (p=.20) | +0.73 (p=.11) | **−0.87pp***(反向) | −0.27 (p=.91) | −0.10 (p=1.0) | +0.49 (ns) |
| OTHER | 55/19 | 0 (p=1) | −1.16 (p=.78) | +1.40* | −0.54 (p=.91) | −1.11 (p=1) | −18.2pp*(伪) |

（* = Holm 后 p<.05；OTHER 行 n=55/19 **过小不解读**——false_add 的
−18.2pp "显著" 是 19 个样本的噪声形态，仅记录。）

T0_date 稳健：FR 内 recovery（p<.001）与 contrib（p=.033）显著、CYCLE_OK
内全不显著——与主 cluster 一致。

## 3. 判读（对照预注册三形态）

**落入第三形态：strata 方向不同（conditional structure）**——order gradient
的存在性**依赖于前序 outcome**：

1. **FR 前序下梯度保留**：ADD₁ 假恢复后，k2→k3+ 的 recovery/ret/contrib
   下降、dd/mfe 恶化**全部 Holm 后显著**——在"第一次已经错了"的路径上，
   order 仍携带额外条件信息（后续每次 re-risk 的恢复捕获继续衰减、下行
   继续）。注意 false_add 在 FR 内也不升——**错的风险仍不升，对的结果
   在变差**（T8.1 结构在 FR 内的强化版）。
2. **CYCLE_OK 前序下梯度消失**：ADD₁ 真恢复后，k2vsk3+ 的 recovery
   （+3.84pp p=.20）/ret/contrib 全不显著且点估计转负；**mfe 甚至反向
   显著**（k3+ 上行中位更高）——第一次成功后，后续 re-risk 次数与 outcome
   无系统关联。
3. **不能压成统一"次数规则"**：同样的 k3+，在 FR 前序下系统性更差、在
   CYCLE_OK 前序下不差——"第 N 次停止 ADD"类规则没有数据基础（这本身
   就是预注册三形态里第三形态的定义）。

## 4. 回答 T8 的原始问题

- RQ1（边际）：order gradient 存在但**结构不对称**——错误率平坦 +
  恢复捕获/终点收益递减 + 中位上行潜力平坦（T8.1 描述被 inference 确认）。
- RQ2（条件）：**outcome₁ 解释了梯度的 CYCLE_OK 部分、解释不掉 FR 部分**。
  order 不是纯粹的前序路径质量 proxy（否则条件化后应全部消失）；它只在
  失败前序下携带额外的条件信息。

## 5. Gate

`t8_2_gates.json` 全 PASS：G1（2 输入：anatomy parquet + t6 contract）/
G45（contrast 集合恰=预注册 6+3、指标恰 6、无新条件变量、无 policy 词）/
G46（primary 样本量与 anatomy VAL+CONF 逐组对账 + strata 划分守恒
1,686+1,631+55=3,372 / 931+750+19=1,700）/ G47（48 个 Holm 族从盘上 p 值
全量重放 0 mismatch；B/seed/cluster 与冻结契约一致）。

## 6. 边界（如实）

- Estimand B 是 conditional association：FR 内梯度保留 ≠ "FR 后的第 3 次
  ADD 导致更差"——risk set 仍在选择路径上；
- OTHER stratum（n=635 of k1）的三值映射覆盖了 4.4% 的 primary k1 冲突
  （FR∩CYCLE_OK=1,347 计入 FR）——优先级是预注册的，冲突数如实报；
- 无 policy：本段不产生任何"停止规则"；若未来要做，须独立 Design →
  Freeze → VAL 完整管线（Plan §3 条件门）。
