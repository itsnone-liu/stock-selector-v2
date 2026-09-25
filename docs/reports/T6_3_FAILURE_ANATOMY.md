# T6.3 报告：Failure Anatomy（失败发生在哪一段，什么区分可回补与不可恢复）

> 核心问题：在当时可见的信息中，什么把"可回补型恶化"与"不可恢复型恶化"区分开？
> 三个既有异常放在同一镜头下：C106（E2 收益好但 conf terminal failure 多）、C201（REDUCE
> 时恶化幅度分层）、C204（EXIT 只在 confirmation）。
> 数字全部来自 `output/research/t6/03_failure_anatomy/t6_3_report_data.json`；F1–F6 定义、
> 阈值、首中顺序全部预注册于冻结 contract。参考 cell = direct_chase | P2_balanced
> （21,675 episodes）。
>
> **R1（审计修正）**：false-recovery 窗口曾把 A0 当天计入"after A0 的 5 个有效观察日"
> （A0 日指标普遍未修复，系统性抬高 F3）。已改为严格 A0 之后，并新增 G8d 全量验证
> `trigger_day > a0_day`。修正后 F3 计数 val 3,078→2,017（−34%）、conf 1,873→1,303
> （−30%）；本文全部数字为修正后口径。

## 1. 失败阶段定位（C301）

首中分类 F1→F3→F2→F4→F5→F6：

| F 段 | val | conf | 定义要点 |
|---|---|---|---|
| F1 快速首操作 | 3,855 | 2,512 | 首个 REDUCE/EXIT ≤5 天且终亏 |
| F3 假恢复 | 2,017 | 1,303 | REDUCE→ADD 后 A0 起 5 有效观察日内再破位 |
| **F2 迟识别** | **0** | **0** | **首中分类的结构零**（被 F1/F3 前置截获） |
| F4 退出缺失 | 89 | 16 | dd≥−15% 且从未 EXIT 且终亏 |
| F5 快速缺口/崩跌 | 5 | 13 | 停牌缺口或单日大亏主导终段 |
| F6 其余 | 5,780 | 3,283 | 含 censored 与全部 GOOD/多数 PAINFUL_WIN |

episode 四分类：val GOOD 5,393 / CONTROLLED_LOSS 4,691 / PAINFUL_WIN 1,368 / SEVERE 294；
conf 3,467 / 2,965 / 555 / 140。

**F2=0 的解释边界**：这只是预注册首中分类下没有 episode 最终落入 F2，**不**证明 F1/F3
episode 内不存在 late-deterioration 特征——该潜在重叠本阶段未分解（classification
absence ≠ mechanism absence）。

## 2. 可回补 vs 不可恢复的事前区分（C302，修正窗口后）

队列：有 RECOVERED cycle 的 episode 内，FALSE_RECOVERY（F3）vs CYCLE_OK（trigger 未触
发），事前变量取**首个 REDUCE 日**的可见快照（中位差，stock cluster，Holm 校正）：

| 变量 | val | conf | 解读 |
|---|---|---|---|
| efficiency_signed_3 | **+0.0046** | **+0.0050** | FR 组更高（双段显著） |
| ret_1d_log（当日） | **+0.0136** | **+0.0134** | FR 的首 REDUCE 日在反弹（双段显著） |
| dist_ref20 | **+0.0072** | **+0.0155** | FR 价格更高于 ref20（双段显著） |
| turnover_load_3d | **+0.44** | **+0.28** | FR 热度更高（双段显著） |
| 回撤深度 / max_dd / 首减时长（中位） | 差 0（p=1.0） | 同 | **中位口径无分离** |

修正窗口后信号**更强更纯**：四个行为变量双段 Holm 全显著。口径限定：dd/max_dd/首减
时长的"无分离"仅指 median 检验口径，不主张整个分布无差异。
与 T6.2 C201 拼合：**深恶化→不 ADD（NO_RECOVERY）；浅恶化且反弹日（价格高于 ref20、
当日上涨、热度高）→过快 ADD→A0 后 5 有效观察日内再破（F3）**。

## 3. C106 定位（C303/C304）：E2 的 conf 张力分散在 F6+F1+F3

| 口径 | val E1/E2/E3 | conf E1/E2/E3 |
|---|---|---|
| SEVERE_FAILURE（终亏+深回撤） | 3.79 / 3.42 / 1.48% | 3.66 / **2.00** / 1.31% |
| terminal_failure（末日深回撤，无论盈亏） | 43.8 / 44.8 / 35.1% | 55.8 / **64.6** / 46.8% |

两口径方向相反（C304）：E2 在 conf **最终大亏更少、带深回撤扛到末日的更多**——失败
形态是 PAINFUL_WIN 型，不是更多终亏。

conf 的 +8.7pp 按 F 分解（修正窗口）：**F6 残差 +3.9pp（~45%）> F1 +2.6pp（~30%）>
F3 +2.4pp（~28%）**，F4/F5 ≈ 0；val 净 +1.0pp（F3 +2.1 被 F1 −1.2 抵消）。修正前
"F3 贡献一半"的表述不成立——张力分散在残差/早操作/假恢复三段（C303）。

## 4. EXIT 通道解剖（C305）

conf 的 3,328 个退出 episode：**F1 2,033（61%）+ F6 810（24%）+ F3 477（14%）**。
conf 的 EXIT 主要是**早期结构切除**，不是"修复放弃式"晚退出；F4（该退不退）所有段
≤1%。

## 5. 失败链条判定（C306）

`E-class 错误 → 恶化识别迟 → 错误 ADD → EXIT 缺失 → 数据缺口崩跌` 中：
- 主泄漏 = **ADD 段（F3）+ 早期操作段（F1）**，且 E2 张量大量落在 F6 残差（未分解的
  中段形态）；
- 恶化识别迟（F2）不构成独立首中类（taxonomy 结构零，机制重叠未分解）；
- EXIT 缺失（F4）与数据缺口（F5）边缘。
以上为冻结规则下的条件结构，非因果归因。

## 6. Claims（⊂ t6_3_claims.json）

C301 SUPPORTED / C302 SUPPORTED / C303 SUPPORTED / C304 SUPPORTED / C305 SUPPORTED /
C306 SUPPORTED（全部为 R1 修正窗口口径）。

## 7. Gate 结果

见 `t6_3_gates.json`。G8d（新增）：全量验证每个 fired trigger 的 `trigger_day > a0_day`
且触发日 row_present=True；G9 含 NaN 一致性；G9b 从 contract 符号独立重建四分类；G10
重放 separability 单元逐位一致。
