# T6.3 报告：Failure Anatomy（失败发生在哪一段，什么区分可回补与不可恢复）

> 核心问题：在当时可见的信息中，什么把"可回补型恶化"与"不可恢复型恶化"区分开？
> 三个既有异常放在同一镜头下：C106（E2 收益好但 conf terminal failure 多）、C201（REDUCE
> 时恶化幅度分层）、C204（EXIT 只在 confirmation）。
> 数字全部来自 `output/research/t6/03_failure_anatomy/t6_3_report_data.json`；F1–F6 定义、
> 阈值、首中顺序全部预注册于冻结 contract。参考 cell = direct_chase | P2_balanced（21,675
> episodes）。

## 1. 失败阶段定位（C301）

首中分类 F1→F3→F2→F4→F5→F6：

| F 段 | val | conf | 定义要点 |
|---|---|---|---|
| F1 快速首操作 | 3,855 | 2,512 | 首个 REDUCE/EXIT ≤5 天且终亏 |
| F3 假恢复 | 3,078 | 1,873 | REDUCE→ADD 后 5 有效观察日内再破位 |
| **F2 迟识别** | **0** | **0** | **结构零**（被 F1/F3 前置截获） |
| F4 退出缺失 | 88 | 16 | dd≥−15% 且从未 EXIT 且终亏 |
| F5 快速缺口/崩跌 | 4 | 13 | 停牌缺口或单日大亏主导终段 |
| F6 其余 | 4,721 | 2,713 | 含 censored 与全部 GOOD/多数 PAINFUL_WIN |

episode 四分类：val GOOD 5,393 / CONTROLLED_LOSS 4,691 / PAINFUL_WIN 1,368 / SEVERE 294；
conf 3,467 / 2,965 / 555 / 140。**失败质量集中在 F1+F3+F6；F2 按预注册定义零命中**。

## 2. 可回补 vs 不可恢复的事前区分（C302）

队列：有 RECOVERED cycle 的 episode 内，FALSE_RECOVERY（F3）vs CYCLE_OK（trigger 未触发），
事前变量取**首个 REDUCE 日**的可见快照（中位差，stock cluster，Holm 校正）：

| 变量 | val | conf | 解读 |
|---|---|---|---|
| efficiency_signed_3 | **+0.0031** | **+0.0028** | FR 组更高（双段 Holm 显著） |
| ret_1d_log（当日） | **+0.0072** | **+0.0071** | FR 的首 REDUCE 日在反弹（双段显著） |
| dist_ref20 | −0.0010 (ns) | **−0.0065** | conf 段 FR 更贴近 ref20 |
| 回撤深度 / max_dd / 首减时长 | 中位差 0（p=1.0） | 同 | **无区分力** |

**回撤深度不区分假恢复与干净恢复——"浅恶化 + 反弹日 REDUCE"才容易变成假恢复**。与 T6.2
C201 拼成完整图景：深恶化→根本不 ADD（NO_RECOVERY）；浅恶化且当天反弹→过快 ADD→5 日内
再破位（F3）。

## 3. C106 定位（C303/C304）：E2 的 conf 张力在假恢复路径

两种失败口径的 E 分解（比例，E-class 内）：

| 口径 | val E1/E2/E3 | conf E1/E2/E3 |
|---|---|---|
| SEVERE_FAILURE（终亏+深回撤） | 3.79 / 3.42 / 1.48% | 3.66 / **2.00** / 1.31% |
| terminal_failure（末日深回撤，无论盈亏） | 43.8 / 44.8 / 35.1% | 55.8 / **64.6** / 46.8% |

两口径方向相反（C304）：E2 在 conf **最终大亏更少、但带深回撤扛到末日的更多**——失败
形态是 PAINFUL_WIN 型（扛到末日后翻身），不是更多终亏。

C106 的 +8.7pp 增量按 F 分解（conf，E2−E1）：**F3 贡献约 +4.2pp（半数）、F1 +2.6pp、
F6 +2.1pp；F4（退出缺失）≤0.5pp**（C303）。validation 只有 F3 分量（+2.6pp）被 F1
（−1.25pp）抵消——C106 的段间不一致本质是 **F3 假恢复分量的段间放大**。

## 4. EXIT 通道解剖（C305）

conf 的 3,328 个退出 episode：**F1 2,033（61%）+ F3 590（18%）+ F6 697（21%）**。conf 的
EXIT 主要是**早期结构切除**（5 天内首操作即退出且终亏），不是"修复放弃式"晚退出；F4
（该退不退）在所有段 ≤1%——退出缺失不是失败主因。

## 5. 失败链条判定（C306）

`E-class 错误 → 恶化识别迟 → 错误 ADD → EXIT 缺失 → 数据缺口崩跌` 中：
- **主导泄漏 = ADD 段（F3）+ 早期操作段（F1）**；
- 恶化识别迟（F2）按预注册定义零命中；
- EXIT 缺失（F4）与数据缺口（F5）边缘。
以上为冻结规则下的条件结构，非因果归因。与用户"资金态度"框架的连接：**区分可回补与
不可恢复的关键事前信号不是回撤深度，而是恶化浅但热度/反弹异常（efficiency 高 + 当日
反弹）的组合**——这是 T6.5 synthesis 的输入。

## 6. Claims（⊂ t6_3_claims.json）

C301 SUPPORTED / C302 SUPPORTED / C303 SUPPORTED / C304 SUPPORTED / C305 SUPPORTED /
C306 SUPPORTED。

## 7. Gate 结果

见 `t6_3_gates.json`。G9 含 R1 的 NaN 一致性约束；G9b 独立重算频率表与四分类（从
contract 阈值符号独立重建）；G10 重放 separability 单元逐位一致。
