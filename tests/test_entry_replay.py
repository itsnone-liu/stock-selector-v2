"""第四批 entry_replay 人工行情测试（v2：七项修复后）。"""
from __future__ import annotations

import pandas as pd
import pytest

from stock_selector.decision.execution import CostModel
from stock_selector.research.entry_replay import (
    ENTRY_REPLAY_COLUMNS, RETURN_QUALITY, ReplayConfig, replay_entries,
)
from stock_selector.research.lifecycle import (
    LifecycleConfig, classify_lifecycle,
)


def mk_daily(closes, opens, vols, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": opens, "high": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
         "low": [min(o, c) * 0.99 for o, c in zip(opens, closes)],
         "close": closes, "volume": vols}, index=idx)


def mk_week(df):
    return [(ts, "intact", "strengthening") for ts in df.index]


def mk_pool(df):
    return {ts.strftime("%Y-%m-%d"): "in" for ts in df.index}


def build_market(closes=None, vols=None):
    if closes is None:
        closes = [8.0] * 25 + [8.6 + 0.04 * i for i in range(6)] \
            + [8.84 - 0.08 * i for i in range(1, 5)] \
            + [8.5, 8.55, 8.62, 8.75] + [8.9 + 0.06 * i for i in range(12)]
    if vols is None:
        vols = [1000] * 25 + [1200] * 6 + [600, 500, 450, 420] \
            + [500, 520, 550, 600] + [900] * 12
    opens = [c * 0.998 for c in closes]
    df = mk_daily(closes, opens, vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    i0 = 31
    pb = [{"event_id": "PB1",
           "first_day": df.index[i0].strftime("%Y-%m-%d"),
           "end_day": df.index[i0 + 6].strftime("%Y-%m-%d"),
           "stabilization_day": df.index[i0 + 4].strftime("%Y-%m-%d")}]
    pdly = pd.DataFrame({
        "event_id": ["PB1"] * 7,
        "date": [df.index[i0 + k].strftime("%Y-%m-%d") for k in range(7)],
        "shrink_volume": [True, True, True, True, False, False, False]})
    return df, lc, pb, pdly


def run_replay(code="000001", market_cal=None, **kw):
    df, lc, pb, pdly = build_market()
    return replay_entries(code, lc, df, pb, pdly,
                          kw.pop("cfg", None) or ReplayConfig(),
                          kw.pop("cost", None) or CostModel(),
                          market_cal=market_cal)


def _bo(df, lc):
    return [i for i, ts in enumerate(df.index)
            if ts.strftime("%Y-%m-%d") == lc.iloc[0]["breakout_day"]][0]


# ---------------- 原有关键断言（列名同步） ----------------

def test_four_strategies_same_population():
    ev = run_replay()
    assert len(ev) == 4
    assert set(ev["strategy"]) == {"direct_chase", "wait_first_pullback",
                                   "wait_support_hold", "staged_entry"}
    assert list(ev.columns) == ENTRY_REPLAY_COLUMNS
    assert (ev["return_quality"] == RETURN_QUALITY).all()


def test_direct_dual_view_prices_differ():
    ev = run_replay()
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["fill_status_close"] == "filled"
    assert d["fill_status_next"] == "filled"
    assert d["fill_price_next"] != d["fill_price_close"]
    assert d["not_filled_reason_close"] is None


def test_chase_cap_variant_on_same_row():
    df, lc, pb, pdly = build_market()
    g = (df.iloc[_bo(df, lc)]["close"]
         / df.iloc[_bo(df, lc) - 1]["close"] - 1) * 100
    ev = replay_entries("000001", lc, df, pb, pdly,
                        ReplayConfig(chase_gain_cap_pct=g - 1.0), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["capped_entered"] is False
    assert d["capped_not_entered_reason"] == "chase_gain_cap_exceeded"
    assert d["fill_status_close"] == "filled"


def test_next_session_limit_up_blocked():
    df, lc, pb, pdly = build_market()
    bo = _bo(df, lc)
    prev = df.iloc[bo]["close"]
    for f in ("open", "high", "low"):
        df.iloc[bo + 1, df.columns.get_loc(f)] = round(prev * 1.10, 2)
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["fill_status_next"] == "not_filled"
    assert d["not_filled_reason_next"] == "open_limit_up_buy_blocked"
    assert d["not_filled_reason_close"] is None  # 两视角原因分列不覆盖


def test_wait_pullback_fills_on_first_shrink_day():
    ev = run_replay()
    w = ev[ev["strategy"] == "wait_first_pullback"].iloc[0]
    df, lc, pb, pdly = build_market()
    assert w["fill_status_close"] == "filled"
    assert w["fill_date_close"] == pb[0]["first_day"]
    bo = _bo(df, lc)
    exp = (w["fill_price_close"] / df.iloc[bo]["close"] - 1) * 100
    assert abs(w["fill_price_vs_breakout_pct"] - exp) < 1e-9


def test_wait_not_filled_reasons():
    df, lc, _, _ = build_market()
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    for strat in ("wait_first_pullback", "wait_support_hold"):
        r = ev[ev["strategy"] == strat].iloc[0]
        assert r["not_filled_reason_close"] == "no_pullback_before_end"
        assert r["not_filled_reason_next"] == "no_pullback_before_end"
        assert r["missed_upside_pct"] is not None


# ---------------- 修复 1：回调限定本生命周期内 ----------------

def test_pullback_after_lifecycle_end_not_fillable():
    df, lc, pb, pdly = build_market()
    late = "2024-03-20"  # 严格晚于 end_day，且不在个股行情内
    pb2 = [dict(pb[0], first_day=late, end_day=late,
                stabilization_day=late)]
    pdly2 = pd.DataFrame({"event_id": ["PB1"],
                          "date": [late], "shrink_volume": [True]})
    ev = replay_entries("000001", lc, df, pb2, pdly2, ReplayConfig(), CostModel())
    assert lc.iloc[0]["end_day"] < late
    for strat in ("wait_first_pullback", "wait_support_hold"):
        r = ev[ev["strategy"] == strat].iloc[0]
        assert r["fill_status_close"] == "not_filled"
        assert r["not_filled_reason_close"] == "no_pullback_before_end"


def test_earliest_pullback_event_chosen():
    df, lc, pb, pdly = build_market()
    pb2 = pb + [dict(pb[0], event_id="PB0", first_day="1970-01-01",
                      end_day="1970-01-02", stabilization_day=None)]
    ev = replay_entries("000001", lc, df, pb2, pdly, ReplayConfig(), CostModel())
    w = ev[ev["strategy"] == "wait_first_pullback"].iloc[0]
    assert w["fill_date_close"] == pb[0]["first_day"]  # 排序后取最早


# ---------------- 修复 2：双视角独立收益起点 ----------------

def test_next_view_return_starts_one_day_later():
    # 单边上涨：next 视角收益起点=次日开盘，与 close 视角差一天
    closes = [8.0] * 25 + [8.6 * 1.02 ** i for i in range(30)]
    vols = [1000] * 25 + [1100] * 30
    df, lc, _, _ = build_market(closes, vols)
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    bo = _bo(df, lc)
    assert d["ret_gross_20_close"] == pytest.approx(
        (df.iloc[bo + 20]["close"] / df.iloc[bo]["close"] - 1) * 100)
    # next 视角毛收益：买=次日开盘、卖=起点后第20日收盘（精确市场价口径）
    assert d["ret_gross_20_next"] == pytest.approx(
        (df.iloc[bo + 21]["close"] / df.iloc[bo + 1]["open"] - 1) * 100,
        abs=1e-6)
    assert d["mfe_20_next"] != d["mfe_20_close"]


# ---------------- 修复 3：分批现金与窗口 ----------------

def test_staged_flat_market_only_t1_gives_zero():
    # 突破后横盘：只有 T1 成交，组合收益≈0 而非 -70%
    closes = [8.0] * 25 + [8.6] * 30
    vols = [1000] * 25 + [1100] * 30
    df, lc, _, _ = build_market(closes, vols)
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["fraction_invested"] == pytest.approx(0.30)
    assert abs(st["ret_gross_20_close"]) < 0.5  # ≈0，不是 -70%
    assert abs(st["ret_net_20_close"]) < 0.5


def test_staged_late_leg_excluded_from_5d_window():
    # T2 缩量日在第 6 日：5 日窗只含 T1+现金；20 日窗含两批
    closes = [8.0] * 25 + [8.6, 8.7, 8.75, 8.8, 8.85, 8.9, 8.86, 8.8,
                           8.78, 8.75, 8.8, 8.9] + [9.0 + 0.05 * i for i in range(20)]
    vols = [1000] * 25 + [1200] * 7 + [500, 450, 420, 500, 600] + [900] * 20
    df = mk_daily(closes, [c * 0.998 for c in closes], vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    bo = _bo(df, lc)
    t2 = bo + 6
    pb = [{"event_id": "PB1",
           "first_day": df.index[t2].strftime("%Y-%m-%d"),
           "end_day": df.index[t2 + 3].strftime("%Y-%m-%d"),
           "stabilization_day": None}]
    pdly = pd.DataFrame({"event_id": ["PB1"],
                         "date": [df.index[t2].strftime("%Y-%m-%d")],
                         "shrink_volume": [True]})
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["t2_fill_date"] == df.index[t2].strftime("%Y-%m-%d")
    assert st["fraction_invested"] == pytest.approx(0.60)
    # 5 日窗（末=bo+5）：只 T1 在窗内
    p5 = df.iloc[bo + 5]["close"]
    exp5 = (0.7 + 0.3 * p5 / df.iloc[bo]["close"] - 1) * 100
    assert st["ret_gross_5_close"] == pytest.approx(exp5, abs=0.05)
    # 20 日窗：两批都进
    p20 = df.iloc[bo + 20]["close"]
    p1, p2 = df.iloc[bo]["close"], df.iloc[t2]["close"]
    exp20 = (0.4 + 0.3 * p20 / p1 + 0.3 * p20 / p2 - 1) * 100
    assert st["ret_gross_20_close"] == pytest.approx(exp20, abs=0.05)


def test_staged_capital_days_nonnegative_and_conservation():
    ev = run_replay()
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["max_position"] <= 1.0 + 1e-9
    assert st["capital_position_days"] >= 0


# ---------------- 修复 4：市场日历下的「次日」 ----------------

def test_suspension_day_not_treated_as_next_session():
    df, lc, pb, pdly = build_market()
    bo = _bo(df, lc)
    full_cal = pd.bdate_range(df.index[0], df.index[-1])
    bo_day = df.index[bo]
    nxt_day = full_cal[full_cal.searchsorted(bo_day, side="right")]
    df2 = df.drop(index=nxt_day)  # 个股停牌：下一市场日无 bar
    lc2 = classify_lifecycle("000001", df2, mk_week(df2), mk_pool(df2), [],
                             LifecycleConfig())
    assert len(lc2) == 1
    pdly2 = pdly[pdly["date"] != nxt_day.strftime("%Y-%m-%d")]
    ev = replay_entries("000001", lc2, df2, pb, pdly2, ReplayConfig(),
                        CostModel(), market_cal=full_cal)
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["fill_status_next"] == "not_filled"
    assert d["not_filled_reason_next"] == "missing_bar_or_suspended"
    # 复牌日（下一根个股 bar）不得冒充次日成交
    assert pd.isna(d["fill_date_next"])
    assert d["fill_date_close"] == d["signal_day"]


# ---------------- 修复 5：20 日新高边界与删失 ----------------

def test_new_high_on_day_20_recognized():
    # 回调后成交（fill=缩量日 8.4），其后 19 天低于突破价，第 20 天回到 8.6
    closes = [8.0] * 25 + [8.6, 8.62, 8.58, 8.4] + [8.5] * 19 + [8.6] + [8.7] * 5
    vols = [1000] * 25 + [1200] * 2 + [400, 350] + [600] * 19 + [900] * 6
    df = mk_daily(closes, [c * 0.998 for c in closes], vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    bo = _bo(df, lc)
    t2 = bo + 3  # 缩量日=回撤第 2 天
    pb = [{"event_id": "PB1", "first_day": df.index[bo + 2].strftime("%Y-%m-%d"),
           "end_day": df.index[bo + 5].strftime("%Y-%m-%d"),
           "stabilization_day": None}]
    pdly = pd.DataFrame({"event_id": ["PB1"],
                         "date": [df.index[t2].strftime("%Y-%m-%d")],
                         "shrink_volume": [True]})
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "wait_first_pullback"].iloc[0]
    assert d["fill_status_close"] == "filled"
    assert d["fill_date_close"] == df.index[t2].strftime("%Y-%m-%d")
    assert d["outcome_20d_complete"] is True
    assert d["new_high_in_window_close"] is True
    assert d["days_to_new_high_close"] == 20  # 含第 20 日


def test_new_high_missing_when_window_incomplete():
    closes = [8.0] * 25 + [8.6, 8.62, 8.58, 8.4] + [8.5] * 19 + [8.6] + [8.7] * 5
    vols = [1000] * 25 + [1200] * 2 + [400, 350] + [600] * 19 + [900] * 6
    df = mk_daily(closes, [c * 0.998 for c in closes], vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    bo = _bo(df, lc)
    t2 = bo + 3
    pb = [{"event_id": "PB1", "first_day": df.index[bo + 2].strftime("%Y-%m-%d"),
           "end_day": df.index[bo + 5].strftime("%Y-%m-%d"),
           "stabilization_day": None}]
    pdly = pd.DataFrame({"event_id": ["PB1"],
                         "date": [df.index[t2].strftime("%Y-%m-%d")],
                         "shrink_volume": [True]})
    df2 = df.iloc[:t2 + 15]  # fill 后仅 14 日 < 20
    lc2 = classify_lifecycle("000001", df2, mk_week(df2), mk_pool(df2), [],
                             LifecycleConfig())
    assert len(lc2) == 1
    pdly2 = pdly[pdly["date"] <= df2.index[-1].strftime("%Y-%m-%d")]
    ev = replay_entries("000001", lc2, df2, pb, pdly2, ReplayConfig(),
                        CostModel())
    d = ev[ev["strategy"] == "wait_first_pullback"].iloc[0]
    assert d["fill_status_close"] == "filled"
    assert d["outcome_20d_complete"] is False
    assert d["new_high_in_window_close"] is None  # 缺失，不是 False
    assert d["outcome_5d_complete"] is True
    assert d["outcome_20d_observed"] == 14


def test_horizon_completeness_separate():
    ev = run_replay()
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["outcome_5d_observed"] <= 5
    assert d["outcome_10d_complete"] in (True, False)
    assert d["outcome_20d_complete"] in (True, False)


# ---------------- 修复 6：卖出滑点 ----------------

def test_sell_slippage_reduces_net():
    ev = run_replay()
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    df, lc, _, _ = build_market()
    bo = _bo(df, lc)
    cost = CostModel()
    buy = d["fill_price_close"]
    sell_raw = df.iloc[bo + 20]["close"]
    sell_day = df.index[bo + 20].date()
    shares = 100_000.0 / buy
    gross = shares * sell_raw
    manual = ((gross - cost.fees(gross, "sell", sell_day)["total"])
              / (100_000.0 + cost.fees(100_000.0, "buy", sell_day)["total"]) - 1) * 100
    assert d["ret_net_20_close"] == pytest.approx(manual - 0.10, abs=0.06)
    assert d["ret_net_20_close"] < manual  # 卖出滑点进一步压低


# ---------------- 修复 7：无突破输出四行 ----------------

def test_no_breakout_lifecycle_yields_four_not_filled_rows():
    # 缓跌触发 structure_break，全程无突破
    closes = [8.0] * 20 + [8.0 - 0.08 * i for i in range(1, 15)]
    vols = [1000] * 34
    df = mk_daily(closes, [c * 0.998 for c in closes], vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    assert lc.iloc[0]["breakout_day"] is None or pd.isna(lc.iloc[0]["breakout_day"])
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    assert len(ev) == 4
    for r in ev.itertuples():
        assert r.fill_status_close == "not_filled"
        assert r.not_filled_reason_close == "no_breakout_signal"
        assert r.not_filled_reason_next == "no_breakout_signal"
        assert r.ret_gross_20_close is None
        assert r.capped_entered is None


# ---------------- 回归：右删失与无未来泄漏 ----------------

def test_right_censored_tail():
    df, lc, pb, pdly = build_market()
    bo = _bo(df, lc)
    df2 = df.iloc[:bo + 8]
    lc2 = classify_lifecycle("000001", df2, mk_week(df2), mk_pool(df2), [],
                             LifecycleConfig())
    pb2 = [dict(pb[0], end_day=min(pb[0]["end_day"],
                                    df2.index[-1].strftime("%Y-%m-%d")))]
    pdly2 = pdly[pdly["date"] <= df2.index[-1].strftime("%Y-%m-%d")]
    ev = replay_entries("000001", lc2, df2, pb2, pdly2, ReplayConfig(),
                        CostModel())
    for strat in ev["strategy"]:
        r = ev[ev["strategy"] == strat].iloc[0]
        if r["fill_status_close"] == "filled":
            assert r["outcome_20d_complete"] is False
            assert r["failure_path_close"] == "right_censored"


def test_no_lookahead_outcome_only():
    df, lc, pb, pdly = build_market()
    bo = _bo(df, lc)
    ev1 = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    df3 = df.copy()
    df3.iloc[bo + 5:, df3.columns.get_loc("close")] *= 1.10
    ev2 = replay_entries("000001", lc, df3, pb, pdly, ReplayConfig(), CostModel())
    d1 = ev1[ev1["strategy"] == "direct_chase"].iloc[0]
    d2 = ev2[ev2["strategy"] == "direct_chase"].iloc[0]
    assert d1["fill_price_close"] == d2["fill_price_close"]
    assert d1["fill_date_close"] == d2["fill_date_close"]
    assert d2["ret_gross_20_close"] > d1["ret_gross_20_close"]


# ---------------- 修复轮 2：四个口径问题 + 新高边界 ----------------

def test_next_gross_uses_open_price_exactly():
    # 精确对照：次日开盘 -> 第20日收盘（市场价，不含滑点费用）
    closes = [8.0] * 25 + [8.6 * 1.02 ** i for i in range(30)]
    vols = [1000] * 25 + [1100] * 30
    df, lc, _, _ = build_market(closes, vols)
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    bo = _bo(df, lc)
    exp = (df.iloc[bo + 21]["close"] / df.iloc[bo + 1]["open"] - 1) * 100
    assert d["ret_gross_20_next"] == pytest.approx(exp, abs=1e-6)


def test_next_view_censoring_uses_own_completeness():
    # close 有 20 日、next 少一天：next=右删失，close=完整
    closes = [8.0] * 25 + [8.6 * 1.01 ** i for i in range(28)]
    vols = [1000] * 25 + [1100] * 28
    df, lc, _, _ = build_market(closes, vols)
    bo = _bo(df, lc)
    df2 = df.iloc[:bo + 21]  # last=bo+20：close 完整、next(bo+21) 不完整
    lc2 = classify_lifecycle("000001", df2, mk_week(df2), mk_pool(df2), [],
                             LifecycleConfig())
    assert len(lc2) == 1
    ev = replay_entries("000001", lc2, df2, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["fill_status_next"] == "filled"
    assert d["outcome_20d_complete"] is True      # close 视角完整
    assert d["outcome_20d_complete_next"] is False  # next 视角不完整
    assert d["failure_path_close"] in ("ok", "entry_poor")
    assert d["failure_path_next"] == "right_censored"  # 不得计失败样本


def test_staged_gross_differs_from_net():
    ev = run_replay()
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["ret_gross_20_close"] is not None
    assert st["ret_net_20_close"] is not None
    assert st["ret_net_20_close"] < st["ret_gross_20_close"]  # 费用+滑点分离
    if st["ret_gross_20_next"] is not None:
        assert st["ret_net_20_next"] < st["ret_gross_20_next"]


def test_staged_close_view_has_mfe_mae_new_high():
    # 分批 close 视角补齐：MFE/MAE/新高非空（完整窗）
    closes = [8.0] * 25 + [8.6, 8.62, 8.58, 8.4, 8.45] + [8.9 + 0.05 * i
                                                          for i in range(25)]
    vols = [1000] * 25 + [1200] * 2 + [400, 350, 500] + [900] * 25
    df = mk_daily(closes, [c * 0.998 for c in closes], vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    bo = _bo(df, lc)
    pb = [{"event_id": "PB1", "first_day": df.index[bo + 2].strftime("%Y-%m-%d"),
           "end_day": df.index[bo + 5].strftime("%Y-%m-%d"),
           "stabilization_day": None}]
    pdly = pd.DataFrame({"event_id": ["PB1"],
                         "date": [df.index[bo + 3].strftime("%Y-%m-%d")],
                         "shrink_volume": [True]})
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["outcome_20d_complete"] is True
    assert st["mfe_20_close"] is not None
    assert st["mae_20_close"] is not None
    assert st["mae_20_close"] < 0 < st["mfe_20_close"]
    assert st["new_high_in_window_close"] in (True, False)
    assert st["days_to_new_high_close"] is not None
    # 手工对照：从 T1(bo) 次日起，窗口内最高/最低相对 bo 收盘
    w = [df.iloc[j]["close"] / df.iloc[bo]["close"] - 1
         for j in range(bo, bo + 21)]
    assert st["mfe_20_close"] == pytest.approx(max(w) * 100, abs=1e-9)
    assert st["mae_20_close"] == pytest.approx(min(w) * 100, abs=1e-9)


def test_direct_new_high_starts_after_fill_day():
    # 成交日=突破日自身不算新高：其后 20 天均低于突破价 -> False（非 0 天）
    closes = [8.0] * 25 + [8.6] + [8.4 + 0.005 * i for i in range(20)] + [8.5] * 3
    vols = [1000] * 25 + [1100] * 24
    df, lc, _, _ = build_market(closes, vols)
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    bo = _bo(df, lc)
    assert all(df.iloc[bo + k]["close"] < df.iloc[bo]["close"]
               for k in range(1, 21))
    assert d["outcome_20d_complete"] is True
    assert d["new_high_in_window_close"] is False
    assert d["days_to_new_high_close"] is None
