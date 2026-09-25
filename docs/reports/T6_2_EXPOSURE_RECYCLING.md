# T6.2 报告：Exposure Recycling（REDUCE→ADD 状态循环）

> 核心机制问题：动态仓位的优势是否来自"坏状态释放资本、修复后重新投入"？
> 本报告所有数字来自 `output/research/t6/02_recycling/t6_2_report_data.json`（机器聚合），
> 阈值/分类/窗口全部预注册于冻结 contract。参考 cell = direct_chase | P2_balanced。

## 1. Cycle 提取（contract 规则）

R0 = REDUCE 日（连续 REDUCE 时 R0 前移到最后一个）；A0 = 其后首个 ADD。共 **31,260
cycles**（RECOVERED_ADD 15,646 / NO_RECOVERY 11,858 / FAILED_EXIT 3,338 / CENSORED 418），
validation 17,150 / confirmation 10,346 / development 3,764（reference only）。A0−R0 中位
**2 天**（三段一致）。

**结构事实（C204）**：EXIT 通道只在 confirmation 触发（3,328/3,347 个退出 episode 在
conf；validation 为 **0**）。validation 段的动态暴露不含退出保险；T5.8R-2 的 no_exit
反事实对比主要由 confirmation 段贡献。FAILED_EXIT 组在 validation 段结构性为空（相应
统计单元格为 NaN，非缺失错误）。

## 2. 恶化验证（C201）：REDUCE 时刻相对前 5 日基线的变化（中位，stock cluster CI）

| det 量 | RECOVERED_ADD (val/conf) | NO_RECOVERY (val/conf) | FAILED_EXIT (conf) |
|---|---|---|---|
| 回撤深度 | **+0.59pp / +0.68pp** | **+3.33pp / +2.38pp** | **+3.72pp** |
| efficiency_signed_3 | −0.0005 / −0.0010 | −0.0069 / −0.0062 | −0.0066 |
| dist_ref20 | 0.00 / +0.0020 | −0.032 / −0.019 | −0.035 |
| turnover_load_3d | −0.039 / −0.035 | −0.132 / −0.109 | −0.131 |
| cum_ret（价格） | +0.0002 / +0.0023 | −0.031 / −0.017 | −0.035 |

总体呈恶化特征（回撤/efficiency/turnover 在所有非空组显著），但**幅度强分层**：不修
复组的恶化约为修复组的 3–6 倍——恶化程度本身是 cycle 结局的强预测子。注意
RECOVERED_ADD 的部分价格类指标接近零（validation cum +0.0002、dist_ref20 ≈ 0，CI 跨
零），并非五个指标全部显著恶化。

## 3. ADD 的状态语义（C202）：不是修复，是低位快速回补

RECOVERED_ADD 组在 A0（中位 R0+2 天）相对 R0 的变化（中位，CI 均不含零）：

| rep 量 | val | conf | 解读 |
|---|---|---|---|
| 回撤深度 | **+1.51pp** | **+1.83pp** | 更深 |
| cum_ret（价格） | −1.48pp | −1.81pp | 更低 |
| dist_ref20 | −1.51pp | −1.91pp | 更低于 ref20 |
| efficiency_signed_3 | −0.0039 | −0.0043 | 更差 |
| turnover_load_3d | −0.065 | −0.049 | 唯一"降温"维度 |

**预注册的"修复后重入"读法被拒绝（C207 NOT_SUPPORTED）**：ADD 在 REDUCE 后很快发生
（中位 2 天），发生时价格低于 R0、多数预注册状态指标尚未修复（五量中四个更差、只有
turnover 降温）。"低位回补"是**行为描述性标签**（规则输出的刻画），不含价值/便宜判
断，也不是因果机制主张。

## 4. 同窗漂移对比（C205，固定窗 REC−NO，防成功样本选择）

validation H5 全面分离（dd −4.9pp 更浅、价格 +10.8pp、turnover +0.78）；confirmation
H5 混合（dd 差不显著 p=0.74、efficiency −0.0066），H10 恢复全面显著。可恢复 cycle 的
短期状态优势**依段而异**（PARTIALLY_SUPPORTED）。

## 5. 路径分离（C203/C206）：从 R0 起的 buy&hold（PIT 前缀统计）

| horizon | REC (val/conf) | NO (val/conf) | REC−NO |
|---|---|---|---|
| H5 | −1.5% / −2.6% | −12.4% / −9.6% | **+10.8pp / +7.0pp**（p<0.001） |
| H10 | +0.2% / −1.1% | −17.5% / −18.3% | **+17.7pp / +17.1pp** |
| H20 | +6.4% / +7.2% | 未检验（空组） | NaN（diff/CI/p 一致 NaN） |
| H40 | +18.3% / +22.7% | 未检验（空组） | NaN |

NO_RECOVERY 组在 H20/H40 结构性无足够存活路径（生存差异本身是循环结构的一部分，
C206）。此为冻结规则下的**描述性分离**，不构成对 ADD 规则信息含量的因果主张。

## 6. 对"释放资本—重入"机制的最终回答（C207）

- ✅ "坏状态释放资本"：成立——REDUCE 由恶化触发，且恶化幅度分层预测结局；
- ❌ "修复后重新投入"：不成立——ADD 时状态量更差、价格更低；
- ✅ 替代描述：**轻度恶化的 REDUCE 在价格进一步回落后（中位 2 天）低位买回，该组后续
  路径显著优于不修复组**；动态暴露的优势模式与"低位回补"一致，与"简单少持仓"的区别
  在于重入的选择性（C201 的幅度分层 + C203 的路径分离）。

## 7. Claims（⊂ t6_2_claims.json）

C201 SUPPORTED / C202 SUPPORTED / C203 SUPPORTED / C204 SUPPORTED /
C205 PARTIALLY_SUPPORTED / C206 SUPPORTED / **C207 NOT_SUPPORTED**（预注册"修复"读法；
替代机制描述见 C202）。

## 8. Gate 结果

见 `t6_2_gates.json`（G9 为 nan 感知校验：FAILED_EXIT 在 validation 的空组单元格合法）。
