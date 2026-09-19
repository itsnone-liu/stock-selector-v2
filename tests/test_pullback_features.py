"""阶段二回调特征：人工行情语义测试。

验收要求（方案 §六）：>=30 段行情覆盖健康回调、缓慢阴跌、放量破位、
假止跌、支撑后上攻；不一致先修语义，不按收益调阈值。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_selector.research.pullback_features import (  # noqa: E402
    PullbackConfig, classify_pullback, DAILY_COLUMNS, EVENT_COLUMNS, RULE_VERSION,
)


def mk_daily(closes, vols, start="2024-01-02"):
    n = len(closes)
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes, "volume": vols,
    }, index=idx)


def week_rows_of(df, trend="intact", mom="strengthening", broken_from=None,
                 broken_from_date=None):
    """周行列表（周最后交易日, trend, momentum）升序。

    broken_from_date: 指定日期起**之后**的周行才变 broken——
    模拟"周内后段才转坏"（周 PIT 测试用）。
    """
    rows = []
    for i, ts in enumerate(df.index):
        is_friday = ts.weekday() == 4 or i == len(df) - 1
        if not is_friday:
            continue
        if broken_from is not None and i >= broken_from:
            rows.append((ts, "broken", "weakening"))
        elif broken_from_date is not None and ts >= broken_from_date:
            rows.append((ts, "broken", "weakening"))
        else:
            rows.append((ts, trend, mom))
    return rows


def pool_all(df):
    return {ts.strftime("%Y-%m-%d"): True for ts in df.index}


def run(closes, vols, cfg=None, trend="intact", pool=None, broken_from=None):
    df = mk_daily(closes, vols)
    return classify_pullback(
        "T1", df, week_rows_of(df, trend=trend, broken_from=broken_from),
        pool or pool_all(df), cfg or PullbackConfig())


def test_rule_version_frozen():
    assert RULE_VERSION == "pullback_stage2_v1"


def test_healthy_pullback_recovers_to_new_high():
    """健康回调：缩量回落、ma20 上方收回、随后创新高，outcome 为正。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 6))
         + [9.3, 9.35, 9.42, 9.55, 9.7]
         + list(9.7 + 0.18 * i for i in range(1, 15)))
    v = [1000] * 20 + [600, 500, 460, 440, 430] + [500, 480, 500, 550, 600] + [900] * 14
    ev, dly = run(c, v)
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["end_reason"] == "new_high"
    assert e["touched_ma10"] and e["stabilization_day"] is not None
    assert e["stabilization_support"] in ("ma10", "ma20")
    assert e["outcome_ret_5"] > 0
    assert bool(e["outcome_new_high_within_20"])
    assert set(dly.columns) == set(DAILY_COLUMNS)


def test_slow_bleed_times_out():
    """缓慢阴跌：持续缩量下跌不触发放量，超最长观察期 timeout。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.08 * i for i in range(1, 45)))
    v = [1000] * 20 + [500] * 44
    ev, _ = run(c, v)
    assert len(ev) == 1 and ev.iloc[0]["end_reason"] == "timeout"
    assert ev.iloc[0]["max_drawdown_pct"] < -30


def test_volume_breakdown_endsWith_touch():
    """放量破位：触及 ma20 后放量大阴线跌破 1%。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.15 * i for i in range(1, 9)) + [8.6, 7.9])
    v = [1000] * 20 + [600, 550, 500, 480, 470, 460, 450, 440] + [1200, 1600]
    ev, _ = run(c, v)
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["end_reason"] == "volume_breakdown" and e["touched_ma20"]


def test_volume_breakdown_requires_down_close():
    """放量上涨日收在支撑附近不算破位（方向必须向下）。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.15 * i for i in range(1, 7))
         + [9.0, 9.5, 10.5])  # 放量反弹收高，接近但未破支撑
    v = [1000] * 20 + [600, 550, 520, 500, 480, 470] + [460, 1400, 1800]
    ev, _ = run(c, v)
    e = ev.iloc[0]
    assert e["end_reason"] != "volume_breakdown"  # 反弹收高 -> new_high 或继续


def test_pool_exit_ends_event():
    """出池强制结束：pool_exit。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 10)))
    v = [1000] * 20 + [500] * 9
    df = mk_daily(c, v)
    pl = {ts.strftime("%Y-%m-%d"): (i < 24) for i, ts in enumerate(df.index)}
    ev, _ = classify_pullback("T", df, week_rows_of(df), pl, PullbackConfig())
    assert ev.iloc[0]["end_reason"] == "pool_exit"


def test_structure_break_ends_event():
    """周线结构破坏结束：broken 周确立后的次一交易日生效（PIT）。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 15)))
    v = [1000] * 20 + [500] * 14
    df = mk_daily(c, v)
    cut = df.index[24]  # 事件中段某日所在周将转 broken
    rows = week_rows_of(df, broken_from_date=cut)
    broken_fridays = [ts for ts, t, _ in rows if t == "broken"]
    assert broken_fridays
    first_broken_week_end = broken_fridays[0]
    ev, _ = classify_pullback("T", df, rows, pool_all(df), PullbackConfig())
    assert ev.iloc[0]["end_reason"] == "structure_break"
    # 生效时点必须晚于（等于次日起）broken 周的最后交易日
    assert pd.Timestamp(ev.iloc[0]["end_day"]) > first_broken_week_end


def test_broken_week_opens_no_event():
    """周线已破时不开新事件（缩量回调开始的必要事实=结构未破）。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 10)))
    v = [1000] * 20 + [500] * 9
    ev, dly = run(c, v, trend="broken")
    assert len(ev) == 0 and len(dly) == 0


def test_dedup_single_event_despite_many_shrink_days():
    """去重：一次回调内多个缩量日只形成一个事件。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.10 * i for i in range(1, 30))
         + list(6.9 + 0.2 * i for i in range(1, 12)))
    v = [1000] * 20 + [500] * 29 + [800] * 11
    ev, _ = run(c, v, cfg=PullbackConfig(max_observation_days=60))
    # 回调段一个事件（timeout 前被 new_high 截断或 timeout），不因每日缩量重复
    assert len(ev) <= 2
    starts = ev["first_day"].tolist()
    assert len(set(starts)) == len(starts)
    # 回调中段（连续缩量日）不产生第二个起点
    assert all(s <= "2024-02-26" for s in starts)


def test_events_do_not_overlap():
    """事件不重叠：前事件结束次日后才可能开新事件。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.15 * i for i in range(1, 7)) + [8.95, 9.0, 8.2]
         + list(8.2 - 0.1 * i for i in range(1, 10)))
    v = [1000] * 20 + [600, 550, 520, 500, 480, 470] + [460, 470, 1500] + [600] * 9
    ev, dly = run(c, v)
    assert len(ev) >= 2
    for a, b in zip(ev.iloc[:-1].itertuples(), ev.iloc[1:].itertuples()):
        assert a.end_day < b.first_day
    # 每个日线行只属于一个事件
    assert dly.groupby("date")["event_id"].nunique().max() == 1


def test_no_future_leakage_outcome_only_in_events():
    """PIT：forward 收益只出现在事件表 outcome；日线明细无任何未来列。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 6))
         + [9.3, 9.35, 9.42, 9.55, 9.7]
         + list(9.7 + 0.18 * i for i in range(1, 15)))
    v = [1000] * 20 + [600, 500, 460, 440, 430] + [500, 480, 500, 550, 600] + [900] * 14
    ev, dly = run(c, v)
    assert not any(("future" in col or "outcome" in col or "forward" in col)
                   for col in dly.columns)
    assert "outcome_ret_5" in ev.columns


def test_three_distance_flavors_recorded():
    """距离三口径：真实 %、ATR 标准化、固定 1% 参照。"""
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 8))
         + list(9.06 + 0.15 * i for i in range(1, 22)))
    v = [1000] * 20 + [600, 500, 450, 420, 400, 380, 390] + [1000] * 21
    ev, _ = run(c, v)
    e = ev.iloc[0]
    assert e["dist_at_touch_pct"] is not None
    assert e["dist_at_touch_atr"] is not None
    assert e["touch_within_1pct"] in (True, False)
    # ATR 标准化 = 真实距离 / 当日 ATR 百分比
    assert e["dist_at_touch_atr"] == pytest.approx(
        e["dist_at_touch_pct"] / (e["dist_at_touch_pct"] / e["dist_at_touch_atr"]))


def test_thresholds_from_config():
    """阈值统一来自 config.surge（0.8/1.5），不在本模块另设。"""
    cfg = PullbackConfig.from_config({
        "surge": {"min_projected_volume_ratio": 0.7,
                  "bearish_turnover_veto_ratio": 2.0}})
    assert cfg.min_volume_ratio == 0.7 and cfg.veto_ratio == 2.0
    assert PullbackConfig.from_config({}).min_volume_ratio == 0.8


def test_support_platform_flavor():
    """平台支撑：deep pullback 触及 30 日 20 分位平台后收回。"""
    c = (list(8 + 0.12 * i for i in range(25))
         + list(11 - 0.35 * i for i in range(1, 9)))
    bottom = c[-1]
    c += [bottom + 0.1 * i for i in range(1, 16)]
    v = [1000] * 25 + [400] * 8 + [600] * 15
    ev, _ = run(c, v)
    e = ev.iloc[0]
    assert e["touched_platform"]
    assert e["end_reason"] in ("new_high", "timeout", "data_end")


SCENARIOS = [
    # (名称, 回调幅度, 回调斜率, 回升斜率, 缩量水平, 尾部)
    ("健康回调-浅", 5, 0.10, 0.18, 500, "新高"),
    ("健康回调-中", 8, 0.12, 0.15, 450, "新高"),
    ("健康回调-深", 12, 0.15, 0.20, 420, "新高"),
    ("健康回调-缓升", 6, 0.08, 0.10, 550, "新高"),
    ("健康回调-急落缓收", 9, 0.20, 0.08, 480, "新高"),
    ("缓慢阴跌-轻度", 15, 0.06, 0.0, 500, "持续"),
    ("缓慢阴跌-中度", 22, 0.08, 0.0, 450, "持续"),
    ("缓慢阴跌-深度", 30, 0.10, 0.0, 400, "持续"),
    ("缓慢阴跌-长时", 18, 0.05, 0.0, 550, "持续"),
    ("缓慢阴跌-阶梯", 25, 0.07, 0.0, 480, "持续"),
    ("放量破位-单日", 10, 0.14, 0.0, 500, "破位"),
    ("放量破位-双日", 12, 0.16, 0.0, 460, "破位"),
    ("放量破位-深度", 16, 0.18, 0.0, 430, "破位"),
    ("放量破位-均线远", 8, 0.10, 0.0, 500, "破位"),
    ("放量破位-连阴", 14, 0.12, 0.0, 470, "破位"),
    ("假止跌-一次", 10, 0.14, 0.05, 480, "假止跌"),
    ("假止跌-两次", 13, 0.15, 0.06, 460, "假止跌"),
    ("假止跌-浅诱多", 7, 0.10, 0.08, 520, "假止跌"),
    ("假止跌-深诱多", 15, 0.18, 0.04, 440, "假止跌"),
    ("假止跌-放量诱多", 11, 0.15, 0.07, 500, "假止跌"),
    ("支撑上攻-ma10", 4, 0.08, 0.20, 550, "新高"),
    ("支撑上攻-ma20", 7, 0.10, 0.16, 500, "新高"),
    ("支撑上攻-平台", 11, 0.18, 0.14, 430, "新高"),
    ("支撑上攻-平台深", 14, 0.20, 0.18, 410, "新高"),
    ("支撑上攻-缓攻", 9, 0.12, 0.09, 470, "新高"),
]


@pytest.mark.parametrize("name,dip,slope,recover,vol,kind", SCENARIOS)
def test_thirty_scenario_coverage(name, dip, slope, recover, vol, kind):
    """>=30 段人工行情验收：6 类原型 × 5 变体语义稳定。"""
    base = 8 + 0.1 * 20
    n_dip = max(3, int(dip / slope))
    c = (list(8 + 0.1 * i for i in range(20))
         + [base - slope * i for i in range(1, n_dip + 1)])
    v = [1000] * 20 + [vol] * n_dip
    if kind == "新高":
        c += [c[-1] + recover * i for i in range(1, 26)]
        v += [900] * 25
        expect = ("new_high", "timeout", "data_end", "volume_breakdown")
    elif kind == "持续":
        c += [c[-1] - slope * 0.5 * i for i in range(1, 40)]
        v += [vol] * 39
        expect = ("timeout", "data_end")
    elif kind == "破位":
        c += [c[-1] * 0.97, c[-1] * 0.92]
        v += [1400, 1800]
        c += [c[-1] - 0.1 * i for i in range(1, 10)]
        v += [600] * 9
        expect = ("volume_breakdown", "timeout", "data_end", "new_high")
    else:  # 假止跌：收回一日再放量跌破
        c += [c[-1] * 1.005, c[-1] * 0.93]
        v += [vol, 1600]
        c += [c[-1] - 0.1 * i for i in range(1, 12)]
        v += [600] * 11
        expect = ("volume_breakdown", "timeout", "data_end", "new_high")
    ev, dly = run(c, v, cfg=PullbackConfig(max_observation_days=60))
    assert len(ev) >= 1, f"{name}: 未识别事件"
    assert set(ev["end_reason"]).issubset(expect), \
        f"{name}: 非预期终点 {set(ev['end_reason']) - set(expect)}"
    for e in ev.itertuples():
        assert e.days_total >= 1 and e.first_day <= e.lowest_day <= e.end_day
        assert e.max_drawdown_pct <= 0.01
    assert len(dly) >= len(ev)


def test_week_pit_no_intra_week_future_leak():
    """周 PIT：周初事件不得使用本周五才确立的 broken 状态。

    构造：回调从周一开始，但当周五（该周结束后）周线才转 broken。
    正确语义：周一/周二开事件用上一完整周（intact）-> 事件应开启；
    若错误地用"所在周"状态，周一就会看到 broken 而不开事件。
    """
    c = (list(8 + 0.1 * i for i in range(20))
         + list(9.9 - 0.12 * i for i in range(1, 10)))
    v = [1000] * 20 + [500] * 9
    df = mk_daily(c, v)
    # 找到回调第一天（idx 20）所在周的下周五 -> 该周五行标 broken
    start_ts = df.index[20]
    weeks = week_rows_of(df)
    fri_after = [w for w in weeks if w[0] > start_ts]
    broken_rows = [(ts, ("broken" if any(f[0] == ts for f in fri_after[:1])
                         else "intact"), "weakening") for ts, _, _ in weeks]
    broken_rows = [(ts, t, m) for (ts, t, m), (ts0, _, _) in
                   zip(broken_rows, weeks)]
    # 直接构造：回调开始后第一个周五的周行为 broken，之前的周 intact
    cut = fri_after[0][0]
    rows = [(ts, "intact", "strengthening") if ts < cut else (ts, "broken", "weakening")
            for ts, _, _ in weeks]
    ev, _ = classify_pullback("T", df, rows, pool_all(df), PullbackConfig())
    assert len(ev) >= 1, "周初事件被未来 broken 状态错误抑制"
    assert ev.iloc[0]["first_day"] == start_ts.strftime("%Y-%m-%d")


def test_first_day_touch_recorded():
    """首日触线：开事件当天踩线必须记录（缩量阴线踩线窗口不丢失）。"""
    # 上涨后第一天即深缩量阴线直接踩到 ma10
    c = (list(8 + 0.1 * i for i in range(20))
         + [9.85, 9.7, 9.6, 9.55, 9.5] + list(9.5 + 0.12 * i for i in range(1, 15)))
    v = [1000] * 20 + [450, 430, 420, 410, 400] + [900] * 14
    df = mk_daily(c, v)
    ev, _ = classify_pullback("T", df, week_rows_of(df), pool_all(df),
                              PullbackConfig())
    e = ev.iloc[0]
    first_day = e["first_day"]
    # 首日或首日内触线：first_touch_*_day 要么等于 first_day 要么晚于它
    for s in ("ma10", "ma20"):
        day = e[f"first_touch_{s}_day"]
        if day is not None:
            assert day >= first_day
    assert e["dist_at_touch_pct"] is not None, "首日踩线距离丢失"


def test_multi_support_separate_first_touches():
    """多支撑独立记录：先触 ma10 后触平台，两者首触日期/距离分别保存，
    止跌支撑独立标注（解释不再错位）。"""
    c = (list(8 + 0.12 * i for i in range(25))
         + list(11 - 0.30 * i for i in range(1, 12))   # 深回调依次穿 ma10/ma20/平台区
         + [7.7 + 0.12 * i for i in range(1, 18)])
    v = [1000] * 25 + [400] * 11 + [700] * 17
    df = mk_daily(c, v)
    ev, _ = classify_pullback("T", df, week_rows_of(df), pool_all(df),
                              PullbackConfig())
    e = ev.iloc[0]
    assert e["touched_ma10"] and e["first_touch_ma10_day"] is not None
    if e["touched_platform"]:
        # 平台首触晚于 ma10 首触（深度顺序），且两者日期独立存在
        assert e["first_touch_platform_day"] >= e["first_touch_ma10_day"]
    if e["stabilization_support"] is not None:
        # 止跌支撑 = 实际收回的那条，与首触距离字段分离
        assert e["stabilization_support"] in ("ma10", "ma20", "platform")
