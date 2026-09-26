# CSR-7 IMPLEMENTATION ERRATUM (narrow, pre-registered before Phase A rerun)

用户在 CSR-8 Phase A 审计（5f041b6）中指出四处协议文本/实现口径需要在重跑前定准。
本 erratum 只处理口径定义，不改变 CSR-7 冻结结构；全部条目在重跑 Phase A 之前登记，
不依据任何候选名单特征挑选定义（G1-E1 的阈值敏感性将在 manifest 中同时列出三档供审计）。

## G1-E1 "回撤修复 ≤3 次" operational definition

一次回撤修复（one recovery）= 状态机计数：
  - running peak P（窗口内截至当日的最高收盘，hfq）；
  - 进入回撤：close < P×(1−0.20)（幅度阈值 20%，选择依据=A 股惯例熊市阈值，
    事前声明，非数据驱动挑选）；
  - 修复完成：回撤发生后 close 首次 ≥ 该回撤起点的 P（回到起点高点）→ recovery += 1，
    状态机退出回撤；同一次回撤内的更深下探不重复计数；
  - episode 窗口结束时仍处于未修复回撤 → 该次不计入修复次数（计入"未修复回撤存在"标记，
    manifest 单列登记但不构成过滤条件）。
过滤：recovery_count ≤ 3。
敏感性登记（不作为选择依据，仅审计透明）：阈值 15% / 20% / 25% 三档下的
候选计数将并列写入 replay_manifest，主口径=20%。

## G1-E2 月粒度真实口径

废止 "month_granularity_trading_days=21" 的伪声明。G1 实际算法（冻结）：
  - 窗口起点=自然月切换后的首个交易日（calendar-month start）；
  - 最短/最长窗口长度=375 / 1250 交易日（18/60 个月的交易日近似）；
  - manifest 字段改为 g1_start_grid=calendar_month_first_trading_day、
    g1_window_min_days=375、g1_window_max_days=1250。

## G1-E3（连带）窗口内涨幅口径

max_gain = max_{窗口内 k}（close[k] / min_{窗口内 ≤k 的 close}）−1，顺序约束（先低后高），
hfq 收盘。已在代码与 manifest 一致，此处仅备案。

## G4-E1 group rule 与 anchor rule 权威关系

权威（authoritative）= case_selection.anchor_generation 详细规则：
  launch = 低波动段结束后 252 个交易日内，20 日滚动涨幅截面分位首次 ≥85% 的首日。
group rule 中"随后 12 个月涨幅分位 ≥85%"为简写笔误（erratum），不构成独立过滤条件；
gain_12m 仅用于多段唯一化（段后 12 个月涨幅最高，并列最早），允许 gain_12m < 0
（未启动成功不是 G4 的入选否定条件——入选=存在合格 launch 事件本身）。

## UNI-E1 universe 数目勘误

CSR-7 sampling_frame 文本 "5,241" 为旧口径残留；authoritative source =
config/universe_frozen.json（frozen_at 2026-09-21，count=5240，codes_sha256=521e146d…）。
Phase A 脚本增加硬 gate：set(per_stock codes) == set(universe_frozen codes)（精确集合相等，
非数量相等）。

## SAM-E1 分层重抽与余数规则精确化

- 触发重抽后仍为 seeded random（seed=20260925 连续 rng 流），不是组内指标 top-N：
  每年份桶内 seeded 均匀打乱后取前 quota 名；
- 余数名额=全局按组内规则指标值降序补足（跳过已选），跨桶不设上限——
  原 CSR-7 文本"余数按组内规则指标值降序分配到桶"按此解释执行；
- 重抽至多 1 次不变；重抽后仍单年 >50% 如实登记。

## SAM-E2 chosen / substitutes / excluded 守恒契约

final chosen 确定（含 redraw）之后：
  ordered substitutes = 同一 rng 流的后续序列中非 chosen 者，取 20 名（有序）；
  excluded = 候选全集 − chosen − substitutes（全量登记）。
三者两两互斥、并集=候选全集；sample_selection.json 必须包含三者并在写盘前通过
守恒断言（脚本内 gate，失败即 abort）。

## CODE-E1 canonical stock code

任何分组比较/membership 计算之前，所有代码统一为 canonical 格式 sh.XXXXXX / sz.XXXXXX
（G2 事件表读入时立即规范化）；membership register 用 canonical 集合重算，
并加集合守恒 gate（每股票的组集合与逐组名单反查一致）。

## REPLAY-E1 输入/输出哈希冻结

replay_manifest.json 必须包含：
  config/universe_frozen.json SHA256；
  output/research/t6/01_eclass/t6_1_per_event.parquet SHA256；
  data/t4/sector_map/csrc_industry_snapshot.json SHA256；
  per_stock 全体文件聚合 SHA256（排序文件名→逐文件 SHA256→拼接再 SHA256）；
  scripts/csr8_sample.py 全量 SHA256；
  output/research/csr/07_case_protocol/CSR_7_CASE_PROTOCOL.yaml SHA256；
  numpy / pandas 版本；
  以及写盘完成后回填的各输出 CSV / sample_selection.json SHA256。

## G5-E1 provisional 地位

G5 当前基于现时行业 snapshot（caveat 已登记）→ 本轮结果标记 provisional；
Phase B 的 PIT 行业时点表落地后必须做 G5 membership revalidation，
若样本变化按同一冻结规则整体重放，不得人工保留原样本。


---

# ERRATUM v2（Phase A 第二轮审计裁决，406bccb 复审后；本文件先于重跑单独 commit）

## G1-P1 分位阈值参考总体（裁决：严格方案）

CSR-7 冻结规则的 AND 条件顺序为：
  1) 区间最大涨幅 ≥ **全池**（recovery 过滤前的完整 episode 总体）99.5% 分位；
  2) 且回撤修复 ≤3 次。
即分位阈值在过滤前总体上一次性计算（当前研究窗 = 26.171336×），随后应用 recovery
过滤。406bccb 实现的"先 recovery 过滤→qualified pool 内重算 99.5%"废止——它把参考
总体从全池换成 qualified pool，实质改变了样本定义，属于执行阶段看过数据后的口径漂移。
后果（如实接受，不凑数）：G1 合格候选 = 3（sh.601869 / sh.688498 / sz.300489），
登记 **INSUFFICIENT_CANDIDATES**；首轮 G1 实际样本 3 例（不足 20 不补、不降阈值、
不改分位口径），首轮总样本 = 83。这是预注册机制应当发现的真实结果：当前研究窗内
极端涨幅股大多携带多次深回撤修复，"99.5 分位涨幅 ∧ 修复≤3"近乎空集。
敏感性登记同步按**固定全池阈值 26.171336×** 重算（不随 recovery 阈值重算分位）：
  recovery 15% → 1 例；20% → 3 例；25% → 7 例。

## G2-P1 reference_high 边界（裁决：维持首次登记口径）

"未创新高"的 reference_high = **突破前 20 个交易日最高收盘（不含 T0 当日）**。
406bccb 代码 `c[max(0, i-20):i+1]` 误含 T0 收盘（即实际执行 max(pre20, T0_close)），
与 manifest 宣称口径不一致——修正代码为 `c[max(0, i-20):i]`，G2 全量重跑。
单一事实源=本 erratum + 代码 + manifest 三者一致（pre20_high, exclusive of T0）。

## FLOW-P1 先注册后执行的可审计拆分

本 erratum v2 单独 commit（commit A，不含任何重跑产物）；随后代码修改与重跑
产物作为 commit B。Git 历史即可证明规则冻结先于结果生成。
（注：G1 候选数从 21 变 3 会改变单一 rng 流的消耗，G2/G3/G4/G5 的 chosen 将随流
变化——这是流一致性的正常结果，manifest 记录新流即为可重放。）


## G2-P1b 检查窗口澄清（erratum v2 内部矛盾修正，先于重跑 commit B 登记）

erratum v2 的操作句 "fwd window includes T0; no-new-high = fwd max <= pre20 high"
存在逻辑矛盾：T0 为突破日，其收盘价超过前 20 日高是突破事件的定义性特征，
若检查窗口含 T0 则条件几乎必然失败（实测 G2 候选=0，自证矛盾）。
修正冻结：
  reference_high = 前 20 个交易日最高收盘（不含 T0）——同 G2-P1 不变；
  检查窗口 = T0 之后至 T0+120（不含 T0）；
  no-new-high = max(close[T0+1 .. T0+120]) ≤ reference_high。
即"突破日可以站上前高（那是突破本身），之后 120 日不得再超出前高"。
