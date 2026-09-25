# T6.4 报告：Market Regime Interaction（市场态对 E 梯度 / 循环结局 / 真假恢复的作用）

> 核心问题（承接 T6.3）：同样的"反弹日 + 高效率 + 高换手"签名，为什么有些成为真恢复、
> 有些成为假恢复——外部市场 regime 是否提供区分条件？
> 数字全部来自 `output/research/t6/04_regime/t6_4_report_data.json`；市场态三分与全部阈值
> 预注册于冻结 contract（M_STRONG：breadth>0.55 且 new_high>0.10；M_WEAK：breadth<0.45
> 或 new_high<0.04；M_NEUTRAL：其余；取 R0 日 PIT 市场列）。参考 cell =
> direct_chase | P2_balanced；31,260 cycles + 21,675 episodes。

## 1. 对核心问题的直接回答（C402）：预注册 breadth/new-high 三档市场 regime 未区分同签名的真假恢复

在热签名子集（R0 日 ret_1d>0 且 efficiency>0，即 T6.3 C302 假恢复签名携带者）内：

| FR 率 | M_STRONG | M_NEUTRAL | M_WEAK | SvW diff |
|---|---|---|---|---|
| val（n=516/1,197/480） | 50.2% | 49.0% | 49.0% | +1.2pp，p=0.717 |
| conf（n=193/384/437） | 54.4% | 46.1% | 57.0% | −2.6pp，p=0.551 |

**分层后各 regime 的假恢复率都在 46–57%，CI 全部跨零**。被拒绝的是**本阶段预注册的这
一 regime 表示**（breadth/new-high 三档）；不能外推为"外部市场态不是区分条件"——流动
性、指数趋势、波动率、市场微观结构、风格等未测维度保持开放（NOT_SUPPORTED，范围限定
于所测表示）。

## 2. 全池的 regime 效应（C401/C403）

**循环结局**（A1，NO_RECOVERY 占比）：val 为 22.7%（STRONG）/ 32.8%（NEUTRAL）/
**67.2%（WEAK）**——弱市三分之二的 REDUCE 再无恢复；conf 平坦（23.1/15.2/23.5%），
段间形态不同（C401 PARTIALLY）。

**全池 FR 率**（A2，不限签名）：val SvW **+7.4pp**（48.8% vs 41.4%，Holm 显著）；conf
反向不显著（−2.5pp，p=0.215）。该对比在热签名子集内消失，结果**与恢复池构成差异一致**；T6.4 未识别造成该构成差异的
机制，也不主张 regime 对单个 cycle 增加区分信息（C403 PARTIALLY）。

## 3. E 梯度的 regime 一致性（C404）：T6.1 结论加强

E3 的 abs_mdd 优势与 terminal-failure 优势在**三个市场层 × 双段全部保持**：

| abs_mdd 中位（E1→E3） | M_STRONG | M_NEUTRAL | M_WEAK |
|---|---|---|---|
| val | 0.066→0.047 | 0.061→0.051 | 0.050→0.033 |
| conf | 0.058→0.039 | 0.052→0.035 | 0.061→0.044 |

p_terminal_failure 同构（E3 全层最低）。**六个 segment×regime 层方向一致、无 regime 方向
反转**——T6.1 风险塑形结构未被市场态分层推翻（C404 SUPPORTED；注：A3 为各层 level CI，
未做 E3−E1 pairwise 差异推断，结论限定为方向保持）。

## 4. C106 的 regime 放大（C405）

E2 的 terminal-failure 超额集中在弱市：M_WEAK 层 E2−E1 = +4.5pp（val）/ +3.7pp（conf），
M_STRONG 层 conf 仅 +1.2pp。**描述性条件结构**：未做 (E2−E1)_WEAK − (E2−E1)_STRONG
交互对比推断，"弱市放大"是描述性读法（C405 PARTIALLY，与 T6.3 的多路径 F 分解互补）。

## 5. Sector 交互（C406）：数据边界

contract 预注册的 4 个 sector_metrics **不存在于冻结的 T6.0 事实层**——sector 交互无法
执行，按数据边界如实记录（非"无板块效应"的证据；预注册本就限定 EXPLORATORY ONLY）。
Gate G9 强制隔离：主结论块零 sector 引用。

## 6. Claims（⊂ t6_4_claims.json）

C401 PARTIALLY / **C402 NOT_SUPPORTED（问题方向）** / C403 PARTIALLY / C404 SUPPORTED /
C405 PARTIALLY / C406 SUPPORTED（数据可得性范围主张）。

## 7. T6.5 synthesis 的输入

1. E3 风险塑形 regime-uniform（C404）——初始风险预算结构稳健；
2. 当前 breadth/new-high 市场 regime **未解释**真假恢复分离（C402，范围=所测表示）——
   剩余区分信息可能位于**个股内部路径或本阶段未观测的外部环境变量**（交 T6.5 综合
   T6.2/T6.3 的恶化幅度 + 签名方向；null 结果不得转述为"因此一定是个股因素"）；
3. 弱市与循环结构强相关（val 67% no_recovery；E2 张力弱市层更大）——但 conf 段形态不
   同，regime 叙事必须分段，且均为描述性。

## 8. Gate 结果

见 `t6_4_gates.json`。G9 含 NaN 一致性 + sector 隔离断言；G9b 从 contract 阈值独立重放
全部 R0 日 regime 分类；G10 重放 SvW 对比逐位一致。
