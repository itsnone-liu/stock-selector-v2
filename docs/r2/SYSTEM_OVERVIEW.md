# 资本成本与筹码生命周期选股体系 — 完整说明文档

> 版本：2026-10-08（R2-9 验收后）。本文是体系的权威总说明：策略逻辑、全部指标定义、决策规则、运行方式。
> 研究历史与证据见 docs/r2/ 各门文档（R2-6/7/8/9 及 ROUND2_CHARTER）。

---

## 一、体系哲学

**不预测涨跌时机，只判断资本结构的有效性。**

核心命题：股价下方存在"资本成本支撑带"——大量持仓者的成本密集区。价格接近该区域时，抛压枯竭、承接增强，形成统计上可验证的低风险位置。体系回答五个问题：

| 问题 | 答案 | 来源 |
|---|---|---|
| 钱的环境怎样？ | L1 市场状态 | CD45 |
| 做哪个方向？ | L2 板块状态 + T2 | CD1b |
| 板块里选谁？ | T3 个股相对强度 | R2-7 |
| 哪里建仓风险低？ | 资本成本带位置 | R2-6 |
| 还能不能继续拿？ | 支撑完好 + HL_RAISE | R2-8A |
| 哪里必须认错？ | BROKEN 硬退出 | R2-6 |
| 什么时候加仓？ | **不预测启动**，分批规则自然升仓 | R2-8 CLOSED |
| 破位后何时再看？ | 不抢左侧（REBASE_WEAK） | R2-9 |

**方法论红线**（多度独立验证后冻结的 kill list）：
- 户数下降 ≠ 主力吸筹 ≠ 看涨（5 次证伪，含 R2-9）
- 龙虎榜机构大买 ≠ 未来上涨
- 破位 ≠ 机构跑路（真相：杠杆撤退+筹码集中）
- 短期新高收复 ≠ 启动（T4 死）
- RS 加速 / 收复中值 / 反弹高效 / 收复新高——一切"已经涨起来"的口径都选到晚位（四度反向一致）
- 启动时点不可由 EOD 数据可靠提前识别 → ADD_TRIGGER = UNRESOLVED

---

## 二、决策链与 Tier 体系

每晚对全市场 ~5,400 只股票产出决策卡。判定顺序（前者优先）：

```
1. EXIT            支撑态=BROKEN → 硬退出，无条件
2. CONFIRM_CANDIDATE  带内(IN_SUPPORT/UNDERCUT_TEST) ∧ T3 ∧ (BULL 或 HL_RAISE)
3. RISK_HOLD       带内 ∧ T3 ∧ BEAR ∧ 无HL_RAISE → 不加仓、只观察/小仓
4. BUILD           带内/回踩带 ∧ T2 ∧ ¬BEAR → 可分批建仓
5. WATCH           带上方 ∧ T2 → 等回落进带
6. NO_BUILD        其余（含 BEAR 下仅 T2 者）
```

BEAR 门：L1 五日多数票 ∈ {R_DEPRESSED, R_RISK_OFF} 时，T2-only 一律降为 NO_BUILD，T3-only 降为 RISK_HOLD——弱市里只有"个股强 + 价格结构稳(HL)"才保留观察资格。

---

## 三、指标定义（全部冻结口径）

### 3.1 L1 市场状态（CD45，五状态）

市场级仓位预算层，全市场统一计算：
- **R_RISK_ON_BROAD** 宽基风险偏好（可正常建仓）
- **R_RISK_ON_NARROW** 结构性/窄基风险偏好（只在强板块内操作）
- **R_REBOUND_MIXED** 反弹混合（谨慎，半仓思维）
- **R_RISK_OFF** 规避（禁新仓）
- **R_DEPRESSED** 萧条（最低仓位；与 RISK_OFF 同属 BEAR 组）

**五日多数票**：单日 regime 几乎不持续（中位 1–2 天），决策取最近 5 个交易日多数票，消除单日噪声误开误关 BEAR 门。五状态定义与 BEAR/BULL 分组规则冻结不动。

### 3.2 T1 / T2 / T3 三层选择（R2-7，独立角色不合成评分）

- **T1（市场层/风险预算）**：L1 状态决定整体风险预算——BULL 正常、BEAR 折扣/关门。
- **T2（板块层/方向过滤）**：板块 20 日累计收益 > 大盘 20 日累计 → 板块方向合格。BEAR 下 T2 单独不构成建仓理由。
- **T3（个股层/选股）**：个股 20 日收益 > 所属板块 20 日累计 → 相对强度合格。是 CONFIRM 的最低资格。
- ~~T4（收复新高确认）~~：**已裁死**。数据：收复 10/15 日新高无预测价值，量确认回收同样无效。

### 3.3 资本成本带（R2-6，核心，算法冻结）

- **窗口**：500 日滚动。典型价 = (high+low+close)/3，按成交量分入 100 个价格 bin。
- **带**：从成交量直方图上找覆盖 **30% 总量**的最窄连续价格区间 → [cost_band_low, cost_band_high]，中值 = (low+high)/2。
- **带宽**：(high−low)/mid，衡量成本分散度。
- **qfq 纪律**：成本带只用前复权价。TDX 裸价仅用于交叉校验/当日涨跌/停牌检测，绝不入带。
- **支撑持久性**（R2-6 验证结论）：有效带被击穿需要持续卖压——带内/带缘买入的 60 日破位率 ~11–15%，远低于随机位置。

### 3.4 支撑态（价格 × 带的位置关系）

| 状态 | 定义 | 语义 |
|---|---|---|
| ABOVE_SUPPORT | close > band_high | 带上方，等回落 |
| IN_SUPPORT | band_low ≤ close ≤ band_high | 带内，低风险区 |
| UNDERCUT_TEST | close < band_low（未确认破位） | 带下试探，最敏感观察位 |
| BROKEN | 连续 5 根收盘 < band_low×0.95 | **结构死亡，硬退出** |

- **BROKEN 触发线** = band_low × 0.95；5 日收盘确认，不等资金面确认。
- **exit_distance** = px/(band_low×0.95)−1：负=已越线（待确认数天数），小正=临界预备队。
- **破位后统计事实**：全部破位事件后续中位再跌 −15%，BEAR 中 −22%；但 ~27% 十日内收复——所以 EXIT 后按 R2-9 结论**不抢新支撑左侧**。

### 3.5 HL_RAISE（R2-8A，HOLD/RISK 许可，非买入信号）

- **定义**：min(low[近5日]) > min(low[第6–10日前]) —— 低点抬升。
- **证据**：brk 全线下降（ALL 15.3→12.3%，BEAR 32.3→**19.8%**），双时代一致；但 conv 无增量 → 不是启动器。
- **语义**：「不告诉你马上会涨，只告诉你价格结构正在变得更不容易崩」→ 持有许可。
- **产品化**：BEAR 下 T3 ∧ 无 HL_RAISE → RISK_HOLD（不因相对强而乐观）。

### 3.6 E3 筹码维度与置信度（描述性，不入决策）

- **E3 筹码质量分**（0/1/2/−1）：成本带内筹码占比/集中度的分档。**只解释不筛选**（E3=0 当日表现最差仅是描述性发现）。
- **confidence** = min(0.9, 0.3+0.1×sup+0.35×cov)；cov<0.5 时封顶 0.5。度量的是**证据数量与一致性**，不是上涨概率。仅排序展示用，不参与 tier 判定。
- **季度持仓数据**（户数/户均/前十大）：**只作解释性 descriptor**，available_at=季末+45 自然日后才可进 tradable 层；方向由数据决定（结论至今：无增量）。

### 3.7 盘中警报（intraday_scan，冻结重层+实时轻层）

昨日冻结的带/tier × 实时报价（基准=上证指数）：
- **CROSS_TRIGGER**：盘中价 < 触发线（预警；EXIT 仍以收盘 5 日确认为准）
- **NEAR_TRIGGER**：距触发线 <2% 预备队
- **BAND_TEST**：带上方回落进带 → 变为可评估 BUILD（仅 candidates/all 池有意义）
- **BAND_BREAKOUT**：带内 → 突破带上沿
- **RS_VS_INDEX**：当日涨幅 > 上证 +1pp
- **n_missing**：报价缺失数（>0 必须显式，防静默丢票）

---

## 四、R2-9 Structural Rebase 结论（BROKEN 之后）

26,820 个破位事件全量：新带（120 日窗）形成率 75.8%（中位 78 bar），但首测 **brk60=61.7%、SURVIVED 仅 30.7%**（原生带 ~11–15%）→ **REBASE_WEAK**：价格稳定 ≠ 新资本结构有效；ownership 三组（CONC/FLAT/DISP）在形成速度与存活上均无区分 → 「BROKEN 后长期回避」是数据支持的策略。状态机终态：VALID → BROKEN → (REBASE_PENDING → NEW_SUPPORT →) SURVIVED/FAILED，其中新支撑质量普遍不达标。

---

## 五、每日运行体系

### 5.1 收盘全链（Hermes 执行，18:10 后）

```bash
cd /root/project/workspace/stock-selector-v2 && \
.venv/bin/python src/r2/daily_update.py --day $(date +%F)
```

| 步 | 内容 | 产物 | 实测耗时 |
|---|---|---|---|
| A | 价格增量（腾讯同源+TDX 逐bar校验+原子写回） | daily_fullmarket 更新 + update_\<day\>.json | ~117min |
| C | 5 构建器全量重建（L2四轴→L1→L2状态→L3池→L4 episode）+ 历史校验（轴=严格相等，生命周期表=键存活） | 轴文件滚动 | ~13min |
| E | 全量 scan + 日期快照 | scans/current_scan_\<day\>.json | ~3min |
| F | 日报：迁移表/固定切片交叉/池表现/BROKEN临界队列(仅CONFIRM/BUILD/WATCH) | report_\<day\>.json + crossval_history.jsonl | ~10s |

### 5.2 盘中轻扫（11:35 / 13:55）

```bash
.venv/bin/python src/r2/intraday_scan.py --pool candidates   # 10秒
```

### 5.3 慢频（H）

e5 板块扩展每周一；holders 每月 1 号；机构持仓每季；宇宙补新每月（E 每月补新）。详见 `docs/r2/DAILY_UPDATE_RUNBOOK.md`（含失败恢复/除权处理/验收清单）。

### 5.4 数据源

- **价格史**：腾讯 fqkline（qfq+裸价，end 参数排他=明日）；**本地 TDX 镜像** /root/tdx_data/vipdoc（每日 ~18:00 自动同步）为校验权威。
- **停牌处理**：TDX 无 bar = 停牌，统计中剔除（腾讯 pct=0 是占位符不是真涨跌）。
- **除权**：腾讯 qfq 整段重定基 → overlap 校验不过 → fail-closed 跳过，手工整段重取（runbook §4.3）。

---

## 六、决策表（操作口径汇总）

| 场景 | 动作 |
|---|---|
| BULL + T2 + 带内/回踩带 | BUILD：分批建仓（首仓≤计划1/2） |
| + T3 | CONFIRM_CANDIDATE：完整资格，可上正常仓位 |
| BEAR + T3 + 带内 | 有 HL_RAISE → 持有观察；无 → RISK_HOLD 不加仓 |
| BEAR + 仅 T2 | NO_BUILD |
| 带上方 + T2 | WATCH：等回落进带再评估 |
| 任何时点 BROKEN 确认 | EXIT 硬退出，不等待、不摊平 |
| 盘中 CROSS_TRIGGER | 收盘前盯住；连续第 5 日收盘越线即 EXIT |
| BROKEN 后 | 不抢新支撑左侧（REBASE_WEAK）；新带首测存活才重新入池评估 |
| 加仓 | 不预测启动；价格验证（带内企稳→HL→带中→带上）分批推进 |

## 七、已冻结的研究结论索引

- R2-6 成本带有效性：PASS（生产）
- R2-7 T1–T3：PASS（生产）；T4：DEAD
- R2-8A HL_RAISE：HOLD/RISK 层 PASS；R2-8B 早转折微结构：FAIL → ADD_TRIGGER=UNRESOLVED，Activation 关闭
- R2-9 Rebase：REBASE_WEAK；ownership 解释无增量
- 吸筹信号学（Round 1）：NO-GO
- 五次证伪清单见 §一 kill list
