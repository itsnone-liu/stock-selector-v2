# Capital Logic Bridge B1 — 离线机制验证报告

## 1. 裁决

**NULL / 不支持“CD-5 成本状态条件性提高推进效率 λ”的机制假说；不判定为反向。**

原始日观测存在很小的状态差异，但差异在股票内配对和时间分层下不稳定，且与既有量价/流动性测量高度重叠，尚不足以把 λ 解释为独立的“筹码状态 → 价格推进效率”机制。本结果不修改生产体系，也不授权接入决策链。

## 2. 实验与数据审计

- Protocol：`capital-bridge-b1-v1`
- 预注册：`docs/external_ideas/radar/BRIDGE_B1_PREREGISTRATION.md`
- 样本：Phase A 冻结 universe84，84 个唯一代码；SHA256 `083ca9ef0292310aad2415843e8756511b2d74682abb9b1d4b2f897fc0e026d6`
- 行情：CD full-market qfq OHLC、unadjusted volume
- 成交额：`data/r2/market_ext`，84/84 覆盖，amount 元
- CD-5 旁路：qfq `(H+L+C)/3`、unadjusted volume、episode running 50-bin weighted histogram、P25/P50/P75；全部是 `model_derived`
- Episode：476 个，按 `data/cd/l4_episodes.json.gz` 的 start/end 截取
- 有效观测：77,355 行；错误：0
- 位置计数：below 31,070；inside 35,528；above 10,757
- 机器可读输出：`data/cl_radar/bridge_b1/observations.csv.gz`、`analysis_summary.json`
- 脚本：`scripts/cl_bridge_b1.py`、`scripts/analyze_bridge_b1.py`

## 3. 冻结指标

20 交易日窗口内：`OF=amount×sign(Δqfq_close)`；`lambda_raw` 为无截距 `Δqfq_close~OF`；`lambda_norm` 为无截距 `return~OF/ADV20`；Amihud 为 `mean(abs(return)/amount)`；`impact_beta` 为 `log(abs(return))~beta×log(amount/ADV20)` 的探索斜率。疑似单价/涨跌停日、无效 amount、零收益等被标记并排除，窗口至少 15 个有效日。

## 4. 主要结果

| cost position | λ_norm 中位数 | λ_norm 截尾均值 | Amihud 中位数 | volume-below 中位数 | impact β 中位数 |
|---|---:|---:|---:|---:|---:|
| below | 0.017659 | 0.019147 | 1.295e-10 | 0.1014 | 0.9523 |
| inside | 0.017097 | 0.018912 | 1.213e-10 | 0.4617 | 0.9573 |
| above | 0.017065 | 0.019296 | 1.382e-10 | 0.9689 | 0.9639 |

原始 pooled 数据中 below 的 λ 中位数略高于 above，但差异很小；Amihud 的 above 高于 below，说明状态分层与普通流动性/量价比测量存在重叠。

### 时间稳定性

| 时段 | below | inside | above | below−above |
|---|---:|---:|---:|---:|
| 2021–22 | 0.019311 | 0.017896 | 0.017238 | +0.002073 |
| 2023–24 | 0.017105 | 0.016646 | 0.016225 | +0.000880 |
| 2025–26 | 0.017341 | 0.017054 | 0.017526 | −0.000185 |

方向在 2/3 时段符合 below > above，但第三时段反向；按预注册的稳健性门不能升级为支持。

### 股票内配对

- 84/84 股票同时拥有 below 与 above 状态
- 每股票状态中位数的 `below−above`：中位数 **−0.0003143**，均值 **−0.0007049**，P10 **−0.00605**，P90 **+0.00360**
- 等权股票状态中位数：below 0.017552；inside 0.017108；above 0.017236
- `volume_below_current_price_ratio` 与 λ_norm Spearman：**−0.0294**
- 成本带宽与 λ_norm Spearman：**+0.3707**
- distance-to-center 与 λ_norm Spearman：**−0.1125**

股票作为基本重复单位时，below 的 pooled 优势消失并略为反向。

### 边际冲击斜率

impact β 中位数为 below **0.9523**、inside **0.9573**、above **0.9639**。差异很小，没有显示稳定、独立的筹码状态曲率变化；探索性 β 不改变主裁决。

## 5. 与既有“量价比”假说的重叠

1. `lambda_norm` 本身以 `amount/ADV20` 标准化，已经是成交额—价格响应的量价工具。
2. Amihud comparator 与状态排序存在重叠，状态效应可能只是流动性差异的另一种表示。
3. `volume_below_current_price_ratio` 与 λ 的单调相关很弱（−0.0294），且 pooled 状态排序在股票内配对后不稳。
4. 本轮尚未证明新增的条件交互：“CD-5 成本/历史成交价状态 → 独立于量价比的冲击效率”。

## 6. 预注册裁决

- 覆盖充分：84 股票、476 episode、77,355 观测
- 数据质量：84/84 amount 文件，0 运行错误
- 方向：pooled 时间分层为 2/3，但股票内中位差为负
- 结论：**NULL / 机制未成立**，不是 REVERSE

NULL 只表示本次冻结构造没有证明条件机制，不表示 CD-5 成本上下文或 λ 永久无价值。当前不进入第二层决策价值实验；未来若重开研究，必须先做股票内/episode 内识别、市场/波动控制、显式状态×成交额交互和正式嵌套量价比比较。

## 7. 边界

全程未修改生产特征、CD-5 文件、决策门、Shadow 链或现有参数。该报告是离线机制研究结果，不是交易结论。
