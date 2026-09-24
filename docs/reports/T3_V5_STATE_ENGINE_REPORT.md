# T3 V5 状态引擎报告：换手归一化 + 四轴状态向量 + 实时判别框架

- 基线：`64a2a22`（T3 V4 冻结）。
- 状态：**八道 Gate 全部 PASS**；规则版本 `compact_state_v1`，schema 版本 `state_vector_v1`。
- 性质：PIT、确定性、可解释的**状态机**——不是收益预测模型。所有状态完全由 as-of 可观测原语决定；compact 状态是描述性标签，**无排序**（非 A/B/C/D、非强/弱、非买/观/卖）。
- 产物：`output/research/t3_v5/`（研究层 6 件 + 实时层 2 件 + 证据层 4 件 + manifest，见 §11）。

## 1. Turnover Confound Gate（开工令 §1–§2，第一优先）

### 1.1 归一化量（预注册，公式冻结）

- `pre20_turn_base`：V3 冻结基准 = T0 前 20 个 vpos 有效交易日的 turn 均值（事件属性，突破后永不重定义；与 `t3_v3.build_event_daily` 逐字同源，原始数据重算 + 40 事件抽样复核 0 错配）。
- `expected_turnover_since_t0 = pre20_turn_base × turn_n_to_tau`（`turn_n` = 进入 `cum_turnover_since_t0` 的 turn>0 日数，与分子严格同集合）。
- **`turnover_load_to_tau = cum_turnover_since_t0 / expected_turnover_since_t0`**（无量纲；=1 恰为"事件后参与与自身突破前水平同速"）。
- `mean_turnover_load_to_tau = mean_turnover_since_t0 / pre20_turn_base`：与累计定义**恒等**（1,124,302 行逐行 identity check 0 违例）——按开工令作为定义验证列，不作为独立发现。
- 单位继承 V4 schema gate：turn=百分点，cum=百分点·日。

### 1.2 四 exposure 拆解（同 tau 内四分位，Q4−Q1 中位超额，×100=百分点；stock/date 双聚类 bootstrap，Holm 在 (tau,Δ)×exposure 族内）

| exposure（语义） | tau0/Δ20 | tau5/Δ20 | tau10/Δ20 | tau20/Δ20 |
|---|---:|---:|---:|---:|
| cum_turnover（复现 V4，事件后累计） | −5.84 | −5.12 | −4.00 | −2.56 |
| pre20_turn_base（**股票固有换手属性**） | −5.33 | −4.33 | −3.44 | −1.38 |
| **turnover_load（自归一化异常参与）** | −2.26 | −2.04 | −1.26 | −1.76 |
| mean_turnover（事件期均速） | −5.84 | −5.12 | −3.97 | −2.58 |

**基线分层内复验**（在 pre20_turn_base 四分位层内再做 load 四分位，tau=10）：

| 层 | Δ5 | Δ10 | Δ20 |
|---|---|---|---|
| baseQ1（自身低换手股） | −0.39* | −0.94* | −1.95* |
| baseQ2 | −0.47* | −0.59 | −1.30* |
| baseQ3 | −0.49* | −1.06* | −1.91* |
| baseQ4（自身高换手股） | −0.29 | −0.42 | −1.11 |

（* = Holm 后显著；120 个 primary diff 中 111 个 Holm 后显著。）

### 1.3 判定（预注册规则自动读出）

`PASS_norm_persistent`：raw 梯度在全部 primary tau×Δ 复现（15/15）；**归一化 load 的负梯度在 3/3 primary tau 存在**；**在 4/4 基线分层内方向为负**（baseQ4 单层不显著但方向一致）。

**解释边界（按开工令措辞）**：V4 的原始梯度 = 两个成分叠加——(a) 股票固有换手属性（基线自身 Q4−Q1 = −1.4~−5.3pp：高换手股票群体的条件路径本来就更差）；(b) **事件后相对自身的异常参与负荷**（归一化后 −0.3~−2.3pp，层内稳健）。因 (b) 在自身基准归一后独立存活，V5 起授权命名为 **turnover pressure / participation load**；仍不得解释为"主力出货"或任何资金主体行为。

## 2. 四轴状态向量（开工令 §3–§7）

| 轴 | 原语 | 边界（预注册） | 状态 |
|---|---|---|---|
| Structure | distance_to_ref20 | ≥0 / <0（天然零点） | intact / broken |
| Position | close_vs_anchored_vwap | ≥0 / <0（天然零点） | above_event_cost / below_event_cost |
| Participation | turnover_load_to_tau | ≤1 / >1（=自身突破前速度） | normal / elevated |
| Extension | drawdown + days_since_peak | tau 特定冻结中位数（V4 冻结事件宇宙，tau0–40，写入 definition JSON，永不重拟合） | extending / pullback / consolidation |

- ref60 与 `t0_ref60_breakout` 仅作背景列保存，不改变 lifecycle20 主定义。
- 阈值 1.0 处的分布背景（开工令 §6 预期披露）：median load 从 T0 的 1.62 衰减到 tau40 的 1.26；load>1 占比 85.9%→69.1%——"elevated"是突破后的常态，阈值保持 1.0 不动，不按结果调切点。
- Extension 中位数分割矩阵：days_since>med → consolidation（时间消化）；≤med 且 dd≤med → extending；≤med 且 dd>med → pullback（快速回撤，罕见格）。

## 3. Compact State v1（§8）

全空间确定映射：broken→`structural_break`；intact 且 below cost→`structural_pressure`；intact 且 above：extending×load≤1→`continuation`、extending×load>1→`high_participation_extension`、pullback→`controlled_pullback`、consolidation→`consolidation`；任一轴缺失→`insufficient_data`。映射冻结于 `compact_state_definition.json`（含全部参考中位数）。

日级网格分布（in-dataset 行）：structural_break 42.2%、high_participation_extension 26.7%、structural_pressure 17.3%、consolidation 4.7%、continuation 4.4%、controlled_pullback 3.3%、insufficient 1.4%。checkpoint 视角：T0 时 71.7% 为 high_participation_extension（突破日天然 extending 且 load>1 占 86%）；tau=20 时 structural_break 44.9%。

**资金效率二维（§9 固定组合：价格完整性 × 归一化负荷，tau=10/Δ20）**：

| 格 | n | 中位超额% | 中位MDD% | P(new high) |
|---|---:|---:|---:|---:|
| intact_lowload | 1,918 | −1.15 | 10.0 | 0.735 |
| **intact_highload** | 13,919 | **−2.29** | **11.7** | 0.655 |
| impaired_lowload | 3,609 | −1.79 | 9.8 | 0.351 |
| impaired_highload | 6,921 | −2.15 | 10.2 | 0.313 |

描述性读法：**付出高换手负荷而结构仍保持的事件，比低负荷事件随后路径更差**（三维 outcome 同向）；结构受损格的创新高概率骤降。"高换手本身不重要、重要的是换手是否换来结构推进"这一核心假设在四格里呈现为 intact 内的负荷惩罚。`efficiency_proxy = price_progress / max(load, 0.25)`（预注册分母下限 0.25）仅作 exploratory 列，二维原变量始终随报。

## 4. 状态转移（§11）

- **Dwell（市场日，中位）**：structural_break 3（p90=31——一旦破位倾向于长期停留，吸收态特征）；high_participation_extension 2；continuation 2；structural_pressure/consolidation/pullback 1。
- **First-entry tau（中位）**：high_participation_extension 0（T0 即入）、continuation 1、structural_pressure 2、structural_break 3、controlled_pullback 5、consolidation 9。
- **Revisit（均值，每事件×状态）**：structural_pressure 2.05（最常反复）、HPE 1.66、break 1.20。
- **Checkpoint 流**（1→5）：break→break 17.0%、HPE→HPE 15.0%、HPE→pressure 11.5%、HPE→break 8.8%、pressure→break 7.6%；（10→20）：break→break 30.9%。
- 日级全量 transition 计数/概率在 `state_transitions.parquet`（daily + checkpoint 双 scope）。

## 5. 实时层（§12–§13）

- `realtime_state_snapshot`：输入只含截至 asof 的数据；输出 active 事件的 code6/event_id/breakout_day/tau/四轴/compact/连续原语/完整性 flag/state_since/previous_state；支持 `--asof YYYY-MM-DD` 任意历史重放；同输入确定性（Gate 6 双跑一致 + 截断重算一致）。
- **Anchor 规则**：同股多 active 事件取 `latest breakout_day <= asof`（100% 确定，Gate 5 于 13 个历史 asof 逐一复核 0 错配）；同时保留 `overlapping_event_count` / `prior_breakout_event_id` 审计列。
- 基准快照（2026-09-18）：1,132 只锚定股票——structural_break 522、HPE 179、continuation 158、pressure 134、consolidation 115、pullback 11、insufficient 13；median load 0.88（当前突破后参与低于自身突破前速度，load>1 仅 37%——时点性描述）。

## 6. 历史验证的边界 + 前瞻台账（§14–§15）

- 本报告全部条件路径数字属于 **internal temporal robustness**——V4 已用全数据发现换手结构，任何再切分都不是 untouched holdout，不称 out-of-sample。
- `prospective_state_ledger` 已建：hash 链式 append-only（每行 sha256(prev‖canonical row)）、asof 严格递增、rule/schema/input-manifest-hash 齐全；首笔为 2026-09-18 的 **in-sample 基线记录**（不计入 prospective 证据）；真正前瞻样本从 2026-09-18 之后的新事件开始，成熟后由独立脚本追加 outcome（本次未写任何前瞻 outcome）。
- 冻结纪律：ledger 建立后的状态规则不因前瞻表现不好而回改。

## 7. Internal Validation（§16：语义一致性，非收益最大化）

tau=10/Δ20 按 compact 状态（中位超额% / 中位MDD% / P(new high) / P(lose ref20)）：

| 状态 | n | 超额 | MDD | P(nh) | P(lose) |
|---|---:|---:|---:|---:|---:|
| controlled_pullback | 975 | −4.79 | 16.6 | 0.502 | 0.344 |
| structural_pressure | 4,770 | −2.59 | 10.9 | 0.440 | 0.638 |
| structural_break | 10,484 | −2.03 | 10.0 | **0.326** | **0.977** |
| high_participation_extension | 7,376 | −1.91 | 11.7 | 0.793 | 0.393 |
| consolidation | 1,505 | −1.58 | 11.2 | 0.742 | 0.614 |
| continuation | 1,110 | **−1.08** | **9.6** | **0.814** | 0.567 |

语义检查结果：**structural_break** 确以最低 P(new high) 与 97.7% 的再度失守体现（不止是收益差一点）；**high_participation_extension** 复现 V4 的"高负荷 + 随后效率下降"（创新高概率仍高 0.79 但超额/MDD 在 intact-above 组内最差）；**consolidation** 复现"中位路径改善但突破动能不必然改善"（P(nh)=0.742 低于 extending 态）。三个预注册语义全部成立，无需为标签有序性修改任何规则；controlled_pullback 为最差格（快速深回撤是危险信号而非"便宜上车"），保留多维解释。

## 8. 八道 Gate

| Gate | 结果 | 证据 |
|---|---|---|
| 1 Turnover Confound | **PASS** | 四 exposure 全拆解 + identity 0 违例 + 40 事件原始重算 base 0 错配 + 预注册判定 PASS_norm_persistent |
| 2 State PIT | **PASS** | 120 抽样（覆盖全部 compact 态/tau0–40）物理截断→V3 重建→独立映射，5 项字段 0 mismatch |
| 3 State Determinism | **PASS** | 全产物进程内双跑 hash 一致（含 bootstrap） |
| 4 Transition Integrity | **PASS** | 日级转移计数/检查点状态/run 统计独立复算 0 错配 |
| 5 Active Anchor | **PASS** | 13 个历史 asof，latest-anchor/重叠数/前事件 100% 确定 |
| 6 Realtime Replay | **PASS** | 随机 asof 双跑一致 + 4 日期×4 事件截断重算状态一致 |
| 7 No-Future | **PASS** | 实时产物无 outcome 列；每行 source_date==asof |
| 8 Prospective Ledger | **PASS** | hash 链 0 断裂、asof 单调、版本/manifest-hash 完整 |

实现勘误（如实披露，均在冻结前由 Gate 抓出并重建）：① 初版 extension 轴误用 `distance_to_ref20` 参与回撤中位数比较（正确为 `drawdown_from_running_peak`）——Gate 2 的独立映射暴露 114/120 错配，修复后 0；② checkpoint 转移行 scope 列缺失（与日级 0→1 行不可区分），补 `scope="checkpoint"` 重建；③ 门禁脚本自身两处口径修正（JSON 整型键、None/NaN 归一），产品不受影响。教训与 V4 一致：**独立代码路径的对账是唯一可靠的门禁**——把映射逻辑内联重写是两次事故的共同根源。

## 9. 产物清单（§18）

| 层 | 产物 | 规模 |
|---|---|---|
| 研究 | `state_vector_daily.parquet`（tau0–40 全网格，四轴+compact+原语+flag） | 1,124,302 行 |
| 研究 | `state_checkpoints.parquet`（tau∈{0,1,5,10,20}） | 137,110 行 |
| 研究 | `state_transitions.parquet`（daily+checkpoint）/ `state_run_stats.parquet`（dwell/first-entry/revisit） | — |
| 研究 | `turnover_normalization_audit.parquet`（base/expected/load/identity 全列） | 1,124,302 行 |
| 研究 | `turnover_confound_contrasts.parquet` / `state_internal_validation.parquet` | 600 / 99 行 |
| 定义 | `compact_state_definition.json`（轴定义+冻结参考中位数+映射+判定） | — |
| 实时 | `realtime_state_snapshot.parquet` / `prospective_state_ledger.parquet` | 1,132 / 1,132 行 |
| 证据 | `state_integrity_gates.json` / `state_pit_audit`（并入 gates）/ `state_replay_audit`（并入）/ `state_determinism.json` / `state_run_manifest.json` | — |

## 10. 禁止事项自查（§19）

无预测模型/ML 分类器/自动特征选择/阈值寻优；compact 未转买卖信号、未按收益排序；无仓位优化、无四策略比较、无止盈止损优化；未因前瞻表现修改冻结规则（前瞻样本尚未存在）。状态与未来结果物理分离（No-Future gate 结构性保证）。

## 11. V6 展望（§20）

V5 PASS 后进入 T3 V6（状态条件下的交易执行研究）：同一状态内比较四种入场（直接追入/首次缩量回调/支撑止跌/分批），以及同一入场跨状态的表现——问"什么状态适合什么执行"，让数据决定。本报告所有状态差异不构成入场建议。

## 12. 成功标准对照（开工令结尾六问）

对任意已突破股票与任意历史日期，系统可在不知未来的前提下回答：结构是否保持（structure 轴）；价格在事件成本代理的哪侧（position 轴）；当前换手相对自身历史正常还是偏高（participation 轴，turnover_load vs 1）；正在延伸/回调/时间消化/结构破坏（extension 轴 + compact）；状态已持续多久（state_since）；从哪个状态转来（previous_state + 转移表）——以上以 `compact_state_v1` 固定规则写入实时 ledger。
