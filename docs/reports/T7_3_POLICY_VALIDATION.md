# T7.3 报告：Frozen-Policy Replay + Dual-Clock Accounting（VAL primary）

> **身份**：Freeze（`4a08d9e`）之后的第一次 VAL 打开。全部 policy 与阈值在 Freeze
> 已写死（C1/C2 阈值从 contract 读取，源码无字面量——G27）。CONF 在本轮**未计算**
> （段协议 t7_3b：validation first；summary/报告只含 VAL）。数字全部来自
> `output/research/t7/03_policy_validation/` 产物。

## 1. 管线与守恒（审计优先于结果）

- **Policy replay**：A（a0_day 原样）/ B1/B2/B3/B5（a0 后延迟 N 有效日，episode
  放不下则该 cycle 无 ADD）/ C1（R+5 评估 `max_bounce_R5 > q1(−0.01875)`，通过则
  R+5 ADD，否则本 cycle 不再 ADD）/ C2（q2 sensitivity）。
- **Sizing 机械继承**：各 policy 的 add 后 exposure 序列 = A 的 add 后形状**平移到
  自己的 add_day**（C1 早于 a0 进场时形状提前重放、末端以 A 末仓延续）；
  **inheritance violations = 0**（G27，逐行断言）。
- **G25 反事实守恒**：7 policies × 31,260 cycles 全等键集（218,820 行）；C1 否决
  ADD 的 18,395 个 cycle **保留在评价样本内**（has_add=False），无选择性消失。
- **G26 双 clock 重放**（120 抽样逐位重算）：False ADD 从**各 policy 自己的
  add_day** 起 W10（est∈(add, add+10] 视为 in-window；add 前已恢复不算 false
  add）；Missed Recovery 用**公共 cycle est clock**（TR 且 est 日未暴露）。0
  mismatch。

## 2. VAL frontier（17,150 cycles；primary=A, B3；curve/sensitivity 全报）

| policy | ADDs | **false_add_rate** | TR missed 率 | missed 正成本和 | mean expo | **wret_R40** |
|---|---|---|---|---|---|---|
| **A** | 9,312 | **16.16%** | 12.08% | +3.23 | 0.411 | **+2.08%** |
| B1 | 9,312 | 18.03% | 36.35% | +25.84 | 0.402 | +1.95% |
| B2 | 8,876 | 17.98% | 79.24% | +102.24 | 0.392 | +0.40% |
| **B3** | 8,665 | 17.58% | 79.65% | +102.50 | 0.385 | −0.47% |
| B5 | 8,146 | 17.59% | 84.91% | +110.56 | 0.365 | −0.49% |
| **C1** | 7,649 | **17.47%** | **82.23%** | +104.01 | 0.372 | **−0.32%** |
| C2 | 5,297 | 21.13% | 89.60% | +111.00 | 0.342 | −0.37% |

（"missed 正成本和"= missed cycles 的正 upside 求和（负 upside 段 = est 日价格仍
低于 R0 的 cycle，"错过"它们不构成真实成本）：A=+3.23/−19.19、B1=+25.84/−32.89、
B2=+102.24/−42.07、B3=+102.50/−42.98、B5=+110.56/−47.51、C1=+104.01/−51.08、
C2=+111.00/−54.16；精确分解已持久化 `t7_3_report_data.json` 的
`missed_cost_decomposition_val`。）

## 3. VAL 结果（如实，无解释性回溯）

1. **C1 的 false-ADD 风险未降低**：17.47% vs A 的 16.16%（Δ=+1.3pp）。DEV 上
   高 bounce tertile 的 FR 率优势（32.3% vs 62.1%）**没有**转化为 VAL 上
   policy-level false_add_rate 的改善——C1 的统一 R+5 进场时点改变了各 ADD 的
   自身 clock（提前于 a0 的进场暴露在更早的回撤窗），W10/severe 口径下风险端
   反而略升。
2. **C1 的恢复捕获大幅劣化**：TR missed 82.2% vs A 的 12.1%（est 日中位远早于
   R+5——恢复确认点先于 C1 的确认进场时点本身）；wret_R40 −0.32% vs +2.08%。
3. B 全曲线同向（延迟越久越差）；C2 一致更差（21.1% / 89.6%）。

## 4. 段协议结论

按 t7_3b 预注册处置：**C1 = NOT VALIDATED（VAL）**——风险端（false-ADD
reduction）未达成、上行端（recovery upside）大幅受损。**不回 DEV 重选、不调整
阈值、不晋升 C2**（contract 禁令）。A 保持 frozen reference。CONF 阶段对 C1
不再进行（VAL 已失败，段协议允许直接记 NOT_VALIDATED 终止）；CONF 窗口仍可用于
t7_4 的全段独立预注册研究（不涉及 policy 选择）。

## 5. Gate

`t7_3_gates.json` 全 PASS：G1（5 输入）/ G2b（上游 5 产物不可变）/ **G25 反事实
守恒**（31,260×7 全等；C1 的 18,395 个无 ADD cycle 保留在样本）/ **G26 双 clock
重放**（0 mismatch）/ **G27 sizing 继承 + 阈值零字面量**（0 violations）/
**G28 VAL-only 报告纪律**。

过程修正（诚实）：初版 inheritance 断言按"无 pad"语义写，把 C1 提前进场的 237
个合法形状重放记为违规——修正断言语义（pad 段=A 末仓延续）后 0 违规；B_N 延迟
越界从"钳到末日"改为"该 cycle 无 ADD"。
