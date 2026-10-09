# External Ideas 接口层 — 方案与思想映射（EI-0）

> 裁定全文已入决策记忆（2026-10-09）。生产基线冻结不动；外部思想三去向：A 增强已验证模块 / B 补缺失决策模块 / C 解释诊断。禁第四种（直接加交易信号）。

## 卡片模板（每个思想必填，核心=existing_baseline）
```
idea_id / source / source_formula
target_decision: MARKET|SECTOR|WHAT|WHERE|HOLD|REDUCE|POSITION|EXIT|DIAGNOSTIC
mechanism / new_information: true|false
existing_baseline: 相对现有模块新增什么（答不出=不研究）
incremental_question / frozen_inputs / outcomes
promotion_rule / stop_rule
status: IDEA|PREREGISTERED|TESTED_PASS|TESTED_FAIL|DIAGNOSTIC_ONLY|ARCHIVED
```

## EI-0：916 库思想映射（不跑数据）

| 来源 | 思想 | 决策轴 | 判定 |
|---|---|---|---|
| S008 宽度模块（MA50占比/新高新低/板块宽度/龙头集中） | 市场内部健康度驱动 exposure | MARKET | **OPEN_GAP → EI-1**（P3 overlay） |
| S008 RPS50/120/250 横截面强度 | T3 的更好表达 | WHAT | **POTENTIAL_INCREMENT → EI-3**（先 descriptor） |
| S008 倍危（多周期过度扩张） | 盈利仓 REDUCE 缺口 | REDUCE | **OPEN_GAP → EI-2**（最高价值新增） |
| S006 多周期 VWAP 中枢/量权成本带 | 轻量成本代理 | WHERE | **POTENTIAL_INCREMENT → EI-4**（盘中 proxy） |
| S006 竞价/分时构造 | 新信息域 timing | TIMING | **EI-5**（唯一可重挑 Activation 的方向，独立立项） |
| S008 Minervini 四阶段 | 价格结构描述 | DIAGNOSTIC | 保留解释/可视化，不入 gate |
| S003 缩量上涨/惜售 | 供给压力诊断 | HOLD | 低优先（HL_RAISE 已很好） |
| S006 波动率自适应均线 VIDYA | 工具 | — | 备用工具，不立项 |
| S001 复合超卖振荡器 / S002 大阳反转 / KDJ-CCI-MACD 复合 / S004 EOD 起爆 / S005 单峰密集吸筹 / 涨停穿越买点 / 户数时序买点 | — | — | **ARCHIVED**（分别被 Cost Support 替代/事后确认/信息重复/R2-8B 关闭/R2-9 否定/late confirm/多次 NO-GO） |

## 执行序与停止线
EI-1 Breadth→P3 → EI-2 Overextension/REDUCE → EI-3 RS 比较器 → EI-4 VWAP proxy → EI-5 盘中可行性（最后）。
每条=一次预注册主实验+必要独立验证；禁改周期/阈值/换名重试；无清晰稳定可解释增量即归档不救。
关闭项不重开清单：EOD 启动识别 / ADD_TRIGGER / 户数=bullish / 龙虎榜 / 新带=支撑 / 超跌反转。
