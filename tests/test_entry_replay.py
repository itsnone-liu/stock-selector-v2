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
    # 手工对照：组合净值路径（现金+T1 0.3+T2 0.3），逐日价值相对起点面值
    t2 = bo + 3
    vals = []
    for j in range(bo, bo + 21):
        v = 1.0 + 0.3 * (df.iloc[j]["close"] / df.iloc[bo]["close"] - 1.0)
        if j >= t2:
            v += 0.3 * (df.iloc[j]["close"] / df.iloc[t2]["close"] - 1.0)
        vals.append(v)
    assert st["mfe_20_close"] == pytest.approx((max(vals) - 1) * 100, abs=1e-9)
    assert st["mae_20_close"] == pytest.approx((min(vals) - 1) * 100, abs=1e-9)


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


# ---------------- 修复轮 3：分批 next 独立性 + MFE 基准 + 净值路径 ----------------

def _mk_staged_market():
    """突破 -> 回调(缩量日 bo+3) -> 再突破前高(reattack, bo+8) -> 续涨。

    classify_lifecycle 实际产生 reattack_days（测试无条件依赖 T3 存在）。
    """
    closes = [8.0] * 25 + [8.6, 8.62, 8.58, 8.4, 8.45, 8.42, 8.46, 8.5,
                           8.68, 8.8] + [8.9 + 0.05 * i for i in range(22)]
    vols = ([1000] * 25 + [1200, 1200] + [400, 350, 420, 380, 400, 420, 450]
            + [1500, 1600] + [900] * (len(closes) - 36))
    df = mk_daily(closes, [c * 0.998 for c in closes], vols)
    # reattack 由回调事件驱动：classify 必须带事件表
    pb = [{"event_id": "PB1", "first_day": df.index[28].strftime("%Y-%m-%d"),
           "end_day": df.index[32].strftime("%Y-%m-%d"),
           "stabilization_day": None}]
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), pb,
                            LifecycleConfig())
    assert len(lc) == 1
    assert lc.iloc[0]["reattack_days"], "测试构造必须产生 reattack（T3 存在）"
    bo = _bo(df, lc)
    assert bo == 25  # 数据契约：突破日=closes[25]
    pdly = pd.DataFrame({"event_id": ["PB1"],
                         "date": [df.index[28].strftime("%Y-%m-%d")],
                         "shrink_volume": [True]})
    return df, lc, pb, pdly, bo


def _limit_up(df, pos):
    prev = df.iloc[pos - 1]["close"]
    for f in ("open", "high", "low", "close"):
        df.iloc[pos, df.columns.get_loc(f)] = round(prev * 1.10, 2)


def test_staged_t1_next_blocked_t2_fills():
    # 第一批次日涨停不可成交：观察起点应为第二批的次日成交日
    df, lc, pb, pdly, bo = _mk_staged_market()
    _limit_up(df, bo + 1)  # T1 的次日一字板
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    t2 = bo + 3
    assert st["fill_status_next"] == "filled"
    # 起点 = T2 的次日（t2+1）
    assert st["fill_date_next"] == df.index[t2 + 1].strftime("%Y-%m-%d")
    assert st["t1_next_status"] == "not_filled"
    assert st["t1_next_reason"] == "open_limit_up_buy_blocked"
    assert st["t2_next_status"] == "filled"
    # next 视角实际仓位：T1 阻断 + T2/T3 成交 = 0.70（非收盘理论的 1.00）
    assert st["fraction_invested_next"] == pytest.approx(0.70)
    assert st["max_position_next"] == pytest.approx(0.70)
    assert st["avg_cost_next"] is not None
    assert st["ret_gross_20_next"] is not None
    # 手工：T1 阻断 -> 现金 0.3；T2/T3 在窗内（含 reattack 批）
    t3 = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d")
          == lc.iloc[0]["reattack_days"].split("|")[0]][0]
    wend = t2 + 1 + 20
    exp = (0.3 + 0.3 * df.iloc[wend]["close"] / df.iloc[t2 + 1]["open"]
           + 0.4 * df.iloc[wend]["close"] / df.iloc[t3 + 1]["open"] - 1) * 100
    assert st["ret_gross_20_next"] == pytest.approx(exp, abs=1e-6)


def test_staged_t1_t2_next_blocked_t3_fills():
    # T1 次日涨停 + 无回调成交但 T2 也被阻断（构造 T2 次日同样涨停）
    df, lc, pb, pdly, bo = _mk_staged_market()
    _limit_up(df, bo + 1)   # T1 次日涨停
    _limit_up(df, bo + 4)   # T2(bo+3) 的次日涨停
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    t3 = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d")
          == lc.iloc[0]["reattack_days"].split("|")[0]][0]
    assert st["fill_status_next"] == "filled"
    assert st["fill_date_next"] == df.index[t3 + 1].strftime("%Y-%m-%d")
    assert st["ret_gross_20_next"] is not None
    # 只有 T3 成交：next 实际仓位 40%（收盘理论 100%）
    assert st["fraction_invested_next"] == pytest.approx(0.40)
    assert st["max_position_next"] == pytest.approx(0.40)
    assert st["t1_next_status"] == "not_filled"
    assert st["t2_next_status"] == "not_filled"
    assert st["t3_next_status"] == "filled"


def test_staged_all_legs_next_blocked():
    # 三批次日全部一字板：未成交，原因分列，next 仓位 0
    df, lc, pb, pdly, bo = _mk_staged_market()
    t3 = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d")
          == lc.iloc[0]["reattack_days"].split("|")[0]][0]
    _limit_up(df, bo + 1)   # T1 次日
    _limit_up(df, bo + 4)   # T2 次日
    _limit_up(df, t3 + 1)   # T3 次日
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["fill_status_next"] == "not_filled"
    assert st["not_filled_reason_next"] == "open_limit_up_buy_blocked"
    assert st["ret_gross_20_next"] is None
    assert st["mfe_20_next"] is None
    assert st["fraction_invested_next"] == pytest.approx(0.0)
    assert st["t1_next_status"] == "not_filled"
    assert st["t2_next_status"] == "not_filled"
    assert st["t3_next_status"] == "not_filled"


def test_next_view_mfe_mae_use_open_basis():
    # 次日开盘基准的 MFE/MAE（先跌后涨构造不对称极值）
    closes = [8.0] * 25 + [8.6, 8.5, 8.45, 8.5] + [8.6 * 1.02 ** i
                                                   for i in range(26)]
    vols = [1000] * 25 + [1100] * 30
    df, lc, _, _ = build_market(closes, vols)
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    bo = _bo(df, lc)
    o = df.iloc[bo + 1]["open"]
    rets = [df.iloc[j]["close"] / o - 1
            for j in range(bo + 1, bo + 1 + 21)]
    assert d["mfe_20_next"] == pytest.approx(max(rets) * 100, abs=1e-9)
    assert d["mae_20_next"] == pytest.approx(min(rets) * 100, abs=1e-9)
    # 与 close 收盘基准不同（基准不同 -> 数值不同）
    assert d["mfe_20_next"] != d["mfe_20_close"]


def test_staged_nav_path_next_extremes():
    # 分批 next 视角净值路径极值：手工逐日对照
    df, lc, pb, pdly, bo = _mk_staged_market()
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    t1n = bo + 1  # 无阻断：组合窗口起点 = T1 的次日
    t2n = bo + 4
    t3 = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d")
          == lc.iloc[0]["reattack_days"].split("|")[0]][0]
    t3n = t3 + 1
    vals = []
    for j in range(t1n, t1n + 21):
        v = 1.0 + 0.3 * (df.iloc[j]["close"] / df.iloc[t1n]["open"] - 1.0)
        if j >= t2n:
            v += 0.3 * (df.iloc[j]["close"] / df.iloc[t2n]["open"] - 1.0)
        if j >= t3n:
            v += 0.4 * (df.iloc[j]["close"] / df.iloc[t3n]["open"] - 1.0)
        vals.append(v)
    assert st["mfe_20_next"] == pytest.approx((max(vals) - 1) * 100, abs=1e-9)
    assert st["mae_20_next"] == pytest.approx((min(vals) - 1) * 100, abs=1e-9)


def test_avg_cost_harmonic_formula():
    # 平均成本 = Σw / Σ(w/P)（价格含买入滑点），非算术加权
    ev = run_replay()
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    legs = [(st["t1_fill_price"], 0.30)]
    if st["t2_fill_price"]:
        legs.append((st["t2_fill_price"], 0.30))
    if st["t3_fill_price"]:
        legs.append((st["t3_fill_price"], 0.40))
    tw = sum(w for _, w in legs)
    exp = tw / sum(w / px for px, w in legs)
    assert st["avg_cost"] == pytest.approx(exp, rel=1e-12)
    # 算术加权应不同（除非各批价格相等）
    arith = sum(px * w for px, w in legs) / tw
    if len({round(px, 6) for px, _ in legs}) > 1:
        assert st["avg_cost"] != pytest.approx(arith, rel=1e-9)


def test_next_view_aggregates_reflect_actual_fills():
    # 收盘理论仓位 vs 次日实际仓位分列（T1/T2 阻断只 T3：40% vs 100%）
    df, lc, pb, pdly, bo = _mk_staged_market()
    _limit_up(df, bo + 1)
    _limit_up(df, bo + 4)
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["max_position"] == pytest.approx(1.00)      # 收盘理论：三批
    assert st["fraction_invested_next"] == pytest.approx(0.40)  # 次日实际
    assert st["capital_position_days_next"] is not None
    assert st["capital_position_days_next"] >= 0
    assert st["avg_cost_next"] is not None


# ---------------- 修复轮 4：T3 必须配对 T2 的回调事件 ----------------

def _mk_manual_lifecycle(df, breakout_i, reattack_pairs, t2_event,
                          t2_first_i, t2_end_i, t2_shrink_i):
    """手工 lifecycle 记录（真实数据中存在的形态：reattack_days 第一位
    属于突破前回调，配对 ids 由上游表提供）。"""
    D = lambda i: df.index[i].strftime("%Y-%m-%d")
    lc = pd.DataFrame([{
        "lifecycle_id": "LC1", "anchor_day": D(0), "breakout_day": D(breakout_i),
        "reattack_days": "|".join(d for d, _ in reattack_pairs) or None,
        "reattack_pullback_event_ids": "|".join(r for _, r in reattack_pairs) or None,
        "end_day": D(len(df) - 1), "end_reason": "data_end",
        "right_censored": True}])
    pb = [{"event_id": t2_event, "first_day": D(t2_first_i),
           "end_day": D(t2_end_i), "stabilization_day": None}]
    pdly = pd.DataFrame({"event_id": [t2_event],
                         "date": [D(t2_shrink_i)],
                         "shrink_volume": [True]})
    return lc, pb, pdly


def _mk_pairing_market():
    closes = [8.0] * 25 + [8.6] + [8.45, 8.4, 8.42] + [8.7] \
        + [8.8 + 0.05 * i for i in range(28)]
    vols = [1000] * 25 + [1500] + [500, 450, 480] + [1400] + [900] * 28
    return mk_daily(closes, [c * 0.998 for c in closes], vols)


def test_t3_paired_to_t2_event_not_first_reattack():
    # reattack_days 第一位属于突破前回调 PBPRE（早于 T2）——不得借用
    df = _mk_pairing_market()  # breakout=25, T2 缩量日=26, 合法 T3=29
    lc, pb, pdly = _mk_manual_lifecycle(
        df, breakout_i=25,
        reattack_pairs=[(df.index[24].strftime("%Y-%m-%d"), "PBPRE"),   # 突破前
                        (df.index[29].strftime("%Y-%m-%d"), "PBPOST")],
        t2_event="PBPOST", t2_first_i=26, t2_end_i=28, t2_shrink_i=26)
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["t2_fill_date"] == df.index[26].strftime("%Y-%m-%d")
    assert st["t3_fill_date"] == df.index[29].strftime("%Y-%m-%d")  # 配对 PBPOST
    assert st["t3_fill_date"] > st["t2_fill_date"]
    assert st["max_position"] == pytest.approx(1.00)


def test_t3_absent_when_t2_event_has_no_paired_reattack():
    # T2 回调事件无配对再上攻：T3 不成交，不借用其他事件的再上攻
    df = _mk_pairing_market()
    lc, pb, pdly = _mk_manual_lifecycle(
        df, breakout_i=25,
        reattack_pairs=[(df.index[27].strftime("%Y-%m-%d"), "PBOTHER")],
        t2_event="PBPOST", t2_first_i=26, t2_end_i=28, t2_shrink_i=26)
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["t2_fill_date"] == df.index[26].strftime("%Y-%m-%d")
    assert st["t3_fill_date"] is None          # 不借用 PBOTHER 的再上攻
    assert st["max_position"] == pytest.approx(0.60)


def test_t3_requires_t2_presence():
    # 第三批存在 ⇒ 第二批必须存在（无缩量日时即使有配对再上攻也不成交）
    df = _mk_pairing_market()
    lc, pb, pdly = _mk_manual_lifecycle(
        df, breakout_i=25,
        reattack_pairs=[(df.index[29].strftime("%Y-%m-%d"), "PBPOST")],
        t2_event="PBPOST", t2_first_i=26, t2_end_i=28, t2_shrink_i=26)
    pdly_empty = pd.DataFrame(columns=["event_id", "date", "shrink_volume"])
    ev = replay_entries("000001", lc, df, pb, pdly_empty, ReplayConfig(),
                        CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["t2_fill_date"] is None
    assert st["t3_fill_date"] is None
    assert st["max_position"] == pytest.approx(0.30)


def test_close_theory_position_enum_only_3060_100():
    # close 理论仓位只能 30/60/100；70/40 只可能出现在 next 实际视角
    df = _mk_pairing_market()
    lc, pb, pdly = _mk_manual_lifecycle(
        df, breakout_i=25,
        reattack_pairs=[(df.index[29].strftime("%Y-%m-%d"), "PBPOST")],
        t2_event="PBPOST", t2_first_i=26, t2_end_i=28, t2_shrink_i=26)
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["max_position"] in (0.30, 0.60, 1.00)
    ev2 = replay_entries("000001", lc, df, pb,
                         pd.DataFrame(columns=["event_id", "date",
                                                "shrink_volume"]),
                         ReplayConfig(), CostModel())
    assert ev2[ev2["strategy"] == "staged_entry"].iloc[0]["max_position"] \
        == pytest.approx(0.30)


def test_next_position_reconstructible_from_leg_reasons():
    # next 实际仓位必须能由各批失败原因严格还原
    df = _mk_pairing_market()
    lc, pb, pdly = _mk_manual_lifecycle(
        df, breakout_i=25,
        reattack_pairs=[(df.index[29].strftime("%Y-%m-%d"), "PBPOST")],
        t2_event="PBPOST", t2_first_i=26, t2_end_i=28, t2_shrink_i=26)
    _limit_up(df, 26)  # T1(25) 的次日一字板
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    legs = [("t1", 0.30), ("t2", 0.30), ("t3", 0.40)]
    w = sum(lw for tag, lw in legs if st[f"{tag}_next_status"] == "filled")
    assert st["fraction_invested_next"] == pytest.approx(w)
    for tag, _ in legs:
        if st[f"{tag}_next_status"] == "not_filled":
            assert st[f"{tag}_next_reason"] is not None
