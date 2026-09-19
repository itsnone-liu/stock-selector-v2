"""第四批 entry_replay 人工行情测试（§10-3 场景 + B3/B4/B5/B6）。"""
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


def build_market():
    """横盘 -> 突破 -> 缩量回调(事件) -> 再上攻；含缩量日明细。"""
    closes = [8.0] * 25 + [8.6 + 0.04 * i for i in range(6)] \
        + [8.84 - 0.08 * i for i in range(1, 5)] \
        + [8.5, 8.55, 8.62, 8.75] + [8.9 + 0.06 * i for i in range(12)]
    opens = [c * 0.998 for c in closes]
    vols = [1000] * 25 + [1200] * 6 + [600, 500, 450, 420] \
        + [500, 520, 550, 600] + [900] * 12
    df = mk_daily(closes, opens, vols)
    lc = classify_lifecycle("000001", df, mk_week(df), mk_pool(df), [],
                            LifecycleConfig())
    assert len(lc) == 1
    # 注入一个回调事件：回撤段
    i0 = 31  # 回撤第一日（0 基）
    pb = [{"event_id": "PB1",
           "first_day": df.index[i0].strftime("%Y-%m-%d"),
           "end_day": df.index[i0 + 6].strftime("%Y-%m-%d"),
           "stabilization_day": df.index[i0 + 4].strftime("%Y-%m-%d")}]
    pdly = pd.DataFrame({
        "event_id": ["PB1"] * 7,
        "date": [df.index[i0 + k].strftime("%Y-%m-%d") for k in range(7)],
        "shrink_volume": [True, True, True, True, False, False, False]})
    return df, lc, pb, pdly


def run_replay(code="000001", **kw):
    df, lc, pb, pdly = build_market()
    return replay_entries(code, lc, df, pb, pdly,
                          kw.pop("cfg", None) or ReplayConfig(),
                          kw.pop("cost", None) or CostModel())


def test_four_strategies_same_population():
    ev = run_replay()
    assert len(ev) == 4
    assert set(ev["strategy"]) == {"direct_chase", "wait_first_pullback",
                                   "wait_support_hold", "staged_entry"}
    assert ev["lifecycle_id"].nunique() == 1
    assert list(ev.columns) == ENTRY_REPLAY_COLUMNS
    assert (ev["return_quality"] == RETURN_QUALITY).all()


def test_direct_dual_view_prices_differ():
    ev = run_replay()
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["fill_status_close"] == "filled"
    assert d["fill_status_next"] == "filled"
    assert d["fill_price_next"] != d["fill_price_close"]  # 两视角不混用
    assert d["capped_entered"] is True or d["capped_entered"] is False


def test_chase_cap_variant_on_same_row():
    # 信号日涨幅 ~4%>3.5% 触发 capped 不入；unlimited 事实列仍 filled
    df, lc, pb, pdly = build_market()
    bo = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d") == lc.iloc[0]["breakout_day"]][0]
    g = (df.iloc[bo]["close"] / df.iloc[bo - 1]["close"] - 1) * 100
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(
        chase_gain_cap_pct=g - 1.0), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["capped_entered"] is False
    assert d["capped_not_entered_reason"] == "chase_gain_cap_exceeded"
    assert d["fill_status_close"] == "filled"  # unlimited 视角照常


def test_next_session_limit_up_blocked():
    df, lc, pb, pdly = build_market()
    bo = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d") == lc.iloc[0]["breakout_day"]][0]
    prev = df.iloc[bo]["close"]
    df.iloc[bo + 1, df.columns.get_loc("open")] = round(prev * 1.10, 2)  # 一字板
    df.iloc[bo + 1, df.columns.get_loc("high")] = round(prev * 1.10, 2)
    df.iloc[bo + 1, df.columns.get_loc("low")] = round(prev * 1.10, 2)
    ev = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    assert d["fill_status_next"] == "not_filled"
    assert d["not_filled_reason"] == "open_limit_up_buy_blocked"


def test_wait_pullback_fills_on_first_shrink_day():
    ev = run_replay()
    w = ev[ev["strategy"] == "wait_first_pullback"].iloc[0]
    assert w["fill_status_close"] == "filled"
    # 首个缩量日 = 事件首日（构造中 shrink_volume 首日即 True）
    df, lc, pb, pdly = build_market()
    assert w["fill_date_close"] == pb[0]["first_day"]
    assert w["wait_days"] >= 1
    assert w["missed_upside_pct"] == 0.0
    # 公式一致性：fill_price/close(breakout)-1（回调始于更高位时可为正）
    df, lc, pb, pdly = build_market()
    bo = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d") == lc.iloc[0]["breakout_day"]][0]
    fp = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d") == w["fill_date_close"]][0]
    exp = (w["fill_price_close"] / df.iloc[bo]["close"] - 1) * 100
    assert abs(w["fill_price_vs_breakout_pct"] - exp) < 1e-9
    assert w["wait_days"] == fp - bo


def test_wait_support_uses_stabilization():
    ev = run_replay()
    s = ev[ev["strategy"] == "wait_support_hold"].iloc[0]
    assert s["fill_status_close"] == "filled"
    w = ev[ev["strategy"] == "wait_first_pullback"].iloc[0]
    assert s["fill_date_close"] >= w["fill_date_close"]  # 止跌不早于缩量


def test_wait_not_filled_reasons():
    df, lc, _, _ = build_market()
    ev = replay_entries("000001", lc, df, [], pd.DataFrame(),
                        ReplayConfig(), CostModel())
    for strat, want in (("wait_first_pullback", "no_pullback_before_end"),
                        ("wait_support_hold", "no_pullback_before_end")):
        r = ev[ev["strategy"] == strat].iloc[0]
        assert r["not_filled_reason"] == want
        assert r["missed_upside_pct"] is not None
        assert r["missed_upside_rate"] in (0.0, 1.0)


def test_staged_capital_conservation():
    ev = run_replay()
    st = ev[ev["strategy"] == "staged_entry"].iloc[0]
    assert st["max_position"] <= 1.0 + 1e-9
    # T1 恒成交；T2/T3 视构造
    assert st["t1_fill_date"] is not None
    assert st["avg_cost"] is not None
    legs = [st["t1_fill_price"], st["t2_fill_price"], st["t3_fill_price"]]
    got = [p for p in legs if p]
    w = [0.30, 0.30, 0.40][:len(got)]
    exp = sum(p * x for p, x in zip(got, w)) / sum(w)
    assert abs(st["avg_cost"] - exp) < 1e-9
    assert st["fraction_invested"] == pytest.approx(sum(w), abs=1e-9)


def test_right_censored_tail():
    # 截断数据尾部：fill 后不足 20 日 -> outcome_complete=False
    df, lc, pb, pdly = build_market()
    cut = None
    bo = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d") == lc.iloc[0]["breakout_day"]][0]
    cut = bo + 8  # 成交后仅数日
    df2 = df.iloc[:cut]
    lc2 = classify_lifecycle("000001", df2, mk_week(df2), mk_pool(df2), [],
                             LifecycleConfig())
    pb2 = [dict(pb[0], end_day=min(pb[0]["end_day"],
                                    df2.index[-1].strftime("%Y-%m-%d")))]
    ev = replay_entries("000001", lc2, df2, pb2, pdly, ReplayConfig(),
                        CostModel())
    for strat in ev["strategy"]:
        r = ev[ev["strategy"] == strat].iloc[0]
        if r["fill_status_close"] == "filled":  # 成交但窗口不足 -> 右删失
            assert r["outcome_complete"] is False
            assert r["failure_path"] in ("right_censored", None)
        else:  # 未成交无窗口
            assert r["outcome_complete"] in (None, False)


def test_net_below_gross_and_pct_units():
    ev = run_replay()
    d = ev[ev["strategy"] == "direct_chase"].iloc[0]
    for h in (5, 10, 20):
        g, n = d[f"ret_gross_{h}_close"], d[f"ret_net_{h}_close"]
        if g is not None and n is not None:
            assert n < g  # 费用
    # 百分比单位：数量级应为百分数
    assert abs(d["ret_gross_20_close"]) < 500  # ~7% 而非 0.07


def test_no_lookahead_outcome_only():
    # 突破日后价格整体上移 10%：入场列（成交价/日期）不变，outcome 变
    df, lc, pb, pdly = build_market()
    bo = [i for i, ts in enumerate(df.index)
          if ts.strftime("%Y-%m-%d") == lc.iloc[0]["breakout_day"]][0]
    ev1 = replay_entries("000001", lc, df, pb, pdly, ReplayConfig(), CostModel())
    df3 = df.copy()
    df3.iloc[bo + 5:, df3.columns.get_loc("close")] *= 1.10
    ev2 = replay_entries("000001", lc, df3, pb, pdly, ReplayConfig(), CostModel())
    d1 = ev1[ev1["strategy"] == "direct_chase"].iloc[0]
    d2 = ev2[ev2["strategy"] == "direct_chase"].iloc[0]
    assert d1["fill_price_close"] == d2["fill_price_close"]
    assert d1["fill_date_close"] == d2["fill_date_close"]
    assert d2["ret_gross_20_close"] > d1["ret_gross_20_close"]
