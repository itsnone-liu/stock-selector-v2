# CD-5 — Candidate Episode, Lifecycle & Cost Context · Completion Report

*预注册: `cd5_preregistration.json` · Episodes: `data/cd/l4_episodes.json.gz` · Census: `cd5a_episode_census.json` · 验证: `cd5bd_results.json`*

## CD-5A Episode 层：30,066 episodes（source 序列被保存）

| 终止类型 | 数量 | 语义 |
|---|---|---|
| INACTIVE_TERMINATION（40 日无任何 source） | 25,470 | 自然失活 |
| CENSORED（数据截止仍存活） | 3,707 | **右删失，绝不计为失败** |
| STRUCTURAL_FAILURE（冻结规则） | 889 (3.0%) | 结构失败条件严格 |

**origin**：S 20,360 / M 5,682 / L 4,024（事件型主导，符合三源自然频率）。

**source_sequence census（只计数，不赋义）**：S 单独 7,492 / S→M 7,012 / **S→M→L 3,884** / M 单独 2,110 / L→S→M 2,068 / M→S 1,830…… episode 中位持续 139 日历日。"机会如何长出来"的数据基础已就位。

## CD-5B 生命周期：轴→状态（观察先于命名）

四轴（rp_sector/rp_market 20d 相对、structure vs episode MA60 + episode 回撤、participation vs 起点基线、cost position vs 成本带）dev 窗 q33/q67 冻结分位，优先级 DECAYING > STRENGTHENING > HOLDING 合成。**回调不自动 = DECAY**（需双 LOW + 成本/参与度确认）。全词汇纪律执行（无吸筹/洗盘/拉升/出货/主力）。

## CD-5C 成本上下文：全部 model_derived 显式标记

daily_price_proxy=(H+L+C)/3 → episode running 加权直方图 → cost_center_proxy（加权中位）/cost_band P25-P75/dispersion/above-inside-below/distance/volume_below_current_price_ratio（仅解释为"episode 历史成交价位置与当前价的关系"，非盈利筹码）。

## CD-5D 验证：生命周期标签有真实时间方向含义（dev/holdout 一致）

**STRENGTHENING 的持续与衰减**（holdout，ALL 源类似）：

| 前瞻 | P(仍 STR) | P(进入 DECAYING) |
|---|---|---|
| 5d | **~68%** | 6.5% |
| 20d | ~28-32% | 41-47% |
| 60d | ~21-30% | 78-83% |

状态有清晰的**时间衰减结构**：短期（5d）强延续、中期回归、长期接近必然经历弱段——这正是"时间方向含义"的证据，且 dev/holdout 复验一致。

**origin 分层（硬要求，差异真实）**：

| origin | STR 仍 STR@60d (dev/holdout) | DECAYING→FAIL@60d (dev/holdout) |
|---|---|---|
| L | 29% / 29% | 2.2% / 2.2% |
| M | **21% / 24%**（最不稳定） | **6.4% / 4.3%**（失败率最高） |
| S | 28% / 30% | 1.0% / 0.8% |

**M-origin（emerging）的走强最不持续、失败风险最高；S-origin（event）走强持续性反而略好且失败率最低**——origin 不是 TTL 但携带真实的生命周期条件信息，此类 origin-conditional 发现按裁定如实保留、不强行合并。

**STRUCTURAL_FAILURE 罕见**（3.0%）说明失败规则严格（15 日低于 P25 + 参与度减半）——高频触发会是规则缺陷，罕见触发符合"结构失败应少"的先验。

## 八条完成门判定

| # | 条件 | 判定 |
|---|---|---|
| 1 | episode identity stable | ✅ stock#ord 唯一 30,066 |
| 2 | 候选消失≠终止 | ✅ 终止仅来自冻结规则（40d 无源/结构失败/删失） |
| 3 | source sequence preserved | ✅ census 已交付 |
| 4 | lifecycle 可观察且冻结 | ✅ dev 分位冻结+优先级合成 |
| 5 | cost proxy 来源显式 | ✅ 全 model_derived |
| 6 | origin 分层完整 | ✅ ALL/L/M/S × dev/holdout |
| 7 | 前瞻验证 dev/holdout | ✅ 一致复验 |
| 8 | 删失处理正确 | ✅ 3,707 单列不计失败 |

**CD-6 进入资格：八条全 PASS。**

## 边界遵守

三条硬约束执行：source 消失不终止 episode（仅 INACTIVE 规则）· OHLCV 只产 model-derived proxy（无主力成本/筹码峰声明）· 无任何交易决策输出。NARROWING/regime 仅作 context 携带（L2_RISK_CONTEXT_V1 不动，episode 结束是否受 NARROWING 影响属 CD-6）。

**全局状态**：`CD-0..CD-4V2 + CD-5 COMPLETE · 六层架构 L0-L4 就绪 · CD-6 (L5 Decision Engine) 待 GO · L2_RISK_CONTEXT_V1 待 CD-6 消费 · CSR-8 不变`
