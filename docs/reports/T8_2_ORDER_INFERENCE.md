# T8.2 报告：Preregistered Order Inference（Estimand B — conditional order contrast）

> **身份**：固定预注册 contrast（边际 k1/k2/k3+ 三对比 + outcome₁ stratum 内
> k2 vs k3+），无事后新增条件变量（MAE/MFE/DD 分层明确排除；interaction
> contrast 未预注册、事后不新增）。Primary =
> **validation+confirmation pooled**（frozen t6 统计契约 primary_tests；
> 14,105 ADD：k1 9,033 / k2 3,372 / k3+ 1,700）；dev/全段为参考。B=2,000、
> seed=20260925、双 cluster（stock_code 主表、T0_date 稳健）、Holm 每指标
> ×cluster×族。**Estimand B 命名纪律：全部结果为 conditional association，
> 非因果**。outcome₁ 映射：FR > CYCLE_OK > OTHER；**stratum 标签精确语义**：
> FR = false_add₁；CYCLE_OK = **true_recovery₁ AND NOT false_add₁**（非
> 单纯 true_recovery——1,347 个 both-true 的 ADD₁ 已按优先级归 FR，量不小，
> synthesis 不得把 CYCLE_OK 自然语言扩大成"第一次成功恢复"）；OTHER =
> 两者皆非。

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

**落入第三形态：strata 模式不同（conditional structure）**——k2→k3+ 的
association **观测模式随前序 outcome₁ stratum 而异**（注意：这是分层描述，
不是 interaction 检验——"一个 stratum 显著、另一个不显著"不等于"两个
stratum 的 effect 显著不同"，effect modification 的正式证明需要预注册
interaction contrast，未做）：

1. **FR stratum 内存在多指标一致的梯度**：ADD₁ 假恢复后，k2→k3+ 的
   recovery/ret/contrib 下降、dd/mfe 恶化**全部 Holm 后显著**。注意
   false_add 在 FR 内也不升——**错的风险仍不升，对的结果在变差**（T8.1
   结构在 FR 内的强化版）。
2. **CYCLE_OK stratum 内未观察到 FR 那样跨指标一致的恶化梯度**：
   recovery（+3.84pp p=.20）/ret/contrib 不显著且点估计转负；**mfe 反向
   显著**（k3+ 上行中位更高）。failure-to-reject ≠ equality——不把"不
   显著"写成"无关联"。
3. **不能压成统一"次数规则"**：同样的 k3+，在 FR stratum 内多指标一致
   更差、在 CYCLE_OK stratum 内未出现同样模式——"第 N 次停止 ADD"类
   统一门没有数据基础（预注册三形态里第三形态的定义本身）。

## 4. 回答 T8 的原始问题

- RQ1（边际）：order gradient 存在但**结构不对称**——错误率平坦 +
  恢复捕获/终点收益递减 + 中位上行潜力平坦（T8.1 描述被 inference 确认）。
- RQ2（条件）：**粗粒度 outcome₁ conditioning 部分分层了该结构，但未完全
  吸收**——FR stratum 内的 k2→k3+ association 仍然存在。剩余 association
  的来源**未决**：可能来自 order，也可能来自 outcome₁ 三分类未捕获的前序
  路径差异（大量 path selection 未控制）。"order 本身携带额外信息"保留为
  未决解释，不作为 T8.2 的冻结结论。

## 5. Gate

`t8_2_gates.json` 全 PASS：G1（2 输入：anatomy parquet + t6 contract）/
G45（contrast 集合恰=预注册 6+3、指标恰 6、无新条件变量、无 policy 词）/
G46（primary 样本量与 anatomy VAL+CONF 逐组对账 + strata 划分守恒
1,686+1,631+55=3,372 / 931+750+19=1,700）/ G47（48 个 Holm 族从盘上 p 值
全量重放 0 mismatch；B/seed/cluster 与冻结契约一致）。

## 6. 边界（如实）

- Estimand B 是 conditional association：FR 内梯度保留 ≠ "FR 后的第 3 次
  ADD 导致更差"——risk set 仍在选择路径上；
- outcome₁ 三分类是**粗粒度前序状态摘要**：OTHER stratum（n=635 of k1）、
  FR∩CYCLE_OK both-true 1,347（已按预注册优先级归 FR）——分层不等于
  控制，剩余 path selection 大量存在；
- 无 policy：本段不产生任何停止规则。若未来开 policy amendment，候选
  结构形态是**前序 path state × re-risk order → 是否改变后续 risk
  budget**（而非 order≥N → stop 的统一次数门）——但当前不制定该规则，
  须独立 Design → Freeze → VAL 完整管线（Plan §3 条件门）。
