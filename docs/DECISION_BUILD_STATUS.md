# 决策系统落地状态（对应 docs/DECISION_SYSTEM_BLUEPRINT.md）

代码于 v2.0-ai-rebuild 之后解冻：旧系统（`/root/.hermes/hermes-agent/**`）仍只读；
本仓库即新系统实现基座。2026-09-15 起决策层代码落地。

## 模块 → 蓝图映射

| 模块 | 蓝图章节 | 状态 |
|---|---|---|
| `decision/clock.py` SessionClock / VolumeClock | §2 证据分级、§3.2 量能折算 | ✅ 落地（uniform_v0 默认；profile_v1 待分钟校准数据） |
| `decision/weekly_momentum.py` revised/unified/legacy | §3.4 周级量价动能 | ✅ 落地；legacy 为重建版待取证（SEMANTIC_RECOVERY_WORKSHEET P1） |
| `decision/labels.py` daily_labels | §信号层 | ✅ 落地：多标签（非elif互斥）+量能旁证字段 |
| `decision/portfolio.py` Portfolio/Lot | §4 T+1账本+仓位约束 | ✅ 落地：lot级T+1、单票/行业/单日/regime上限 |
| `decision/exits.py` ExitMonitor | §4.4 退出候选 | ✅ 落地：E1/E2/E3/E5，close与intraday双口径，触发≠成交 |
| `decision/regime.py` market_regime + CapitalContext | §7/§9 | ✅ 落地：指数MA20/60三态；unknown≠neutral |
| `decision/advice.py` compose_advice | §5 建议schema | ✅ 落地：schema v1，置信规则化，unknowns→禁high |
| `decision/minutes.py` TdxMinuteReader / Synthetic | §6.1 分钟层 | ✅ 落地：lc1/lc5解析器+合成provider（测试用） |
| `decision/replay.py` DecisionService / PITReplay | §6 回放引擎 | ✅ 落地：数据截断构造性防穿越+篡改测试 |
| `data/tdx_index.py` index_daily | §7 | ✅ 落地：.day直读（绕过个股市场前缀推断） |
| CLI `decide` / `replay` | §8 使用面 | ✅ 落地 |

## 待办（P2+）

- 分钟数据源（lc1/lc5 或付费）：profile_v1 校准与盘中L1精度；
- ~~capital-observer 自动接入 decide~~ ✅ 2026-09-15 落地：默认自动拉
  `http://127.0.0.1:8120/api/v1/context`（`--board BKxxxx` 指定板块；
  `--context-url` 改地址；`--no-context` 或服务不通 → unknown，绝不默认 neutral；
  输出带 `capital_context_source: auto|unreachable:...|file:...`）；
- ETF 官方日度份额通道 ✅ 2026-09-15 已在 capital-observer 上线
  （`/api/v1/etf/shares`，沪深直连，同源差分，T+1 事实）；
- legacy_weekday 取证校准（工作表P1清单）；
- 滚动窗口/样本外验证框架（裁决 regime 反转与 base_scores 失效）；
- 退出规则回放对比（E1-E5触发≠成交的成交模型）；
- 组合级（多票、行业约束生效）回放器。

## 使用

```bash
# 盘后单票建议（L2）
python3 -m stock_selector.cli decide --code 600519 --asof 2026-09-15T15:10:00

# 自动拉 capital-observer 上下文（默认行为；指定板块）
python3 -m stock_selector.cli decide --code 600519 --board BK0420

# 手动喂JSON（与自动互斥）
python3 -m stock_selector.cli decide --code 600519 --capital-context ctx.json

# PIT回放（EOD检查点）
python3 -m stock_selector.cli replay --codes 600519,300750 \
    --start 2026-09-07 --end 2026-09-15 --output output/replay.jsonl

# 回放切周级动能模式（对照组）
python3 -m stock_selector.cli replay --codes 600519 --mode unified ...
```

## 验收记录（2026-09-15）

- 全量测试 69 通过（21 旧 + 48 决策层）；
- 真实数据 decide：600519 @ 2026-09-15 15:10 → watch/low（regime=weak，动能 pullback_weakening）；
  喂 supportive 上下文后 unknowns=[] → medium（unknown≠neutral 规则生效）；
- 真实回放：3票×7个EOD时点=21条advice，无穿越（未来篡改测试通过）；
  弱市场下全部 watch 符合决策表预期。
