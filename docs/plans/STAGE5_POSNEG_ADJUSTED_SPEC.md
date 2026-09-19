# 批次5语义规范：复权收益接入与正负路径分析（v4 冻结候选）

> 版本链：v1(d4b43ac)→v2(2f9ceee)→v3(4457bea)→本版。取代
> `docs/research/strategy_contract/POSITIVE_NEGATIVE_ANALYSIS.md` 旧稿（保留历史参照）。
> v4 修订：①结局树改为收复/新高事件序（同日并列、横盘、单边、先涨后跌、
> 先跌后涨全部唯一归类，E 采纳独立类 `high_then_pullback_reclaimed`）；
> ②右删失形态 `unknown_censored`；③K2/K3 总体钉死为 27,422 突破样本；
> ④ATR 量纲修正（ATR% 比例相除，复权 OHLC，前一日值）；⑤path_family 与
> θ 切片彻底分离；⑥稀疏分组门禁。

## 0. 冻结基线依赖

| 依赖 | 版本 |
|---|---|
| 周线准入 | `e2cf0918238fc95c` |
| 回调事件 | pullback `68cad4022bec6a8b`｜`pullback_stage2_v1`｜`right_censored_v2` |
| 生命周期 | `7f2c8dda08801d27`（55,646 段；不重跑） |
| 入场回放 | v5 冻结：`entry_replay_stage4_v5`，hash `8ebdc40bacd5bcec`，222,584 行（不重跑） |

批次5 追加三层（不改冻结层）：`adjustment_v1` → `retcalc_v1` → `posneg_v1`。

## 1. 形态：双时点标签 + 右删失状态

| 字段 | 定义 |
|---|---|
| `group_eventual` | 生命周期**完整观察到结局**时的最终形态（G1/G2/G3） |
| `group_eventual_status` | `complete` / `censored`：生命周期是否因数据结束右删失 |
| `group_eventual`（censored 且缺后续阶段时） | `unknown_censored`——当前无 T2 不代表不会回调，无 T3 不代表不会再上攻；**不得**当 G1/G2 负样本 |
| `group_asof_20d` | 截至突破后第 20 交易日已形成的形态；仅当突破后完整观察 20 日才是确定标签，否则 `unknown_censored` |
| `t2_from_breakout_days` / `t3_from_breakout_days` / `t2_to_t3_days` | 距突破日/间隔的连续交易日数（未出现为 null），保存不分析 |

- 守恒门禁：`group_eventual` 取值为 G1/G2/G3/unknown_censored 的行数之和
  = 27,422；`group_asof_20d` 同样 27,422
- 事前识别层**只能用**结局完整观察的样本（G1/G2/G3 确定标签）作训练/验证
- 20 日结局主用 `group_asof_20d` 交叉（仅确定标签行）；`group_eventual` 
  交叉表同出作对照，两表禁止互相替代
- 三形态是入场机会结构标签，绝不作为策略比较筛选条件（事后选择偏差）

## 2. 行情结局：收复/新高事件序决策树（path_family）

以复权价 `P_adj`、`P_bo = P_adj(breakout_day)`、窗口 = 突破后第 1..20 交易日。

**基础事件（精确）**：

```
eps              = 相对容差（价格精度，取 1e-9；消除"横盘恒等于突破价"被当新高）
strict_new_high  = P_adj > P_bo × (1 + eps)          # 严格新高
reclaim          = P_adj >= P_bo                      # 收复/站稳突破价（非新高）
NH               = 窗内首个 strict_new_high 日        # 可能不存在
TR               = 窗内 argmin(P_adj) 日（首个最低点日）
RC               = TR 之后首个 reclaim 日             # 可能不存在
D                = max(0, 1 − min(P_adj[1:20]) / P_bo)  # 始终上涨 D=0（不取绝对值）
```

**决策树（严格按序，首次命中即停；七类互斥完备）**：

```
1. 窗口不完整（outcome_20d_complete=FALSE）
     → right_censored
2. 窗内从未 reclaim（max(P_adj[1:20]) < P_bo）
     2a. P_adj(end) <  P_bo×(1−θ3)  → breakout_failure
     2b. P_adj(end) >= P_bo×(1−θ3)  → breakout_unconfirmed
3. RC 存在（最低点之后曾收复突破价）
     3a. NH 不存在（从未严格新高）   → pullback_reclaimed        # 跌后收复，未创新高
     3b. NH 存在且 NH >= TR          → pullback_new_high         # 先回调后新高（D=0 含单边延续）
     3c. NH 存在且 NH < TR           → high_then_pullback_reclaimed  # 先新高后回调再收复（原裁定E）
4. RC 不存在（最低点后未再收复），但窗内曾 reclaim（含 strict 新高）
     → fade_after_high              # 曾站上突破价后回落未归
```

- 分支 3b 的 `NH >= TR` 含同日（D=0 单边上涨 NH=TR=day1 归 3b，D=0 切片即
  "直接延续"）；分支 4 按"曾站上"（reclaim，不要求 strict）判冲高回落——
  与 v3 的重叠/顺序错误在此消除
- `right_censored` 不进任何结局分母
- **主标签 = `path_family`（上述七类），不依赖 θ1/θ2/θ3**；θ3 仅在
  never-reclaim 族内部作失败/未证实切片（主结论同时披露族级合并口径）
- 门禁：非删失样本恰居一类；分支覆盖率逐类披露；构造性单元测试覆盖
  单边上涨/横盘恒等/先涨后跌/先跌后涨/同日并列/期末恰收复六情形

### 2.1 辅助切片与主结果变量（θ 与主标签彻底分离）

| 字段 | 定义 |
|---|---|
| `drawdown_bucket_abs` | D 的描述性切片：≤3% / 3–10% / >10%（辅助） |
| `below_break_bucket_abs` | never-reclaim 族期末跌幅切片：<15% / ≥15%（辅助，即 θ3） |
| `D`（连续） | 原值 |
| `D_atr` | `D / ATR%_prev`，其中 `ATR%_prev = ATR14_adj / P_adj(prev)`——**比例除以比例**；ATR14 在**复权 OHLC** 上计算（避免历史除权跳空污染 14 日真实波动）；取**突破日前一日已确定**的值（无未来信息）；`ATR%_prev` 缺失（前 14 日数据不全）→ `D_atr=null` 并披露 |
| `structure_broken` | 是否触发 v5 冻结的结构破坏判定 |

θ1/θ2/θ3 不再决定任何主标签；不依据本次收益结果回调边界。

## 3. 策略比较口径

**主总体 = 27,422 个突破生命周期**（无突破的 28,224 段没有突破日、无法定义
K3 共同终点，作为独立对照池**不进入**四种入场策略排名）。
"未成交"= 已发生突破、但对应等待策略未成交。报告同时披露 27,422 总体数与
每策略实际成交数。

| 口径 | 精确定义 |
|---|---|
| K2_h | 全生命周期策略收益：27,422 全体计入。已成交部分从各自实际成交日起持有 h 日；未成交生命周期收益记 0（现金）。策略级 = 全体资金加权平均 |
| K3_h | 相同终点收益：统一在突破后第 h 日估值。到该日仍未成交的资金保持现金（0）；已成交部分按该日复权持仓价值计 |
| K4_h | 条件成交诊断：仅已成交事件，从各自成交日起持有 h 日 |

- h ∈ {1, 3, 5, 10, 20}，三口径 × 全期限输出
- 边界细则（冻结）：终点后才成交→该窗口现金 0；恰在终点日成交→计费用、
  无价格收益；第三批终点后出现→该 0.40 资金现金；持有 h 日超出数据→
  该格删失不进分母并披露
- 未投入现金收益按 0（裁定C）；staged 全口径按组合净值（复权、30/30/40、
  逐批资金价值式）；3.5% 上限不动

## 4. 事前识别层：三时点 + 时间外验证

| 时点 | 可用信息边界 |
|---|---|
| 突破日 | 当日及之前量价/位置（不含 t2/t3 之后任何行情） |
| 首次缩量回调日 | **仅当日已存在**信息：缩量度、距突破回撤、距结构支撑距离。**禁用**止跌信息 |
| 支撑止跌确认日 | 仅已出现止跌样本；止跌确认及之前信息 |

- 预测目标：`group_asof_20d`（确定标签行）与 `group_eventual`（complete 行）
  对照；缩量日/止跌日 → G2 vs G3
- 滚动时间外验证：前半年定单变量分层边界→后续验证→逐半年稳定性表
- 2024–2026 全部为**开发样本**，任何"预测能力"结论须标注；不得反写信号准入

## 5. 复权因子层（adjustment_v1）

### 5.1 因子语义

- 累计总收益复权因子 `F_t`（后复权方向）：`P_adj = P_raw × F_t`；
  `R = (P_raw_1 F_1)/(P_raw_0 F_0) − 1`
- 现金分红再投资并入；送转股按股本变动并入；除权日生效
- 无公司行动 → 因子延续前值（**不是缺失**）；新上市 F=1；停牌沿用前值
- 严格缺失 = 按个股真实行情日期展开后仍有空洞 → **fail-fast** + 股票清单

### 5.2 因子源与容差分级

1. 本地实证先行（盘点实际公司行动文件，不预设 gpcw；产出覆盖实证报告）
2. 外部成熟前复权序列交叉验证

| 层 | 容差 |
|---|---|
| 内部算法重复计算 | `1e-9` |
| 外部交叉验证 | 除权日逐股必须一致；收益误差按源精度容差（如 `1e-4`）；显示值分/厘精度不要求 1e-9 |
| 人工公司行动样本 | 分红/送转/拆分 ≥30 只，股数与价值守恒逐一对照 |

两源皆不可靠（裁定B）：开发严格失败；正式分析若排除须列股票/原因/占比并
检查板块与年份集中度。

### 5.3 净收益：资金价值式

```
R_net = (复权后期末持仓价值 − 卖出费用) / (初始投入资金 + 买入费用) − 1
```

持仓价值按 `P_adj`（含分红再投资与送转股数变化）；费用按 raw_price 资金口径
（含单笔最低佣金）；分批逐批计算加未投入现金，组合资金加权。

## 6. 统计口径与稀疏分组门禁

- 窗口 h ∈ {1, 3, 5, 10, 20}；主标签=path_family；净收益正/负/中性为并列
  结果（中性带作用在**毛收益**上，禁止净收益重复扣成本）
- 不确定性：股票块与日期块有放回 bootstrap 双套区间并列；报告块数
- **稀疏分组门禁**：形态×结局×策略×视角×期限每格披露事件数、股票数、
  信号日期数；样本不足的格子**只描述不输出"更优"**；股票块或日期块数量
  不足时不做区间结论；**不按结果合并小组**
- 分层最低要求：group_asof_20d（确定标签）、path_family、期限、视角；
  行业/大盘仅解释层，不修改个股信号准入
- 删失：仅 `outcome_{h}d_complete=TRUE` 进对应期限分母；删失率逐格披露

## 7. 产物 schema

```
output/research/adjustment_v1/   # F_t 表 + 源实证报告 + 交叉验证对照 + MANIFEST(源SHA256)
output/research/retcalc_v1/      # K2/K3/K4(1/3/5/10/20) + path_family + D/D_atr/
                                 #   drawdown_bucket_abs + structure_broken
                                 #   + group_eventual(_status)/group_asof_20d + 天数字段
output/research/posneg_v1/
  posneg_panel:      上述全部 + strategy + view + R_net + complete flags
  posneg_summary:    形态×结局×策略×视角×期限 效应量、双块区间、事件/股票/日期数、删失率
  identify_breakout_day / identify_first_shrink_day / identify_stabilization_day
```

RULE_VERSION：`adjustment_v1`、`retcalc_stage5_v1`、`posneg_stage5_v1`。
复权验证通过前，分析层不输出"最优策略"结论字段。

## 8. 门禁与验收

1. 因子层闭合：行数闭合、fail-fast 处置符合裁定B、除权日外部一致、
   人工样本股数/价值守恒
2. 等价性：无除权样本内部重算 `1e-9`；外部按源精度容差
3. 标签守恒：`group_eventual`（含 unknown_censored）与 `group_asof_20d` 
   各 27,422；path_family 非删失互斥恰居一类；六情形构造测试全过
4. 口径完整：三口径 × 5 期限 × 双视角全输出；终点边界（当天成交/终点后
   成交/终点后 T3）有专项测试
5. 稀疏门禁生效：小格只描述、无块不区间、不合并
6. 阶梯：50×3mo → 300×1y → 全量；每级四项核对表

## 9. 裁定点终态

| # | 状态 |
|---|---|
| A | 采纳：θ 全部降为辅助切片（drawdown_bucket_abs / below_break_bucket_abs），主标签 path_family 不依赖 θ |
| B | 采纳：开发严格失败；正式排除须清单+集中度检查 |
| C | 采纳确认：未投入现金收益按 0 |
| D | 采纳：三时点独立 + 首版单变量 + 滚动时间外验证；2024-2026=开发样本 |
| E | 采纳：独立类，命名 `high_then_pullback_reclaimed`（分支 3c；可能只是收复突破价而非新高，名称不暗示新高） |
| F（新增，随 v4 固化） | 分支 3b 的 `NH >= TR` 含同日（D=0 单边归 pullback_new_high）；分支 4 按 reclaim（不要求 strict）判 fade_after_high |

全部裁定点已闭合。本版待用户确认后冻结为 `posneg_stage5_v1` 语义基线。
