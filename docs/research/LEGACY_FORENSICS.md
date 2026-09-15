# 旧系统选股规则取证报告（LEGACY_FORENSICS）

- 取证日期：2026-09-16
- 取证性质：**只读取证**。`/root/.hermes/hermes-agent/**` 与 `/root/tdx_data` 全程未做任何修改；本文件是唯一产出物。
- 取证对象：旧选股系统（hermes-agent 根目录下的散装 Python 脚本族 + `release_2026-08-07/` 发布快照）。
- 对应工作表：`docs/SEMANTIC_RECOVERY_WORKSHEET.md` P1 清单五项（L81-88）。
- 引用格式：`文件:行号`（相对 `/root/.hermes/hermes-agent/`，发布快照目录 `release_2026-08-07/` 会显式标出）。

---

## 0. 旧系统管线与取证文件清单

旧系统盘后管线（`batch_runner.py:21-27`）：

```python
STEPS = [
    {"name": "month", "desc": "月线多头（用户本地跑，跳过）"},
    {"name": "weekbull", "script": "week_bull.py", "input": "月线多头股票池.csv", "output": "weekbull_输出.csv"},
    {"name": "weeksurge", "script": "week_surge.py", "input": "weekbull_输出.csv", "output": "weeksurge_输出.csv"},
    {"name": "daytrade", "script": "day_trade.py", "input": "weeksurge_输出.csv", "output": "daytrade_输出.csv"},
    {"name": "briefing", "script": "generate_briefing.py", "output": "daily_briefing.html"},
]
```

盘中管线为 `realtime_quotes.py`（实时价合成本周线）+ `sector_intraday.py`（板块盘中模式）。

本报告取证的核心文件（均真实存在，路径可复查）：

| 文件 | 角色 | 与 P1 疑点关系 |
|---|---|---|
| `week_surge.py`（584行，v4.0 2026-06-11） | 盘后周线 surge 主逻辑，含周一/周二/周三四/周五分支 | 疑点1、2 |
| `realtime_quotes.py`（477行，v3.1） | 盘中实时版周线 surge（腾讯/mootdx 实时价） | 疑点1、2 |
| `release_2026-08-07/day_trade.py`（598行，v4.2 2026-08-12） | 发布快照，含 weekly_surge_check v4.1 与改版 veto | 疑点1、2 |
| `day_trade.py`（根目录，368行，v4.0） | 盘后日线买点 | 疑点4（无流动性过滤的佐证） |
| `sector_intraday.py`（117行） | 板块盘中模式，唯一流动性过滤 | 疑点4 |
| `month.py`（192行） | 月线多头池 | 疑点5 |
| `weekg_v2.py` / `weekg.py` / `weekg_server.py` | 月线多头→周线金叉通道 | 疑点5（月线输入来源） |
| `day_realtime_report.py` / `after_market_automation.py` | 报告与盘后自动化 | 疑点3（"无退出逻辑"的佐证） |
| `使用说明.md` | 服务器流程文档 | 疑点5（monthly_bull.csv 来源） |

---

## 1. 疑点一：旧周内分支逻辑（周一/周二/周三-周四）

### 结论（先行）

**与 v2 两套假设都不一致，旧代码是一套独立的四分支结构：**

- **周一**：完全不看本周（本周才 1 天，"用日线合成的不准"）。只看**最近两个完整周**跑形态A（阴转阳反转）/形态B（双阳加速）；realtime 版另有一个合并语义——把"上周开盘→今日实时价"当作延续中的周线再跑一遍形态。
- **周二**：不是"正常评估"。必须**先通过周一逻辑（完整周形态门槛）**，然后再看本周日线三情形：周一涨→保留；周一跌周二涨→保留；双阴→要求周二缩量，否则剔除。
- **周三-周四**：**恰恰相反于"只看已完成周"——旧代码明确使用本周部分周**（本周开盘=本周首日开盘、收盘=最新收盘、量=累计量），与上一完整周比较，并**按已过交易日数线性折算到 5 天**（`/已过天数×5`）。
- **周五**：用完整周线（W-FRI resample 的最后一根=本周）直接判定。

任务描述中"v2 revised 模式假设：周一用量能否决 distribution_risk，周二起正常，周三-周四只看已完成周"——**第三点是错的**：v2 的 `revised_weekday` 代码实际也是周三四用部分周通用评估（`weekly_momentum.py:248-262`），旧代码同样用部分周；两点在这点上反而方向一致。真正与旧代码冲突的是 v2 对周一/周二的建模（见 §1.4）。

### 代码引用

**总分发**（先跑 veto，再按星期分支）——`week_surge.py:430-448`：

```python
def check_weekly_surge(daily, weekly):
    """根据当前星期几选择不同的筛选逻辑"""
    veto, info = bearish_heavy_turnover_veto(weekly)
    if veto:
        return False, info

    today = datetime.now()
    weekday = today.weekday()  # 周一=0, 周二=1, 周三=2, 周四=3, 周五=4

    if weekday == 0:  # 周一
        return check_surge_monday(daily, weekly)
    elif weekday == 1:  # 周二
        return check_surge_tuesday(daily, weekly)
    elif weekday in [2, 3]:  # 周三、周四
        return check_surge_wednesday_thursday(daily, weekly)
    elif weekday == 4:  # 周五
        return check_surge_friday(daily, weekly)
    else:  # 周末
        return check_surge_friday(daily, weekly)
```

**周一（盘后版）**——`week_surge.py:166-226`（摘录）：

```python
def check_surge_monday(daily, weekly):
    """周一 v4.0：前周、上周、本周三周的同样逻辑
    形态A - 阴转阳反转
    形态B - 双阳 + 量价比提升
    """
    ...
    # 本周（上一周完整周）
    tw = weekly.iloc[-1]
    pw = weekly.iloc[-2]  # 前周

    # 标准：本周+上周
    r = check_dual_yang(tw['open'], tw['close'], tw['volume'],
                         pw['open'], pw['close'], pw['volume'], '周一（双阳加速）')
    if r: return True, r

    if tw['close'] > tw['open'] and pw['close'] <= pw['open']:
        tc = (tw['close'] - tw['open']) / tw['open'] * 100
        score = min(abs(tc) / 2, 10) + 5
        return True, {'筛选模式': '周一（阴转阳反转）', ...}
```

> 取证发现（盘后版独有）：`week_surge.py:215-224` 的"周一补充：前推一组 — 上周+前周"分支传参与 L205-213 的标准分支**完全相同**（同一对 `tw`/`pw` 再算一遍），是复制粘贴产生的**死代码**，永不产生新筛选结果。

**周一（盘中实时版）**——`realtime_quotes.py:125-146`（摘录）：

```python
# ======================= 周一分支 =======================
if wd == 0:
    # 周一：看前周、上周、本周三周
    tw = w.iloc[-1]   # 上周（完整周，因为本周才周一，用日线合成的不准）
    pw = w.iloc[-2]   # 前周
    ppw = w.iloc[-3]  # 前前周

    # 用实时价替代本周close
    tw_open = tw['open']; tw_close = rp; tw_vol = tw['volume']

    # 1) 形态A/B标准：本周+上周
    r = check_dual_yang_boost(tw_open, tw_close, tw_vol, pw['open'], pw['close'], pw['volume'], '周一（双阳加速）')
    if r: return True, r
    r = check_reversal(tw_open, tw_close, pw['open'], pw['close'], '周一（阴转阳反转）')
    if r: return True, r

    # 2) 周一补充：前推一组 — 上周+前周（与标准形态判断周期前移）
    r = check_dual_yang_boost(tw['open'], tw['close'], tw['volume'], pw['open'], pw['close'], pw['volume'], '周一（前推一组：上周+前周双阳加速）')
    ...
```

注意实时版的语义：`tw_close = rp`（今日实时价）但 `tw_open = tw['open']`（**上周**的开盘）——它把"上周开盘→今天实时价"的合并走势当作延续中的本周来检查形态；而"前推一组"分支用上周原始完整 K 再查一遍（这里的"前推一组"是真实有效的，与盘后版的死代码不同）。

**周二**——`week_surge.py:229-297`（摘录）：

```python
def check_surge_tuesday(daily, weekly):
    """周二：首先按前两周筛选，再看本周日线 v4.0"""
    # 首先检查前两周
    ok, info = check_surge_monday(daily, weekly)
    if not ok:
        return False, {}
    ...
    # 情况1：周一涨，包含
    if monday_change > 0:
        info['筛选模式'] = '周二（前两周+周一涨）'
        ...
        return True, info

    # 情况2：周一跌，周二涨，包含
    if monday_change <= 0 and tuesday_change > 0:
        info['筛选模式'] = '周二（前两周+周一跌周二涨）'
        ...
        return True, info

    # 情况3：周一跌，周二跌，要求周二缩量
    if monday_change <= 0 and tuesday_change <= 0:
        tuesday_volume = tuesday_data['volume']
        monday_volume = monday_data['volume']

        if tuesday_volume < monday_volume:
            info['筛选模式'] = '周二（前两周+双阴缩量）'
            ...
            return True, info
        else:
            return False, {}
```

实时版周二（`realtime_quotes.py:148-165`）：先**递归**跑周一逻辑（`surge_check_with_realtime(w, d, 0, rp, rp_open)`），通过后若上周阳，检查"本周两天双阴递进缩量"（`mon_yin and tue_yin and tue['volume'] < mon['volume']`）：

```python
# ======================= 周二分支 =======================
elif wd == 1:
    # 周二：先跑周一逻辑
    ok, info = surge_check_with_realtime(w, d, 0, rp, rp_open)
    if not ok or d is None or len(d) < 2:
        return False,{}
    # 周二补充：上周阳 + 本周两天双阴递进缩量
    lw = w.iloc[-1]  # 上周
    if lw['close'] > lw['open']:  # 上周阳
        ...
        if mon_yin and tue_yin and tue['volume'] < mon['volume']:
            return True,{'筛选模式':'周二（前两周+双阴缩量）','强度评分':info.get('强度评分',8)}
    return True, {**info, '筛选模式':f'周{wdn[wd]}'}
```

**周三-周四**——`week_surge.py:300-377`（摘录）：

```python
def check_surge_wednesday_thursday(daily, weekly):
    """周三、周四 v4.0：形态A（阴转阳反转）+ 形态B（双阳+量价比提升）"""
    ...
    # 获取本周数据（本周一到今天）
    this_week_start = daily.index[-1] - pd.Timedelta(days=weekday)
    this_week_data = daily[daily.index >= this_week_start]
    ...
    # 本周数据
    this_week_open = this_week_data.iloc[0]['open']
    this_week_close = this_week_data.iloc[-1]['close']
    this_week_volume = this_week_data['volume'].sum()
    this_week_days = len(this_week_data)

    # 上周数据
    last_week = weekly.iloc[-2]
    ...
    # 折算到完整周
    this_week_close_scaled = this_week_open + (this_week_close - this_week_open) / this_week_days * 5
    this_week_volume_scaled = this_week_volume / this_week_days * 5

    # 形态A：上周阴 + 本周阳
    this_is_yang = this_week_close > this_week_open
    last_is_yin = last_week_close <= last_week_open
    if this_is_yang and last_is_yin:
        tc = (this_week_close - this_week_open) / this_week_open * 100
        tc_daily = tc / this_week_days * 5
        score = min(abs(tc_daily) / 2, 10) + 5
        ...

    # 形态B：双阳 + 量价比提升（用折算到完整周的数据比）
    this_is_yang_tw = this_week_close_scaled > this_week_open
    last_is_yang = last_week_close > last_week_open
    if this_is_yang_tw and last_is_yang:
        tc = (this_week_close_scaled - this_week_open) / this_week_open * 100
        lc = (last_week_close - last_week_open) / last_week_open * 100
        tv_ratio = this_week_volume_scaled / last_week_volume if last_week_volume > 0 else 1
        t_eff = abs(tc) / tv_ratio if tv_ratio > 0 else 0
        l_eff = abs(lc) / 1.0
        if t_eff > l_eff:
            ...
```

实时版周三四（`realtime_quotes.py:167-204`）同构，收盘用实时价 `this_week_close = rp`，且有本地日线未更新时的降级（L172-178：`⚠️ 本地日线未更新到当天（如周三只有周一数据）…取日线最后一天作为本周起始`）。

**周五**——`realtime_quotes.py:206-223` / `week_surge.py:380-427`：`lw=w.iloc[-2]; tw=w.iloc[-1]`（resample W-FRI 的最后一根即本周），形态A用 `check_reversal(tw['open'], rp, lw['open'], lw['close'], ...)`，形态B用 `check_dual_yang_boost(tw['open'], rp, tw['volume'], ...)`。

**发布快照的统一版**（v4.1，结构已变化）——`release_2026-08-07/day_trade.py:210-312`（摘录）：

```python
def weekly_surge_check(w, d, now_weekday, realtime_price=None, yesterday_close=None):
    """
    周线 surge 检查 v4.1：
    - 本周必须是阳线（实时价合成）
    - 量能放大
    - 按已过交易日天数折算（周一×5，周二×2.5，周三×1.67，周四×1.25，周五×1）
    - 排除周线滞胀：本周量价比必须 > 上周量价比
    - 盘中数据用实时价/昨日收盘价合成
    """
    ...
    # 按已过交易日天数折算
    # weekday: 0=周一, 1=周二, 2=周三, 3=周四, 4=周五
    if now_weekday <= 4:
        scale = 5.0 / (now_weekday + 1)
    else:
        scale = 1.0

    scaled_change = (this_close - last_close) / last_close * 100 * scale
    scaled_volume = this_volume * scale
```

注意：v4.1 的折算用**日历星期** `5.0/(weekday+1)`，而非 v4.0 周三四分支的**实际已过交易日数** `/days×5`（节假日短周时两者不同）。

### 语义解释

旧系统按星期分支的动机是**证据完整度分级**（工作表 3.7 行的"原始意图"得到证实）：周初本周证据不足→用完整周形态兜底，且周二起叠加本周日线微调；周中本周证据渐厚→部分周+折算；周末→完整周。四分支是"同一形态学（阴转阳/双阳加速）在不同证据完整度下的投影"，而不是四种不同规则。折算是**线性外推**（把已过 n 个交易日的走势等比放大到 5 日），用于和完整周同尺度比较。

### 对 v2 legacy_reconstructed 模式的校准建议

v2 `weekly_momentum.py:297-365`（`legacy_weekday`，mode=legacy_reconstructed_v0）对照旧代码有四处失真，建议**改结构**为主、改参数为辅：

1. **周一的"本周临时K优先"不存在**（v2 L326-338 先 `_classify_current(本周临时, 上周)`、非 ACTIVE_UP 才回退）。旧代码周一是**纯完整周**形态判定。校准：周一分支删掉"本周临时K优先"这一步，直接用 `_classify_completed(prev, prev2)`；若想保留实时版的"上周开盘→实时价"合并语义，应作为独立标签（如 `merged_week_extension`）而非通用分类。
2. **周二的门槛语义**（v2 L340-352）：旧代码要求"周一逻辑（完整周形态A/B）通过"才进入日线三情形，且三情形中**周一涨/周一跌周二涨是保留（正向确认）**、双阴缩量才是观察态。v2 只建模了双阴缩量（且 gate 是 `prev_state==ACTIVE_UP`，与"形态通过"同向但不等价）。校准：参数层面可保留 ACTIVE_UP 作 gate（近似），结构层面应补"周一涨→active_up 确认、周一跌周二涨→active_up 确认"两条路径（现有 `_classify_current` 落入通用分类可近似覆盖，但建议在 notes/metrics 里显式记录旧三情形标签）。
3. **周三四投影系数错误**（v2 L358-362）：`legacy_projected_week_pct = day_realized * 5.0` 是固定 ×5；旧代码是 `本周已实现涨幅 / 已过交易日数 × 5`（周一时两者才相等）。校准：改为 `realized / week_completion`（v2 已有 `week_completion` 字段=已过交易日数/5，与旧口径一致，且优于发布快照 v4.1 的日历星期折算——节假日短周时旧 v4.0 的交易日折算才是主干语义）。
4. **周三四的状态分类结构**：旧代码周三四不是"通用分类"，是形态A（**无任何量比要求**的阴转阳）优先、形态B（双阳+效率提升 `t_eff > l_eff`）次之。v2 的 `_classify_current` 用统一量比门槛（`volume_ratio >= 0.8`）会导致形态A类票被误杀。校准：若 legacy 模式目标是复刻旧口径，形态A路径应绕过量比门槛（或在 cfg 中给 `min_projected_volume_ratio` 提供"形态A豁免"开关）。

---

## 2. 疑点二：看空/下跌否决（放量阴线 veto）阈值

### 结论（先行）

**旧代码存在两代 veto，v2 与两者都不完全一致：**

- **v4.0（主干，`week_surge.py` 与 `realtime_quotes.py`）**：周线帧**最后一根 bar**（盘中运行为最近完整周或已更新的部分周）收阴（`close < open`）**且** 成交额（无 amount 列时退回成交量）**> 前 4 周均值 × 1.5** → 一票否决。基线=**前4周均值**，指标=**amount 优先**。
- **v4.1（发布快照，`release_2026-08-07/day_trade.py`）**：**过去 4 周窗口内任意一周**满足 收阴 + 收盘低于前一周收盘 + 当周量 ≥ 前一周量 × 1.5 → 否决。基线=**前一周量**，指标=**volume**（不看 amount）。
- v2 `_distribution_risk`（`weekly_momentum.py:102-106`）：`close < open 且 volume ≥ 1.5 × 前一周 volume`。阈值 1.5 与旧一致、收阴定义一致；但**基线（前一周 vs 旧前4周均值）与指标（仅 volume vs 旧 amount 优先）不一致**——**部分一致**。

### 代码引用

**v4.0 veto**——`week_surge.py:124-163`（`realtime_quotes.py:37-76` 逐字相同）：

```python
def bearish_heavy_turnover_veto(weekly, lookback_weeks=4, threshold=1.5):
    """
    一票否决：
    最近一周收阴，且周成交额显著高于前 lookback_weeks 周均值。

    优先使用 amount（成交额）；如果没有 amount，再退回 volume。
    """
    if weekly is None or len(weekly) < lookback_weeks + 1:
        return False, {}

    metric_col = 'amount' if 'amount' in weekly.columns else 'volume'
    if metric_col not in weekly.columns:
        return False, {}

    last = weekly.iloc[-1]
    prev = weekly.iloc[-(lookback_weeks + 1):-1]
    ...
    bearish_week = last['close'] < last['open']
    heavy_turnover = last_metric > prev_mean * threshold

    if bearish_week and heavy_turnover:
        return True, {
            '筛选模式': '周线放量下跌一票否决',
            ...
        }
```

调用位置：`week_surge.py:432-434`（`check_weekly_surge` 入口、**任何星期分支之前**）；`realtime_quotes.py:90-92`；`release_2026-08-07/day_trade.py:299-300`（在量价比/量能检查**之后**）。

**v4.1 veto（改版）**——`release_2026-08-07/day_trade.py:190-207`：

```python
def bearish_heavy_turnover_veto(w, lookback_weeks=4, threshold=1.5):
    """
    周线空头/滞胀检查：若过去 lookback_weeks 周内出现明显放量阴线，则否决。
    """
    if w is None or len(w) < lookback_weeks + 2:
        return False
    recent = w.tail(lookback_weeks + 1).iloc[:-1]
    max_vol = recent['volume'].max()
    if max_vol <= 0 or np.isnan(max_vol):
        return False
    for i in range(1, len(recent)):
        row = recent.iloc[i]
        prev = recent.iloc[i - 1]
        if row['close'] < row['open'] and row['close'] < prev['close']:
            vol_ratio = row['volume'] / prev['volume'] if prev['volume'] > 0 else 1
            if vol_ratio >= threshold:
                return True
    return False
```

### 语义解释

- v4.0：**只查最近一根周线**，判断"上周（或刚更新出的本周部分周）是否放量收阴"。"放量"的参照系是前 4 周的**平均水平**，且优先用**成交额**（金额口径更接近"资金撤退"语义），无额才用量。
- v4.1：把否决从"最近一根"扩展为"**回看 4 周内任意一根**"，且阴线定义更严（还要 `close < prev_close`，即创周收盘新低），量能参照系改为**紧邻前一周**（周对周放量）。
- 两代都把 veto 放在 surge 判定路径上作为**硬否决**（v4.0 在最前、v4.1 在最后，效果同为短路）。

### 对 v2 的校准建议

- **参数校准**（`bearish_turnover_veto_ratio` 已=1.5，正确）：基线应从"前一周量"改为**前 4 周均量**（对应工作表 3.6 行"阈值需对旧值"）；指标应**amount 优先、volume 回退**（v2 周线聚合已有 amount 列，`weekly_momentum.py:70`）。
- **结构校准**：v2 目前只在"当前 bar vs 基线"上判 distribution_risk。旧 v4.1 提供了第二个语义："**过去 4 周窗口内出现过放量阴线**"也应触发（可作独立字段 `recent_distribution_weeks`，不必做成硬否决，供 revised 模式的 carry_forward 否决条件使用——这正是工作表 3.2/3.6 拟修订所要求的）。
- 周一"当日内放量阴线否决 carry"（v2 `revised_weekday` L189-207）在旧代码中**没有对应物**（旧周一对当日盘中 bar 不做 veto，veto 只作用于周线帧最后一根 bar）。这是 v2 的工程新增，取证结论是"无旧依据"，是否保留属于设计决策而非校准。

---

## 3. 疑点三：旧退出逻辑（时间止损/跟踪止损/结构止损）

### 结论（先行）

**未找到任何退出/止损实现。** 旧系统是纯选股（买入侧信号）系统，没有任何"持仓后何时卖"的代码——不存在时间止损、跟踪止损、结构止损的任何参数。全代码库中与"止损"唯一相关的是报告文案里的一句免责建议。

### 代码引用

全树 grep（`止损|止盈|清仓|减仓|跟踪止损|时间止损|结构止损|卖出`，限定选股脚本与文档）仅命中：

`day_realtime_report.py:197-201`（Markdown 报告的固定建议块，无任何参数）：

```python
    markdown += f"""
### 💡 投资建议

1. **重点关注:** 评分前10名股票
2. **风险控制:** 设置止损位，控制仓位
3. **时机把握:** 结合大盘走势选择入场时机
4. **分散投资:** 避免过度集中在单一板块
```

`after_market_automation.py:161`（唯一的"持仓后"动作是打标签记录，非退出规则）：

```python
        df['跟踪状态'] = '周线金叉'
```

另：`sector/*.py` 中的"继续跟踪/减仓观察"是**板块评级标签**（板块强弱描述），不是个股退出规则。

### 语义解释

旧系统的产出止于"买入候选名单+评分"（weeksurge→daytrade→daytrade_输出.csv / realtime_selection.csv），持仓管理在系统之外人工完成。工作表 6.2 行"旧退出规则 ?"的答案就是**"无"**。

### 对 v2 的校准建议

**没有可校准的旧参数。** v2 的 E1-E5 退出体系（结构失效/组合口径）是全新设计，不应再标注"legacy"或与旧系统对齐；建议在工作表 6.2 行直接填"旧系统无退出逻辑（已取证）"，E1-E5 参数完全交给回测定（这也是既有计划"候选集回测后定"的确认）。

---

## 4. 疑点四：旧流动性窗口（成交量/成交额检查窗口与阈值）

### 结论（先行）

**旧主漏斗（month→week_bull→week_surge→day_trade→realtime_quotes）没有任何流动性过滤**——没有成交额下限、没有换手率下限、没有 N 日窗口；唯一的数量类门槛是**历史数据长度**（周线≥35根、日线≥60根）。

旧系统唯一的流动性过滤在**盘中板块模式**：`sector_intraday.py` 用腾讯实时行情的**当日换手率**做硬过滤，**换手率 < 2.0% 直接剔除**（"铁律"，在买点检查**之前**执行）。**没有回看窗口**（不是 N 日均量/均额，就是当日实时换手率）。

v2 的"流动性用近 20 日数据"窗口**无旧代码依据**——旧系统根本不存在多日流动性窗口这个概念。

### 代码引用

`sector_intraday.py:4`（模块 docstring）：

```python
"""板块盘中选股：参数化板块列表
复用 realtime_quotes 的腾讯实时接口与 daytrade_check 实时买点逻辑。
板块模式跳过周线 weeksurge 检查（老刘规则），硬过滤换手率 < 2%。
用法: python3 sector_intraday.py 软件开发 互联网电商
"""
```

`sector_intraday.py:47-48`（换手率取自腾讯行情 f[38] 字段，当日实时值）：

```python
                    'vol': float(f[6]) if f[6] else 0,     # 成交量(手)
                    'turnover': float(f[38]) if f[38] else 0,  # 换手率%
```

`sector_intraday.py:69-82`（硬过滤实现）：

```python
    # 换手率硬过滤（先过滤再看买点，铁律）；被剔除票也跑一遍买点，供报告"高分但剔除"名单
    rejected_entry = None
    if m['turnover'] < 2.0:
        d = daily_for(code)
        if d is not None and len(d) >= 5:
            bt0, ts0, bi0 = daytrade_check(d, m['rp'], m['yc'], ss=0, rvol=m['vol'])
            ...
        skipped_turnover.append((code, name, m['turnover']))
        ...
        continue
```

`sector_intraday.py:97`（漏斗口径确认）：

```python
print(f"\n池子 {len(pool_df)} → 实时价缺失 {len(skipped_no_rt)} → 换手率<2%剔除 {len(skipped_turnover)} → 日线缺失 {len(skipped_no_daily)} → 买点 {len(results)}")
```

主漏斗无流动性过滤的佐证——数据长度门槛即全部前置条件：`week_surge.py:29`（`MIN_WEEK_DATA = 35`）、`week_surge.py:70`（`len(df) > MIN_WEEK_DATA * 5`）、`day_trade.py:30`（`MIN_DATA_DAYS = 60`）、`realtime_quotes.py:24`（`if len(w)>=35`）、`realtime_quotes.py:237`（`if d is None or len(d)<60`）。另注意 veto 函数"优先 amount"（§2）只是**否决指标**的口径选择，不是流动性下限。

### 语义解释

旧系统的"流动性"概念只有一个操作化定义：**当日实时换手率 ≥ 2%**（板块盘中模式的准入铁律）。它无窗口、无成交额绝对值阈值（不设"日成交额 X 亿"这类门槛）。月线/周线/日线主漏斗对此完全不设限——流动性风险交由"数据长度门槛"（有足够历史）与人工把关。

### 对 v2 的校准建议

- 工作表 5.1 行"旧流动性过滤窗口 ?"应填：**"旧=当日实时换手率≥2%（仅板块盘中模式）；主漏斗无流动性过滤"**。
- v2 risk_filters 若要贴近旧语义：加一个**当日换手率≥2%** 通道（实时口径）；"近 20 日成交额窗口"可以保留，但必须明确标注为 **v2 新增工程化（无旧依据）**，且其 PIT 化改造（仅用 as_of 之前窗口）不受本次取证影响——旧系统没有可对齐的锚点。
- 不要把旧系统的"35周/60日数据长度门槛"误写成流动性过滤：那是历史充分性条件。

---

## 5. 疑点五：旧月线 temp-bar（月末未走完时的处理）

### 结论（先行）

**旧代码没有显式的"临时补 bar"逻辑——既没有构造代码、也没有注释提及**。效果上等价于"隐式临时月K"：`month.py` 把日线 `resample('ME')` 后，**当月未走完时 resample 自然生成一根部分月K**（open=本月首个交易日开盘、close=最新收盘、high/low/volume/amount 为月初至今累计），这根 bar **不加区分地**直接参与 MA5>MA10>MA20 判定和当月涨跌幅计算。没有折算、没有完整度标记、没有任何"月末特判"。

v2 的"含当月未完整月K作为临时月"（工作表 1.1 行）与旧实现**效果一致**；v2 额外记录 `monthly_bar_complete` 是新增工程化（旧系统无此区分），不构成语义冲突。

### 代码引用

`month.py:69-89`（月线构造——resample 后仅 dropna，无任何部分月处理）：

```python
def get_monthly_data(reader, code):
    """获取个股月线数据"""
    try:
        df = reader.daily(symbol=code)
        if df is not None and len(df) > MIN_MONTH_DATA * 20:
            # 转换为月线
            df.index = pd.to_datetime(df.index)
            monthly = df.resample('ME').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
                'amount': 'sum'
            })
            monthly = monthly.dropna()
            if len(monthly) >= MIN_MONTH_DATA:
                return monthly
```

`month.py:91-122`（多头判定——最后一根（可能部分）月K直接进 MA 与涨跌幅）：

```python
def check_monthly_bull(monthly):
    """
    判断月线多头排列
    条件：
    1. MA5 > MA10 > MA20（月线多头排列，数据量有限）
    2. 最近一个月上涨或企稳
    3. 价格在MA5附近（强势）
    """
    ...
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ...
    # 条件1: MA5 > MA10 > MA20（月线多头排列基础）
    if not (last_ma5 > last_ma10 > last_ma20):
        return False, 0

    # 条件2: 本月不暴跌（最多允许-8%回调）
    month_change = (close_last / monthly['close'].iloc[-2] - 1) * 100
```

（注：`-8%` 只出现在注释里，代码实际用 `month_change` 分档计分（L127-133：`>0` +20、`>-5` +10），没有 -8% 硬线。）

服务器流程的月线输入是**外部提供**的（不是本机 temp-bar 计算）——`使用说明.md:73-75`：

```markdown
- `monthly_bull.csv` - 月线多头股票列表
  - 格式：代码,名称,信号类型,趋势强度
  - 来源：老刘定期提供
```

周线金叉通道同样只消费该 CSV：`weekg_server.py:343`（`df_monthly = pd.read_csv(monthly_file, encoding='utf-8-sig')`）。

反证（找不到的正面声明）：全树 grep `临时|temp_bar|tempbar|月末|未走完|未完成` 在 `.py` 中无月线相关命中（唯一命中为 `release_2026-08-07/sentiment/analyzer.py:152` 的"临时 API 抖动"，无关）。

### 语义解释

旧系统对"月未走完"的态度是**不处理**：部分月K被当成正常月K用。这意味着月中运行时，月线多头的 MA 排列与"最近一个月上涨或企稳"都含有**进行中的当月数据**（月初大涨会让当月 bar 偏阳、MA 抬升）。这是工作表 1.1 行"完整月/临时月未区分?"的实证答案：**旧系统确实未区分**。

### 对 v2 的校准建议

- v2 保留"临时月K参与判定"即等于旧行为，**无需改参数**；`monthly_bar_complete` 双字段（工作表 1.1 拟修订）建议保留——它不改变结果，只把旧系统的隐式状态显式化，并支撑"月线背景层盘中只读"（1.2 行）的实现。
- 若追求严格复刻旧口径，注意一点细节：旧月线 resample 用 `'ME'`（自然月末），v2 若按 ISO 周/交易日切月需确认与自然月对齐（农历节假日不影响月切分，但跨月盘中当日的归月应与 resample 一致：当日数据计入当月）。

---

## 6. 取证覆盖度声明

### 已找到原文并逐行核对的文件

全部位于 `/root/.hermes/hermes-agent/`（只读，未修改任何字节）：

- `week_surge.py`（全 584 行通读）——疑点1、2 主证据
- `realtime_quotes.py`（关键段 L1-280 通读）——疑点1、2 盘中版
- `release_2026-08-07/day_trade.py`（L150-479 通读）——疑点1、2 发布快照 v4.1/v4.2
- `day_trade.py`（根目录，全 368 行通读）——疑点4 佐证
- `sector_intraday.py`（全 117 行通读）——疑点4 主证据
- `month.py`（全 192 行通读）——疑点5 主证据
- `weekg_v2.py`（全 331 行通读）——疑点5 佐证（月线输入消费方）
- `batch_runner.py`（L15-45）——管线结构
- `day_realtime_report.py`（L190-210）、`after_market_automation.py`（grep 定位）——疑点3 佐证
- `使用说明.md`（L1-100）——疑点5 佐证（monthly_bull.csv 外部来源）
- 旁证 grep 覆盖：`weekg.py`、`weekg_server.py`、`dayw_realtime.py`、`week_bull.py`、`day.py`、`day_v2.py`、`find_yin*.py`、`sector/`、`release_2026-08-07/` 全目录

### 未找到原文的疑点及原因

- **疑点3（退出逻辑）：确认性缺失，非覆盖不足。** 对全库（含 `.py`/`.md`，排除 hermes 框架自身的 tests/gateway/agent 等无关目录）做了 `卖出|止盈|清仓|减仓|止损|持有N天` 全量检索，选股脚本中唯一命中是报告文案（§3 引用）。结论"旧系统无退出实现"是**穷尽检索后的否定性结论**。
- **疑点5（显式 temp-bar 代码）：确认性缺失。** `临时/temp/月末/未走完/未完成/synth.*月` 等模式全库检索无月线相关命中；旧系统的"临时月K"以 resample 隐式形态存在（§5 已取证其行为）。若"temp-bar"一词来自老刘口述，其指的应该就是这种 resample 隐式行为，而非一段专门代码。
- **未检查的范围**：`/root/tdx_data`（纯数据，无代码）；hermes 会话记录/聊天日志（非代码，且不属于"代码取证"）；`capital-observer`（任务明确排除）；`stock-selector-v2` 本体（新系统，仅读其 `weekly_momentum.py` 与工作表作对照，未修改）。
- **`/root/project/workspace/` 下旧仓库副本排查**：未发现旧选股系统副本。`a-share-clean/` 仅为通达信日线数据同步工具（`sync_vipdoc_daily.py`，官方 datatool 增量合并，无选股逻辑）；`stock-selector-v2-pre-public-20260915163845.bundle` 是 v2 自身的 git bundle（属新系统，排除）；`down/` 为数据目录。

### 取证可信度备注

- 所有行号来自 2026-09-16 当日文件状态；`week_surge.py`（7月20日mtime）与 `release_2026-08-07/` 快照存在版本差（v4.0 vs v4.1/v4.2），本报告对两代口径**分别**取证并在正文标明，未做合并假设。
- `week_surge.py:215-224` 死代码的判定基于参数逐一比对（与 L205-213 传参完全一致），如需双重确认可运行等价性检验（本次只读任务未执行任何脚本）。
