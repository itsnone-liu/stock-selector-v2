"""第四批 lifecycle 人工行情测试（对应冻结契约 B1/B2）。"""
from __future__ import annotations

import pandas as pd
import pytest

from stock_selector.research.lifecycle import (
    LIFECYCLE_COLUMNS, LifecycleConfig, RULE_VERSION,
    classify_lifecycle, stable_event_id,
)


def mk_daily(closes, vols, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": [c * 1.01 for c in closes],
         "low": [c * 0.99 for c in closes], "close": closes,
         "volume": vols}, index=idx)


def week_rows_of(df, trend="intact", mom="strengthening"):
    return [(ts, trend, mom) for ts in df.index]


def pool_all(df):
    return {ts.strftime("%Y-%m-%d"): "in" for ts in df.index}


def pool_out_from(df, date):
    return {ts.strftime("%Y-%m-%d"):
            ("out" if ts >= pd.Timestamp(date) else "in")
            for ts in df.index}


def pool_gap(df, start, n):
    out = {}
    for i, ts in enumerate(df.index):
        d = ts.strftime("%Y-%m-%d")
        if pd.Timestamp(start) <= ts < pd.Timestamp(start) + pd.tseries.offsets.BDay(n):
            out[d] = None
        else:
            out[d] = "in"
    return out


def run(closes, vols, week=None, pool=None, pb=None, cfg=None, **kw):
    df = mk_daily(closes, vols, **kw)
    return classify_lifecycle(
        "000001", df, week if week is not None else week_rows_of(df),
        pool if pool is not None else pool_all(df),
        pb or [], cfg or LifecycleConfig())


def test_linear_breakout_one_lifecycle_monthly_exit():
    c = [8.0] * 25 + [8.5 + 0.05 * i for i in range(29)]
    v = [1000] * 25 + [900] * 29
    lc = run(c, v, pool=pool_out_from(mk_daily(c, v), mk_daily(c, v).index[-3]))
    assert len(lc) == 1
    row = lc.iloc[0]
    assert "preparation" in row["stage_sequence"]
    assert "breakout" in row["stage_sequence"]
    assert row["confirmation_day"] is not None
    assert row["first_pullback_day"] is None
    assert row["end_reason"] == "monthly_exit"
    assert bool(row["end_monthly_exit"]) is True
    assert bool(row["right_censored"]) is False


def test_preparation_skipped_and_pullback_skipped():
    # warmup 期就完成拉升，regime 激活首日已高于前 20 日高 -> 直接 breakout
    c = list(9 + 0.02 * i for i in range(20)) + [9.6, 9.7, 9.75, 9.8, 9.85, 10.0]
    v = [1000] * 20 + [800] * 6
    lc = run(c, v)
    assert len(lc) == 1
    row = lc.iloc[0]
    assert row["stage_sequence"].startswith("breakout")
    assert row["preparation_start"] is None
    assert row["first_pullback_day"] is None


def test_pullback_reattack_cycles_repeatable():
    # 上升 -> 回调(由 pb 事件注入) -> 再创新高 -> 再回调 -> 再创新高
    base = list(8 + 0.05 * i for i in range(25))
    up1 = [9.3 + 0.06 * i for i in range(1, 6)]        # 突破后上行
    dn1 = [9.6 - 0.1 * i for i in range(1, 5)]         # 回调
    up2 = [9.3 + 0.08 * i for i in range(1, 7)]        # 再上攻（新高）
    dn2 = [9.78 - 0.09 * i for i in range(1, 4)]       # 再回调
    up3 = [9.6 + 0.07 * i for i in range(1, 5)]        # 又新高
    c = base + up1 + dn1 + up2 + dn2 + up3
    v = [1000] * len(c)
    df = mk_daily(c, v)
    pb = [
        {"event_id": "E1", "first_day": df.index[len(base) + len(up1)].strftime("%Y-%m-%d"),
         "end_day": df.index[len(base) + len(up1) + len(dn1) - 1].strftime("%Y-%m-%d")},
        {"event_id": "E2", "first_day": df.index[len(base) + len(up1) + len(dn1) + len(up2)].strftime("%Y-%m-%d"),
         "end_day": df.index[-1].strftime("%Y-%m-%d")},
    ]
    lc = classify_lifecycle("000001", df, week_rows_of(df), pool_all(df), pb,
                            LifecycleConfig())
    assert len(lc) == 1
    row = lc.iloc[0]
    assert row["n_pullback_reattack_cycles"] >= 2
    seq = row["stage_sequence"]
    assert seq.count("pullback") >= 2
    assert seq.count("reattack") >= 2
    assert row["pullback_event_ids"] == "E1|E2"
    # reattack 与回调事件一一对应（§2：每次独立回调至多一次并记编号）
    rids = row["reattack_pullback_event_ids"].split("|")
    assert len(rids) == row["n_pullback_reattack_cycles"]
    assert set(rids) <= {"E1", "E2"}


def test_structure_break_end_reason():
    c = list(8 + 0.05 * i for i in range(40))
    v = [1000] * 40
    df = mk_daily(c, v)
    rows = [(ts, "intact" if ts < df.index[30] else "broken", "strengthening")
            for ts in df.index]
    lc = classify_lifecycle("000001", df, rows, pool_all(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    row = lc.iloc[0]
    assert row["end_reason"] == "structure_break"
    assert bool(row["end_structure_break"]) is True


def test_data_end_right_censored_not_failure():
    c = list(8 + 0.05 * i for i in range(40))
    v = [1000] * 40
    lc = run(c, v)
    assert len(lc) == 1
    row = lc.iloc[0]
    assert row["end_reason"] == "data_end"
    assert bool(row["end_data_end"]) is True
    assert bool(row["right_censored"]) is True


def test_max_observation_ends_long_lifecycle():
    c = list(8 + 0.02 * i for i in range(200))
    v = [1000] * 200
    lc = run(c, v, cfg=LifecycleConfig(max_observation_days=60))
    assert len(lc) >= 1
    assert lc.iloc[-1]["end_reason"] in ("max_observation", "data_end")
    closed = lc[lc["end_reason"] == "max_observation"]
    assert len(closed) >= 1
    # session_count 含 anchor：恰好在第 60 个交易日内结束（非 61）
    assert closed.iloc[0]["days_total"] + 1 <= 60


def test_pool_gap_tristate_tolerance():
    c = list(8 + 0.03 * i for i in range(60))
    v = [1000] * 60
    df = mk_daily(c, v)
    # 3 日缺口（<= tolerance）-> 生命周期继续
    lc = classify_lifecycle("000001", df, week_rows_of(df),
                            pool_gap(df, df.index[30], 3), [],
                            LifecycleConfig())
    assert len(lc) == 1
    # 8 日缺口（> tolerance=5）-> pool_gap 终止
    lc2 = classify_lifecycle("000001", df, week_rows_of(df),
                             pool_gap(df, df.index[30], 8), [],
                             LifecycleConfig())
    assert lc2.iloc[0]["end_reason"] == "pool_gap"


def test_determinism_and_one_row_per_lifecycle():
    c = list(8 + 0.04 * i for i in range(50))
    v = [1000] * 50
    a, b = run(c, v), run(c, v)
    pd.testing.assert_frame_equal(a, b)
    assert list(a.columns) == LIFECYCLE_COLUMNS
    assert a.iloc[0]["lifecycle_id"] == stable_event_id(
        ["000001"], [a.iloc[0]["anchor_day"]], RULE_VERSION)[0]


def test_no_lookahead_truncate_before_breakout():
    # 横盘后突破：截断在突破发生前 -> 不得出现 breakout 阶段
    c = [8.0] * 40 + [8.5 + 0.05 * i for i in range(20)]
    v = [1000] * 60
    full = run(c, v)
    assert "breakout" in full.iloc[0]["stage_sequence"]
    trunc = run(c[:40], v[:40])
    if len(trunc):
        assert "breakout" not in trunc.iloc[0]["stage_sequence"]


def test_pool_out_then_rein_two_lifecycles():
    c = list(8 + 0.03 * i for i in range(80))
    v = [1000] * 80
    df = mk_daily(c, v)
    pool = {}
    for i, ts in enumerate(df.index):
        d = ts.strftime("%Y-%m-%d")
        pool[d] = "out" if 35 <= i < 50 else "in"
    lc = classify_lifecycle("000001", df, week_rows_of(df), pool, [],
                            LifecycleConfig())
    assert len(lc) == 2
    assert lc.iloc[0]["end_reason"] == "monthly_exit"
    ids = set(lc["lifecycle_id"])
    assert len(ids) == 2


def test_empty_inputs_and_short_history():
    df = mk_daily([8, 8.1], [100, 100])
    out = classify_lifecycle("000001", df, week_rows_of(df), pool_all(df),
                             [], LifecycleConfig())
    assert len(out) == 0
    assert list(out.columns) == LIFECYCLE_COLUMNS


def test_max_gain_recorded_in_percent():
    # anchor 收盘 10.0，窗口最高 11.1 -> 上涨11% 应记录约11（非0.11）
    c = [10.0] * 25 + [10.2 + 0.1 * i for i in range(10)] + [11.0] + [10.5] * 3
    v = [1000] * len(c)
    lc = run(c, v)
    assert len(lc) >= 1
    assert abs(lc.iloc[-1]["max_gain_from_anchor_pct"] - 11.0) < 0.01


def test_anchor_day_stages_not_lost():
    # 起点当天同时突破 + starting_to_damage -> 序列应含 breakout 后接 decay
    # warmup 满后首个 regime 日即跳空突破（8.6>8.0），当日周线已 starting_to_damage
    c = [8.0] * 20 + [8.6, 8.65, 8.7, 8.75, 8.8]
    v = [1000] * len(c)
    df = mk_daily(c, v)
    anchor = df.index[20]  # 当日即突破
    rows = [(ts, "starting_to_damage", "strengthening") for ts in df.index]
    lc = classify_lifecycle("000001", df, rows, pool_all(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    seq = lc.iloc[0]["stage_sequence"]
    assert seq.startswith("breakout|decay"), seq  # 同日并存：突破当日即记衰减
    assert lc.iloc[0]["decay_day"] == anchor.strftime("%Y-%m-%d")
    assert lc.iloc[0]["breakout_day"] == anchor.strftime("%Y-%m-%d")


def test_120_session_count_exact():
    c = [8.0] * 150  # 长横盘：一直 preparation 直到 max_observation
    v = [1000] * 150
    lc = run(c, v, cfg=LifecycleConfig(max_observation_days=120))
    mo = lc[lc["end_reason"] == "max_observation"]
    assert len(mo) == 1
    # 恰好第 120 个交易日结束：days_total（不含 anchor）+1 == 120
    assert mo.iloc[0]["days_total"] + 1 == 120


def test_same_day_termination_priority():
    # 同日 pool out + trend broken -> 只记 monthly_exit（优先级更高）
    c = [8.0] * 60
    v = [1000] * 60
    df = mk_daily(c, v)
    rows = [(ts, "intact" if ts < df.index[40] else "broken", "strengthening")
            for ts in df.index]
    pool = {ts.strftime("%Y-%m-%d"):
            ("out" if ts >= df.index[40] else "in") for ts in df.index}
    lc = classify_lifecycle("000001", df, rows, pool, [], LifecycleConfig())
    assert lc.iloc[0]["end_reason"] == "monthly_exit"
    assert bool(lc.iloc[0]["end_monthly_exit"]) is True
    assert bool(lc.iloc[0]["end_structure_break"]) is False


def test_adjacent_lifecycles_never_overlap():
    # 反复 out/in：任意相邻两段 next anchor_day > prev end_day
    c = [8.0] * 120
    v = [1000] * 120
    df = mk_daily(c, v)
    pool = {ts.strftime("%Y-%m-%d"):
            ("out" if 30 <= i < 40 or 60 <= i < 70 else "in")
            for i, ts in enumerate(df.index)}
    lc = classify_lifecycle("000001", df, week_rows_of(df), pool, [],
                            LifecycleConfig())
    assert len(lc) >= 2
    prev_end = None
    for row in lc.itertuples(index=False):
        if prev_end is not None:
            assert pd.Timestamp(row.anchor_day) > pd.Timestamp(prev_end)
        prev_end = row.end_day


def test_truncating_future_keeps_past_stages():
    # 截断未来数据：截断日前的阶段序列不得改变
    c = [8.0] * 25 + [8.6 + 0.05 * i for i in range(20)] + [9.6] * 30
    v = [1000] * len(c)
    full = run(c, v)
    cut = 50
    trunc = run(c[:cut], v[:cut])
    f = full.iloc[0]["stage_sequence"]
    t = trunc.iloc[0]["stage_sequence"]
    assert t.replace("|end", "") == f[:len(t.replace("|end", ""))]
    assert trunc.iloc[0]["anchor_day"] == full.iloc[0]["anchor_day"]
