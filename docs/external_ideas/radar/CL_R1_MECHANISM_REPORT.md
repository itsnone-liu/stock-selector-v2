# CL-R1 — a-stock-data-quant 成本分布机制对照报告

## 裁决

**A：部分通过（源码算法可复原；默认 CLI 数据合同不通过）。**

**B：初步支持供应压力与推进效率存在可观测关联，但尚未证明外部复杂模型相对 CD-5 的独立增量。**

因此当前裁决是：**保留为机制参考，暂不进入生产，也不进入 Factor→Return/策略回测。** 若继续，只进入严格的股票/episode 聚类与供应压力事件验证；不直接接入 M3。

## 1. 版本与边界

- 仓库：`jangviktor-web/a-stock-data-quant`
- audited commit：`0944c726f19aa041ecf2d93ac7357223d061823d`
- 核心源码：`/tmp/a-stock-data-quant/lib/chip_distribution.py`
- 样本：84 股冻结 universe，SHA `083ca9ef0292310aad2415843e8756511b2d74682abb9b1d4b2f897fc0e026d6`
- 2,377 个 episode-local PIT 截止快照
- 已连接既有 B1 λ：2,377 个快照；其中 2,327 个有有效 `lambda_norm`
- 全程不使用未来收益，不修改生产体系

## 2. 源码审计结论

算法实现：每日用 `1-turnover/100` 衰减；在 `[low,high]` 的 bin 交集内按高斯核分配成交量；成本中心优先为夹紧后的 `amount/volume`，否则 `(H+L+C)/3`；默认 80 bins；输出 average cost、price≤current close 比例、top-5 concentration。

## 3. 数据合同审计

默认 `cmd_chip` 对缺字段静默写 0。新浪与腾讯 qfq 日线只构造 OHLCV；mootdx 归一化 K 线也只输出 OHLCV。故默认 CLI 很可能实际运行：`turnover=0`（不衰减）、`amount=0`（VWAP 不生效）。此外，全局 high/low 建 bin 的实现只有在输入已经截断至 T 时 PIT 安全；批量全历史输入会造成未来边界污染。

## 4. M0–M3 固定对照

- M0：CD-5 exact running 50-bin point HLC/3
- M1：M0 + turnover decay
- M2：turnover decay + `[L,H]` Gaussian + HLC/3
- M3：turnover decay + Gaussian + VWAP center + 80 bins

输出：`data/cl_radar/r1_chip_ablation/ablation.csv.gz`、`summary.json`。

| 指标（中位数） | M0 | M1 | M2 | M3 |
|---|---:|---:|---:|---:|
| average cost | 8.574 | 8.465 | 8.550 | 8.679 |
| price≤close ratio | 0.414 | 0.438 | 0.362 | 0.206 |
| top-5 concentration | 0.616 | 0.653 | 0.253 | 0.197 |
| supply within +2% | 0.056 | 0.089 | 0.105 | 0.107 |
| supply within +5% | 0.142 | 0.197 | 0.219 | 0.254 |
| supply within +10% | 0.249 | 0.319 | 0.350 | 0.438 |
| all overhead | 0.586 | 0.562 | 0.638 | 0.794 |

这些是定义差异，不是优劣结论。

## 5. PriceImpact 机制结果

与既有 20 日标准化 λ 的 Spearman 相关（2,327 个有效快照）：

| 模型 | +2% supply | +5% supply | +10% supply | overhead total |
|---|---:|---:|---:|---:|
| M0 | -0.192 | -0.175 | -0.162 | +0.011 |
| M1 | -0.137 | -0.119 | -0.103 | -0.000 |
| M2 | -0.239 | -0.256 | -0.251 | -0.064 |
| M3 | -0.256 | -0.266 | -0.282 | -0.083 |

84 股票等权聚合后，`+5% supply` 与股票平均 λ 的相关为：M0 **−0.576**、M1 **−0.373**、M2 **−0.589**、M3 **−0.626**。

方向符合“上方历史成交密度越高，单位成交额推进效率越低”的供应压力解释；但这是关联，不是因果，也没有完成 episode-clustered inference 或控制规模、波动、成交额后的独立交互模型。

M3 相对 M0 的独立增量尚不清楚：M0 已有方向，M1 的 turnover decay 反而减弱 pooled 相关，M2/M3 的高斯/价格分布变化增强了近价供应与 λ 的负相关，但 M3 同时改变 VWAP 与 bins，不能归因于单一组件。

## 6. 下一阶段门槛

进入 R1-B 前必须完成：

1. 每次组件增量只改变一个定义，并确保 M2/M3 的 grid 口径严格可比；
2. 对 84 股票、476 episode 做股票/episode 聚类或等权 bootstrap；
3. 控制 log ADV、波动、价格尺度和时期/市场状态；
4. 预冻结回撤卖压、突破难度、λ 的供应压力事件定义；
5. 比较 M0/M1/M2/M3 的增量，而非只看 pooled Spearman。

若控制后 M0 已足够、M1–M3 无稳定增量，停止复杂化；若只有某一组件稳定改善供应/PriceImpact，只保留该组件，不整体集成外部仓库。

## 7. 禁止解释

`profit_ratio` 不是真实获利筹码比例；`top_concentration` 不是主力控盘；不识别参与者身份或意图；不把本报告转化为交易因子或生产规则。
