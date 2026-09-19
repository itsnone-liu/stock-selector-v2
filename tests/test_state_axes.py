"""周线双轴人工行情语义测试（第二批晋级门槛，方案 5.5）。

构造人工 OHLCV 序列覆盖每个状态，校验程序分类与人工判断一致；
不一致时先修语义，不根据收益调阈值。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stock_selector.research import state_axes as sa

CFG = sa.AxesConfig(min_volume_ratio=0.8, veto_ratio=1.5)


def make_daily(weeks: list[tuple[str, float, float]], base=10.0,
               start="2024-01-01", vol_base=1_000_000.0) -> pd.DataFrame:
    """按周构造日线：weeks = [(方向, 周涨跌幅%, 量比)]，方向 u=阳/d=阴。

    每周 5 个交易日；量比 = 该周总量 / 上一周总量（首周相对 vol_base），
    与分类器内部 volume ratio 口径一致。
    """
    idx = pd.bdate_range(start=start, periods=len(weeks) * 5)
    rows = []
    price = base
    prev_wv = vol_base
    for k, (direction, pct, vr) in enumerate(weeks):
        target = price * (1 + pct / 100.0) if direction == "u" else price * (1 - pct / 100.0)
        wv = vol_base * vr if k == 0 else prev_wv * vr
        for i in range(5):
            frac = (i + 1) / 5
            close = price + (target - price) * frac
            open_ = price if i == 0 else rows[-1]["close"]
            rows.append({"open": open_, "high": max(open_, close) * 1.005,
                         "low": min(open_, close) * 0.995, "close": close,
                         "volume": wv / 5})
        price = target
        prev_wv = wv
    return pd.DataFrame(rows, index=idx)


def calendar_of(df: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(df.index)


def axes_of(df: pd.DataFrame):
    return sa.classify_stock_axes(df, calendar_of(df), CFG, min_history=10)


def last_row(res: pd.DataFrame) -> pd.Series:
    return res.iloc[-1]


def test_trend_intact_and_strengthening():
    # 连续三周阳线温和放量上攻
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 5, 1.3)])
    res = axes_of(df)
    r = last_row(res)
    assert r["trend_structure"] == sa.TREND_INTACT
    assert r["current_momentum"] == sa.MOM_STRENGTHENING
    assert r["evidence_completeness"] == "full_week_confirm"


def test_healthy_pullback_shrinking_decline():
    # 上攻后一周缩量回调（量比 0.5 < 0.8）
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 4, 1.0), ("d", 3, 0.5)])
    res = axes_of(df)
    r = last_row(res)
    assert r["trend_structure"] in (sa.TREND_INTACT, sa.TREND_DAMAGE)
    assert r["current_momentum"] == sa.MOM_HEALTHY_PULLBACK
    assert r["prev_week_class"] == sa.WEEK_ACTIVE_UP


def test_heavy_volume_decline_veto():
    # 当周放量阴线（量比 2.0 >= 1.5）
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 4, 1.0), ("d", 4, 2.0)])
    res = axes_of(df)
    r = last_row(res)
    assert r["current_momentum"] == sa.MOM_HEAVY_DECLINE


def test_trend_broken_by_consecutive_heavy_declines():
    # 连续两周放量下跌 -> broken（PIT：第5周的时点才看全两个已完成放量周）
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("d", 5, 2.0), ("d", 5, 2.2),
                     ("d", 3, 0.5)])
    res = axes_of(df)
    r = last_row(res)
    assert r["trend_structure"] == sa.TREND_BROKEN
    assert r["consecutive_heavy_decline_weeks"] == 2
    # 第4周周五时点只见 1 个已完成放量周 -> starting_to_damage
    week4_friday = res.iloc[19]
    assert week4_friday["trend_structure"] == sa.TREND_DAMAGE


def test_trend_broken_by_breaking_prior_low():
    # 前周收盘跌破前前周低点 -> broken（W1 上攻 low≈9.95，W2 -8% 收 9.75 < 9.95）
    df = make_daily([("u", 6, 1.0), ("d", 8, 0.9), ("u", 5, 1.2)])
    res = axes_of(df)
    r = last_row(res)
    assert r["trend_structure"] == sa.TREND_BROKEN
    assert r["trend_structure_reason"] == "prev_week_close_below_prev2_low"


def test_recovering_after_decline_week():
    # 前周缩量阴，当周转阳收上前周收盘 -> recovering + 跨周恢复效率
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("d", 4, 0.6), ("u", 6, 1.1)])
    res = axes_of(df)
    r = last_row(res)
    assert r["current_momentum"] == sa.MOM_RECOVERING
    assert r["prev_week_class"] == sa.WEEK_SHRINKING_DECLINE
    assert r["cross_week_recovery_eff"] is not None


def test_monday_carry_and_veto():
    # 周一：沿用上一完整周；有完整周基础的周一全部 carry
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 5, 1.1)])
    res = axes_of(df)
    mondays = res[(res["session_ordinal_in_week"] == 1)
                  & res["prev_week_class"].notna()]
    assert len(mondays) >= 2
    assert (mondays["evidence_completeness"] == "carry_previous_week").all()
    assert (mondays["weekday_path"] == "monday_carry").all()
    # 首周周一无完整周基础 -> early/insufficient
    first_monday = res[res["session_ordinal_in_week"] == 1].iloc[0]
    assert first_monday["weekday_path"] == "early"


def test_tuesday_double_bear_shrinking():
    # 周二双阴缩量 -> 卖压衰减路径（手搓最后一周：周一阴、周二阴且量减半）
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 5, 1.1)])
    i_open = df.columns.get_loc("open")
    i_vol = df.columns.get_loc("volume")
    mon, tue = df.iloc[-5], df.iloc[-4]
    df.iloc[-5, i_open] = mon["close"] * 1.01   # 周一阴线
    df.iloc[-4, i_open] = tue["close"] * 1.02   # 周二阴线
    df.iloc[-4, i_vol] = mon["volume"] * 0.5    # 周二缩量
    res = sa.classify_stock_axes(df, pd.DatetimeIndex(df.index), CFG, min_history=10)
    tues = res[res["session_ordinal_in_week"] == 2]
    last_tue = tues.iloc[-1]
    assert last_tue["weekday_path"] == "decline_pressure_fade"
    assert last_tue["current_momentum"] == sa.MOM_HEALTHY_PULLBACK


def test_short_week_planned_sessions():
    # 节假日短周：planned 按日历真实交易日数（最后一周只交易3天）
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 4, 1.0), ("u", 5, 1.1)])
    cal = pd.DatetimeIndex(df.index)
    cal = cal[~cal.isin([cal[-1], cal[-2]])]  # 最后一周只交易3天
    df = df[df.index.isin(cal)]               # 个股数据也只剩3天
    res = sa.classify_stock_axes(df, cal, CFG, min_history=10)
    last = res.iloc[-1]
    assert last["planned_sessions_this_week"] == 3
    assert last["session_ordinal_in_week"] == 3
    assert last["evidence_completeness"] == "full_week_confirm"  # 短周末日=完整周


def test_insufficient_evidence_short_history():
    df = make_daily([("u", 5, 1.0)])
    res = axes_of(df)
    # 少于2完整周：insufficient / 早期行 unclear
    assert (res["trend_structure"] == sa.TREND_INSUFFICIENT).all()


def test_no_future_leakage():
    # 截断到 d 的分类必须与全量数据在 d 日的分类一致（实时特征隔离）
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("d", 3, 0.5), ("u", 6, 1.1),
                     ("d", 5, 2.0)])
    full = sa.classify_stock_axes(df, pd.DatetimeIndex(df.index), CFG, min_history=10)
    cut = df.index[len(df) // 2]
    part = sa.classify_stock_axes(df[df.index <= cut], pd.DatetimeIndex(
        df.index[df.index <= cut]), CFG, min_history=10)
    merged = part.merge(full, on="date", suffixes=("_p", "_f"))
    assert (merged["trend_structure_p"] == merged["trend_structure_f"]).all()
    assert (merged["current_momentum_p"] == merged["current_momentum_f"]).all()
    # None 列先统一填充再比（NaN != NaN）
    assert (merged["prev_week_class_p"].fillna("__na__")
            == merged["prev_week_class_f"].fillna("__na__")).all()


def test_recovery_eff_price_invariant():
    """恢复效率必须无量纲：相同百分比走势在 10 元和 100 元基准下结果一致。"""
    effs = []
    for base in (10.0, 100.0):
        df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("d", 4, 0.6), ("u", 6, 1.1)],
                        base=base)
        res = axes_of(df)
        r = last_row(res)
        assert r["current_momentum"] == sa.MOM_RECOVERING
        effs.append(r["cross_week_recovery_eff"])
    assert effs[0] == effs[1] and effs[0] > 0


def test_monday_veto_prorated_volume():
    """周一放量阴否决按周完成度折算：单日 40% 周量、折算 2 倍于上周即触发。"""
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 4, 1.0), ("u", 5, 1.0)])
    # 重写最后一周：周一巨量阴线 = 0.4 * (2.0 * 上周量) -> 折算量比 2.0 >= 1.5
    i_open = df.columns.get_loc("open")
    i_vol = df.columns.get_loc("volume")
    prev_week_vol = float(df["volume"].iloc[-10:-5].sum())
    mon = df.index[-5]
    df.loc[mon, "open"] = df.loc[mon, "close"] * 1.03  # 阴线
    df.loc[mon, "volume"] = 0.4 * 2.0 * prev_week_vol
    res = sa.classify_stock_axes(df, pd.DatetimeIndex(df.index), CFG, min_history=10)
    monday = res[res["session_ordinal_in_week"] == 1].iloc[-1]
    assert monday["current_momentum"] == sa.MOM_HEAVY_DECLINE
    assert monday["weekday_path"] == "monday_veto"
    assert monday["evidence_completeness"] == "intraday_veto"
    # 反例：同样巨量但阳线 -> 不否决，沿用上周
    df2 = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 4, 1.0), ("u", 5, 1.0)])
    df2.loc[mon, "open"] = df2.loc[mon, "close"] * 0.97  # 阳线
    df2.loc[mon, "volume"] = 0.4 * 2.0 * prev_week_vol
    res2 = sa.classify_stock_axes(df2, pd.DatetimeIndex(df2.index), CFG, min_history=10)
    monday2 = res2[res2["session_ordinal_in_week"] == 1].iloc[-1]
    assert monday2["weekday_path"] == "monday_carry"
    assert monday2["current_momentum"] == sa.MOM_STRENGTHENING


def test_every_day_one_row_and_columns():
    df = make_daily([("u", 5, 1.0), ("u", 6, 1.2), ("u", 4, 1.0), ("d", 3, 0.5),
                     ("u", 6, 1.1)])
    res = sa.classify_stock("000001", df, pd.DatetimeIndex(df.index), CFG,
                            min_history=10)
    assert list(res.columns) == sa.AXES_COLUMNS
    assert len(res) == len(df)
    assert (res["code"] == "000001").all()
    assert res["date"].is_unique
