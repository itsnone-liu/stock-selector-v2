# 批次5语义规范：复权收益接入与正负路径分析（v5 待审）

> 版本链：v1(d4b43ac)→v2(2f9ceee)→v3(4457bea)→v4(b00c52b)→本版。取代
> `docs/research/strategy_contract/POSITIVE_NEGATIVE_ANALYSIS.md` 旧稿（保留历史参照）。
> v5 修订：①path_family 两层化（θ3 移入 path_subtype）；②N_master/N_evaluable_h/
> N_censored_h 分母体系；③staged K2/K4 共同终点钉死为 T1 后第 h 日（保持 v5
> 冻结语义）；④复权价值唯一表达（因子比式，禁股数账本双重计算）；⑤稀疏门禁
> 可执行阈值（裁定点G）；⑥structure_broken_asof_20d 时间边界、group_eventual
> 删失赋值算法、RC 严格 >、类目改名 reclaim_no_new_high / reclaim_then_fade、
> 期末跌幅正值公式与 ≤/> 边界统一。

## 0. 冻结基线依赖

| 依赖 | 版本 |
|---|---|
| 周线准入 | `e2cf0918238fc95c` |
| 回调事件 | pullback `68cad4022bec6a8b`｜`pullback_stage2_v1`｜`right_censored_v2` |
| 生命周期 | `7f2c8dda08801d27`（55,646 段；不重跑） |
| 入场回放 | v5 冻结：`entry_replay_stage4_v4`→`v5`，hash `8ebdc40bacd5bcec`，222,584 行（不重跑） |

批次5 追加三层（不改冻结层）：`adjustment_v1` → `retcalc_v1` → `posneg_v1`。

## 1. 形态：双时点标签 + 右删失状态

| 字段 | 定义 |
|---|---|
| `group_eventual_status` | `complete` / `censored`（生命周期是否因数据结束右删失） |
| `group_eventual` | **确定算法**：①censored 且 T3 已出现 → `G3`（已确定，不会再变）；②censored 且 T1/T2 已出现但无 T3 → `unknown_censored`（未来可能再上攻）；③censored 且只有 T1 → `unknown_censored`（未来可能回调/再上攻）；④complete → 按全部事实判 G1（无 T2）/G2（有 T2 无 T3）/G3（有 T3） |
| `group_asof_20d` | 截至突破后第 20 交易日已形成的形态；仅当突破后完整观察 20 日（`outcome_20d_complete=TRUE`）为确定标签，否则 `unknown_censored` |
| `t2_from_breakout_days` / `t3_from_breakout_days` / `t2_to_t3_days` | 连续交易日数（未出现 null），保存不分析 |

- 守恒门禁：`group_eventual` 四值行数之和 = 27,422；`group_asof_20d` 同
- 事前识别层只用 `group_eventual ∈ {G1,G2,G3}`（即 status=complete 的确定行）
  与 `group_asof_20d` 确定标签行
- 三形态是入场机会结构标签，绝不作为策略比较筛选条件

## 2. 行情结局：事件序决策树（path_family 两层）

以复权价 `P_adj`、`P_bo = P_adj(breakout_day)`、窗口 = 突破后第 1..20 交易日。

**基础事件（精确）**：

```
eps        = 1e-9（相对容差）
strict_new_high = P_adj > P_bo × (1 + eps)
reclaim    = P_adj >= P_bo
NH         = 窗内首个 strict_new_high 日（可能不存在）
TR         = 窗内首个 argmin(P_adj) 日
RC         = 首个日序严格 > TR 的 reclaim 日（>，不含 TR 当日；可能不存在）
D          = max(0, 1 − min(P_adj[1:20]) / P_bo)      # 连续回撤，始终上涨 D=0
E          = max(0, 1 − P_adj(end) / P_bo)             # 期末跌幅（正值公式）
```

**决策树（严格按序，首次命中即停；path_family 六类互斥完备，不依赖任何 θ）**：

```
1. 窗口不完整                                → right_censored
2. 窗内从未 reclaim（max(P_adj[1:20]) < P_bo）→ never_reclaim
3. RC 存在（最低点严格之后曾收复）:
     3a. NH 不存在                           → reclaim_no_new_high
     3b. NH 存在且 NH >= TR                   → pullback_new_high      # 含 D=0 单边延续
     3c. NH 存在且 NH < TR                    → high_then_pullback_reclaimed
4. RC 不存在，但窗内曾 reclaim                → reclaim_then_fade
```

**path_subtype（θ 仅在此层，辅助）**：

```
never_reclaim 内部：
    E > 0.15   → breakout_failure
    E <= 0.15  → breakout_unconfirmed
其余族 subtype=null
```

- 类目命名不暗示事件不存在：`reclaim_no_new_high` 覆盖横盘恒等（D=0 无回调）
  与先跌后收复；`reclaim_then_fade` 覆盖"曾站上（含非严格）后回落未归"
- `right_censored` 不进任何结局分母
- 门禁：非删失样本恰居一类；六情形构造测试（单边上涨/横盘恒等/先涨后跌/
  先跌后涨/同日并列/期末恰收复）逐一断言唯一归类

### 2.1 辅助切片与主结果变量

| 字段 | 定义 |
|---|---|
| `path_family` | 上表六类（主标签，θ 无关） |
| `path_subtype` | never_reclaim 族内 breakout_failure / breakout_unconfirmed（θ3=0.15） |
| `drawdown_bucket_abs` | D 切片：≤3% / 3–10% / >10%（辅助） |
| `below_break_bucket_abs` | never_reclaim 族 E 切片：≤15% / >15%（辅助；与 subtype 边界一致：E>0.15 为 failure 侧） |
| `D`（连续） | 原值 |
| `D_atr` | `D / ATR%_prev`，`ATR%_prev = ATR14_adj / P_adj(prev)`（比例除以比例）；ATR14 在复权 OHLC 上计算；取突破前一日的确定值；前 14 日不全 → null 并披露 |
| `structure_broken_asof_20d` | **时间边界 = 突破后第 20 交易日内**是否触发结构破坏（v5 判定语义）；禁止把 120 日生命周期的最终破坏状态混入 20 日结果（未来信息） |

θ 不决定任何 path_family；不依据结果回调边界。

## 3. 策略比较口径

**总体与分母体系（阻塞点2 修订）**：

```
N_master      = 27,422                # 突破生命周期母总体（守恒数，非每格分母）
N_evaluable_h = 突破后可完整观察 h 日的行数（随 h 变化）
N_censored_h  = N_master − N_evaluable_h
```

- K2_h/K3_h 均值分母 = `N_evaluable_h`（未成交=0 计入分子；右删失=null 
  **不进分母**——未成交与删失严格分开）
- 无突破的 28,224 段为独立对照池，不进入策略排名；报告披露 N_master、
  N_evaluable_h、N_censored_h 与每策略成交数
- "未成交"= 已突破但该等待策略未成交

| 口径 | 精确定义 |
|---|---|
| K2_h | 全生命周期策略收益：`N_evaluable_h` 全体计入。已成交部分持有至**该策略自己的共同终点**（见下）；未成交收益 0。策略级 = 分母内资金加权平均 |
| K3_h | 相同终点收益：统一在**突破后第 h 交易日**估值；未成交资金现金 0 |
| K4_h | 条件成交诊断：仅已成交事件，从成交起按策略共同终点估值 |

**共同终点规则（阻塞点3 修订，单一策略语义不因口径改变）**：

| 策略 | K2/K4 的持有终点 |
|---|---|
| direct_chase / wait_first_pullback / wait_support_hold | 各自**实际成交日后第 h 交易日**（单笔） |
| **staged_entry** | **T1 成交后第 h 交易日**（组合共同终点，保持 Stage4 v5 冻结语义）；T2/T3 仅在终点前实际持有相应天数；**终点后出现的批次保持现金**（0 收益计入） |

- h ∈ {1, 3, 5, 10, 20}，三口径 × 全期限 × 双视角输出
- 边界细则：K3 终点后才成交→该窗口现金 0；恰在终点日成交→计费用无价格
  收益；第三批 K3 终点后出现→该 0.40 资金现金；持有终点超出数据→删失
  （null，不进分母）
- 未投入现金收益按 0（裁定C）；3.5% 上限不动

## 4. 事前识别层：三时点 + 时间外验证

| 时点 | 可用信息边界 |
|---|---|
| 突破日 | 当日及之前量价/位置（不含 t2/t3 之后任何行情） |
| 首次缩量回调日 | **仅当日已存在**信息：缩量度、距突破回撤、距结构支撑距离。**禁用**止跌信息 |
| 支撑止跌确认日 | 仅已出现止跌样本；止跌确认及之前信息 |

- 预测目标：`group_asof_20d`（确定标签行）与 `group_eventual`（G1/G2/G3 行）
  对照；缩量日/止跌日 → G2 vs G3
- 滚动时间外验证：前半年定单变量边界→后续验证→逐半年稳定性表
- 2024–2026 全部为开发样本；结论不得反写信号准入

## 5. 复权因子层（adjustment_v1）

### 5.1 因子语义

- 累计总收益复权因子 `F_t`（后复权方向）：`P_adj = P_raw × F_t`
- 现金分红再投资并入；送转股按股本变动并入；除权日生效
- 无公司行动 → 延续前值（**不是缺失**）；新上市 F=1；停牌沿用前值
- 严格缺失 = 按个股真实行情日期展开后仍有空洞 → **fail-fast** + 股票清单

### 5.2 因子源与容差分级

1. 本地实证先行（盘点实际公司行动文件，不预设 gpcw；覆盖实证报告）
2. 外部成熟前复权序列交叉验证

| 层 | 容差 |
|---|---|
| 内部算法重复计算 | `1e-9` |
| 外部交叉验证 | 除权日逐股一致；收益误差按源精度容差（如 `1e-4`） |
| 人工公司行动样本 | 分红/送转/拆分 ≥30 只，股数与价值守恒对照 |

两源皆不可靠（裁定B）：开发严格失败；正式排除须清单+板块/年份集中度检查。

### 5.3 复权价值唯一表达（阻塞点4 修订）

**冻结唯一表达（因子比式），禁止与股数账本混用**：

```
gross_terminal_value = invested_raw_notional × P_adj(exit) / P_adj(entry)

 invested_raw_notional = 该笔实际成交的原始金额（raw_price × 成交股数，含买入滑点）
 R_net = (gross_terminal_value − 卖出费用) / (invested_raw_notional + 买入费用) − 1
```

- 分红/送转/拆分**全部**由 `P_adj/P_adj(entry)` 因子比承载，实现中**不得**
  再维护真实股数或现金分红账本（否则双重计算公司行动）
- 买卖费用按实际 raw notional（含单笔最低佣金）计
- 分批策略逐批按上式，再加未投入现金，组合资金加权
- 人工公司行动样本验证 = 上式结果与"原始价+股数账本"的**外部手工对照**
  （账本仅用于验证，不进生产路径）

## 6. 统计口径与稀疏分组门禁

- 窗口 h ∈ {1, 3, 5, 10, 20}；主标签 = path_family；净收益正/负/中性并列
  （中性带作用在毛收益上）
- 不确定性：股票块与日期块有放回 bootstrap 双套区间并列；报告块数
- **稀疏分组门禁（可执行阈值，具体数字=裁定点G，跑结果前写入 run_spec）**：

| 参数 | 语义 |
|---|---|
| `min_events` | 格内事件数下限；不足 → 只描述，不输出"更优" |
| `min_unique_stocks` | 格内独立股票数下限；不足 → 只描述 |
| `min_signal_dates` | 格内独立信号日期数下限；不足 → 只描述 |
| `min_bootstrap_blocks` | 股票块/日期块各自块数下限；不足 → 不做区间结论 |

- 每格披露事件数、股票数、信号日期数；**不按结果合并小组**
- 分层最低要求：group_asof_20d（确定标签）、path_family、期限、视角；
  行业/大盘仅解释层
- 删失：仅 `outcome_{h}d_complete=TRUE` 进对应期限分母；删失率逐格披露

## 7. 产物 schema

```
output/research/adjustment_v1/   # F_t 表 + 源实证报告 + 交叉验证对照 + MANIFEST(源SHA256)
output/research/retcalc_v1/      # K2/K3/K4(1/3/5/10/20) + path_family/path_subtype
                                 #   + D/D_atr + bucket 字段 + structure_broken_asof_20d
                                 #   + group_eventual(_status)/group_asof_20d + 天数字段
output/research/posneg_v1/
  posneg_panel:      上述全部 + N_evaluable_h/N_censored_h 标记 + strategy + view
                     + R_net(因子比式) + complete flags
  posneg_summary:    形态×结局×策略×视角×期限 效应量、双块区间、
                     事件/股票/日期数、删失率、稀疏门禁标记
  identify_breakout_day / identify_first_shrink_day / identify_stabilization_day
```

RULE_VERSION：`adjustment_v1`、`retcalc_stage5_v1`、`posneg_stage5_v1`。
复权验证通过前，分析层不输出"最优策略"结论字段。

## 8. 门禁与验收

1. 因子层闭合：行数闭合、fail-fast 处置符合裁定B、除权日外部一致、
   人工样本股数/价值守恒（验证用账本 vs 生产因子比式）
2. 等价性：无除权样本内部重算 `1e-9`；外部按源精度容差
3. 标签守恒：`group_eventual` 四值之和 = 27,422；`group_asof_20d` 同；
   path_family 非删失互斥恰居一类；六情形构造测试逐一断言
4. 口径完整：三口径 × 5 期限 × 双视角全输出；N_evaluable_h 逐期限披露；
   staged 共同终点=T1 后 h 日有专项测试（终点后批次现金）
5. 稀疏门禁生效：阈值在 run_spec 中冻结后不可视结果调整
6. 阶梯：50×3mo → 300×1y → 全量；每级四项核对表

## 9. 裁定点状态

| # | 状态 |
|---|---|
| A–F | 已闭合（见 v4 记录；E 类名 `high_then_pullback_reclaimed`，F 同日/非 strict 规则固化） |
| **G（新增）** | `min_events / min_unique_stocks / min_signal_dates / min_bootstrap_blocks` 的具体数字——**必须在任何结果跑出前裁定并写入 run_spec**；建议初值 30 / 10 / 5 / 30（可裁） |

G 裁定后本版冻结为 `posneg_stage5_v1` 语义基线。
