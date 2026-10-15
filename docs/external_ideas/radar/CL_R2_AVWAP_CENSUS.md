# CL-R2 AVWAP Support-First 普查（最终版，census only）

首轮脚本自动版本（判 INSUFFICIENT_SUPPORT_REVIEW）保留于文末；最终结论以下方两次普查合并为准。

## 普查结论

**G1 构造有效性：AVWAP 在未复权实际价格空间内成立**，条件均为事前冻结处理规则：

1. volume 单位确认为**手（100 股）**，AVWAP 必须为 `Σamount / (Σvolume × 100)`；
2. 修正后 AVWAP 与未复权 OHLC4 偏离：中位 0.43%，P90 0.72%（475/477 episodes 可测）——口径一致；
3. **主分析空间 = 未复权**：`gap(T) = close_unadj(T) / AVWAP(T0→T) − 1`，分子分母同在实际成交价空间，构造上不受复权因子影响；
4. episode 内真实除权断裂（因子偏离 >2%）占 27.7%（132/477）：**单列为敏感性子集**，绝不与稳定窗混合或静默丢弃（预注册条款执行）。

## 数据可得性（Support-First 字段）

| 项 | 值 |
|---|---|
| 样本 | 84 股（frozen universe，sha 083ca9ef…） |
| episodes（CD-5 L4 冻结文件） | 477；中位时长 95 日（P10 55.6，P90 442.8），<6 日仅 2 个 |
| amount 覆盖 | 中位 100%；P10 99.0%；<95% 的 episode 21 个（4.4%） |
| volume 覆盖 | 中位 100%；无 <95% episode |
| 不可读文件 | 0 |
| 单位检验 | (amount/volume)/OHLC4 中位 99.97（22,742 抽样日）→ 手 |
| episode 内因子偏离（自起点 max） | 中位 0.73%，P90 6.2% |
| 因子稳定性分类 | <0.5%：207；0.5–2%：137；>2%（真实除权）：132（27.7%） |

## 首轮普查的两个数据合同发现（存档）

1. naive AVWAP（未乘 100）相对 OHLC4 偏离 ~99 倍 → 单位错误，若未发现会直接污染全部 gap 值；
2. 首轮以 1e-6 容差数"因子断裂"得 75%——为价格 2 位小数存储的舍入噪声；改按幅度分类后真实断裂 27.7%。**计数≠幅度，普查必须分清。**

## 裁决

- 主分析集：344 个稳定/小偏离 episode（因子 max 偏离 ≤2%）；
- 敏感性集：132 个真实断裂 episode 单独报告；
- amount 覆盖 <95% 的 21 个 episode：fail-closed 标记，不填零；
- **G1 = PASS（限未复权空间 + 上述分集规则）**；
- G2/G3（独立性与行为一致性）尚未开始，本轮未读任何结果变量。

产物：`data/cl_radar/r2_avwap/census.json`、`census2.json`；脚本 `scripts/cl_r2_avwap_census.py`、`cl_r2_avwap_census2.py`。

---

## 附：首轮自动生成版本（存档，已被上方修正取代）

- sample: 84 stocks, sha 083ca9ef0292…
- episodes audited: 477（CD-5 L4, 冻结文件）
- 首轮 verdict: INSUFFICIENT_SUPPORT_REVIEW（触发原因即上述两项数据合同问题）

| 项 | 值 |
|---|---|
| duration_days | median=95；p10=55.6；p90=442.8；min=1；max=986；below_min_window_6=2 |
| amount_coverage | median=1.0000；p10=0.9899；episodes_below_0.95=21 |
| volume_coverage | median=1.0000；p10=1.0000；episodes_below_0.95=0 |
| adjustment_factor_breaks（1e-6 容差，舍入噪声） | episodes_with_any_break=360；break_frac_median=0.9833 |
| avwap_vs_unadj_ohlc4_deviation（未修正单位） | median=99.0046；p90=99.1047；n=475 |
