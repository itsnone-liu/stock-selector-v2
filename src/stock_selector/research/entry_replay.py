"""第四批（阶段三研究）：四种入场策略回放。

语义契约（docs/plans/STAGE4_LIFECYCLE_ENTRY_REPLAY_SPEC.md §5-§10b，冻结）：
- 四种策略回放同一批生命周期事件，不得各自筛选总体；
- 收盘信号（signal_close）与次日开盘可成交（next_session_fill）两视角
  分列，绝不混用；四策略都有双视角；
- 双价格口径：raw_price 用于信号/成交/涨跌停/滑点；收益、MFE、MAE 属于
  adjusted_return 层——当前数据源无复权因子，return_quality=
  unadjusted_exploratory，仅限工程验证，不得用于策略结论或调参；
- 模拟资金 100,000 元/生命周期；卖出=观察期第 5/10/20 个交易日收盘；
- 分批 30/30/40 冻结（breakout/首个缩量日/reattack），窗口从第一笔成交
  日起算，收益分母=初始总资金，未投入现金收益记 0，另存各批次单独表现；
- 涨跌停为近似口径（无 ST 5% 历史状态数据），limitation=
  approximate_limit_ratio；
- 等待类输出成交/错失与等待成本三指标；未成交原因分列统计，不合并；
- 未来数据只进 outcome，不进入场特征。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from stock_selector.decision.execution import (
    EXECUTION_MODEL_VERSION, CostModel, execution_feasibility,
)

RULE_VERSION = "entry_replay_stage4_v1"
RETURN_QUALITY = "unadjusted_exploratory"
LIMITATION = "approximate_limit_ratio"

STRATEGIES = ("direct_chase", "wait_first_pullback", "wait_support_hold",
              "staged_entry")

CAPITAL = 100_000.0
HORIZONS = (5, 10, 20)


@dataclass(frozen=True)
class ReplayConfig:
    chase_gain_cap_pct: float = 3.5
    staged_tranches: tuple = ((0.30, "breakout"), (0.30, "pullback_shrink"),
                              (0.40, "reattack"))

    @classmethod
    def from_config(cls, config) -> "ReplayConfig":
        cap = getattr(getattr(config, "surge", None), "max_gain_pct", None)
        return cls(chase_gain_cap_pct=float(cap) if cap else 3.5)


# --------------------------------------------------------------------------
# 双价格口径接口：成交价层（raw）与收益层（adjusted）分离
# --------------------------------------------------------------------------
def raw_price(daily: pd.DataFrame, pos: int, field_: str = "close") -> float:
    """原始成交价层：信号、成交、涨跌停、滑点全部使用它。"""
    return float(daily.iloc[pos][field_])


def adjusted_return(daily: pd.DataFrame, p0: int, p1: int) -> float | None:
    """收益层：p1 相对 p0 的持有期收益（公司行动调整后）。

    当前实现 = 未复权价格比（工程验证口径）；接入复权因子后仅替换本函数。
    """
    if p0 < 0 or p1 >= len(daily) or p1 < p0:
        return None
    a, b = float(daily.iloc[p0]["close"]), float(daily.iloc[p1]["close"])
    return b / a - 1.0 if a > 0 else None


def adjusted_path_max(daily: pd.DataFrame, p0: int, p1: int) -> tuple:
    """收益层窗口极值：返回 (max_ret, min_ret)（含 p0..p1，相对 p0）。"""
    rets = [r for r in (adjusted_return(daily, p0, j)
                        for j in range(p0, min(p1 + 1, len(daily))))
            if r is not None]
    return (max(rets) if rets else None, min(rets) if rets else None)


ENTRY_REPLAY_COLUMNS = [
    # 身份
    "code", "lifecycle_id", "strategy",
    "lifecycle_end_reason", "right_censored", "return_quality", "limitation",
    # 信号与成交（收盘视角 / 次日开盘视角；价格为 raw 含滑点）
    "signal_day", "signal_day_gain_pct",
    "fill_status_close", "fill_date_close", "fill_price_close",
    "fill_status_next", "fill_date_next", "fill_price_next",
    "not_filled_reason",
    # 结果（收益层；三 horizon × 两视角）
    *[f"ret_gross_{h}_{v}" for h in HORIZONS for v in ("close", "next")],
    *[f"ret_net_{h}_{v}" for h in HORIZONS for v in ("close", "next")],
    "mfe_20_close", "mae_20_close", "mfe_20_next", "mae_20_next",
    "new_high_in_window", "days_to_new_high",
    "outcome_complete", "outcome_observed_days",
    "failure_path",
    # direct_chase 对照（B4）
    "capped_entered", "capped_not_entered_reason",
    # 等待类（B6 + §10-6 等待成本三指标）
    "missed_upside_pct", "missed_upside_rate",
    "wait_window_max_gain_pct", "fill_price_vs_breakout_pct", "wait_days",
    # 分批（B6 + §10-4）
    "t1_fill_date", "t1_fill_price", "t2_fill_date", "t2_fill_price",
    "t3_fill_date", "t3_fill_price",
    "t1_ret_20", "t2_ret_20", "t3_ret_20",
    "avg_cost", "capital_position_days", "max_position", "fraction_invested",
]


def _pos_map(daily: pd.DataFrame) -> dict:
    return {ts.strftime("%Y-%m-%d"): i for i, ts in enumerate(daily.index)}


def _slip(cost: CostModel, ref: float) -> float:
    return cost.fill_price(ref, "buy")


def _round_trip_net(cost: CostModel, buy_px: float, sell_px: float,
                    sell_day: date, capital: float) -> float | None:
    """净收益率：买入含滑点、卖出按收盘扣滑点，费用按金额比例计。"""
    if buy_px <= 0:
        return None
    shares = capital / buy_px
    gross = shares * sell_px
    buy_fees = cost.fees(capital, "buy", sell_day)["total"]
    sell_fees = cost.fees(gross, "sell", sell_day)["total"]
    return (gross - sell_fees) / (capital + buy_fees) - 1.0


def _outcome_block(out: dict, daily: pd.DataFrame, fill_pos: int | None,
                   cost: CostModel, breakout_pos: int,
                   breakout_close: float, code: str) -> None:
    """公共结果列：三 horizon 毛净收益 + MFE/MAE + 完整性 + failure_path。"""
    if fill_pos is None:
        out.update({"outcome_complete": None, "outcome_observed_days": 0,
                    "failure_path": None})
        return
    last = len(daily) - 1
    for h in HORIZONS:
        end_pos = min(fill_pos + h, last)
        complete = fill_pos + h <= last
        g = adjusted_return(daily, fill_pos, end_pos) if complete else None
        out[f"ret_gross_{h}_close"] = (g * 100.0) if g is not None else None
        out[f"ret_gross_{h}_next"] = (g * 100.0) if g is not None else None
        if complete and g is not None:
            sell_day = daily.index[end_pos].date()
            out[f"ret_net_{h}_close"] = _round_trip_net(
                cost, out["fill_price_close"], raw_price(daily, end_pos),
                sell_day, CAPITAL) * 100.0
            nxt = out.get("fill_price_next")
            out[f"ret_net_{h}_next"] = (
                _round_trip_net(cost, nxt, raw_price(daily, end_pos),
                                sell_day, CAPITAL) * 100.0
                if nxt else None)
        else:
            out[f"ret_net_{h}_close"] = None
            out[f"ret_net_{h}_next"] = None
    # MFE/MAE：20 日窗（含成交日），收益层
    mfe, mae = adjusted_path_max(daily, fill_pos, min(fill_pos + 20, last))
    out["mfe_20_close"] = mfe * 100.0 if mfe is not None else None
    out["mae_20_close"] = mae * 100.0 if mae is not None else None
    out["mfe_20_next"] = out["mfe_20_close"]
    out["mae_20_next"] = out["mae_20_close"]
    obs = min(20, max(0, last - fill_pos))
    out["outcome_complete"] = obs == 20
    out["outcome_observed_days"] = obs
    # 新高：窗口内首次回到突破收盘之上（close 视角，raw 层）
    if breakout_close:
        nh = next((j - fill_pos for j in range(fill_pos, min(fill_pos + 20, last + 1))
                   if raw_price(daily, j) >= breakout_close), None)
        out["new_high_in_window"] = nh is not None
        out["days_to_new_high"] = nh
    # failure_path：右删失不算失败
    if out["outcome_complete"] is False:
        out["failure_path"] = "right_censored"
    elif out.get("ret_net_20_close") is not None:
        out["failure_path"] = ("ok" if out["ret_net_20_close"] >= 0
                               else "entry_poor")
    else:
        out["failure_path"] = "trend_failed"


def _next_view(out: dict, daily: pd.DataFrame, code: str, fill_pos: int,
               cost: CostModel) -> None:
    """次日开盘可成交视角：一字涨停/停牌阻断，不使用陈旧价格。"""
    npos = fill_pos + 1
    if npos >= len(daily):
        out.update({"fill_status_next": "not_filled",
                    "not_filled_reason": "missing_bar_or_suspended"})
        return
    prev_close = raw_price(daily, fill_pos)
    ok, reason = execution_feasibility(code, daily.iloc[npos], prev_close, "buy")
    if ok:
        out["fill_status_next"] = "filled"
        out["fill_date_next"] = daily.index[npos].strftime("%Y-%m-%d")
        out["fill_price_next"] = _slip(cost, raw_price(daily, npos, "open"))
    else:
        out["fill_status_next"] = "not_filled"
        out["not_filled_reason"] = reason


def _wait_metrics(out: dict, daily: pd.DataFrame, breakout_pos: int,
                  fill_pos: int | None, end_pos: int,
                  breakout_close: float, fill_price: float | None) -> None:
    """等待成本三指标 + 错失（§10-6、§11）。"""
    if fill_pos is not None:
        seg_max = max((raw_price(daily, j) for j in
                       range(breakout_pos, fill_pos)), default=breakout_close)
        out["wait_window_max_gain_pct"] = (
            seg_max / breakout_close - 1.0) * 100.0 if breakout_close else None
        out["fill_price_vs_breakout_pct"] = (
            fill_price / breakout_close - 1.0) * 100.0 \
            if (fill_price and breakout_close) else None
        out["wait_days"] = fill_pos - breakout_pos
        out["missed_upside_pct"] = 0.0
        out["missed_upside_rate"] = 0.0
    else:
        w = None
        if end_pos > breakout_pos and breakout_close:
            w = (max(raw_price(daily, j) for j in
                     range(breakout_pos, end_pos + 1)) / breakout_close - 1.0)
        out["missed_upside_pct"] = w * 100.0 if w is not None else None
        out["missed_upside_rate"] = 1.0 if (w is not None and w > 0) else \
            (0.0 if w is not None else None)


def replay_entries(code: str, lifecycles: pd.DataFrame, daily: pd.DataFrame,
                   pullback_events: list, pullback_daily: pd.DataFrame,
                   cfg: ReplayConfig | None = None,
                   cost: CostModel | None = None) -> pd.DataFrame:
    """单股四策略回放：每 lifecycle×strategy 一行。

    lifecycles: classify_lifecycle 输出（单股）；
    pullback_events: [{event_id, first_day, end_day, stabilization_day}]；
    pullback_daily: 回调明细（event_id, date, shrink_volume）。
    """
    cfg = cfg or ReplayConfig()
    cost = cost or CostModel()
    pos = _pos_map(daily)
    rows: list[dict] = []
    for lc in (lifecycles.to_dict("records") if len(lifecycles) else []):
        bo = pos.get(lc["breakout_day"])
        end = pos.get(lc["end_day"])
        if bo is None:
            continue
        bo_close = raw_price(daily, bo)
        prev_close = raw_price(daily, bo - 1) if bo > 0 else None
        sig_gain = (bo_close / prev_close - 1.0) * 100.0 if prev_close else None
        # 等待类候选：突破后开始的本生命周期回调事件
        pbs = [e for e in pullback_events
               if e["first_day"] > lc["breakout_day"]
               and pos.get(e["first_day"], 10**9) >= pos.get(lc["anchor_day"], 0)]
        first_pb = pbs[0] if pbs else None
        shrink_day = None
        stab_day = None
        if first_pb is not None and len(pullback_daily):
            dd = pullback_daily[
                (pullback_daily["event_id"] == first_pb["event_id"])
                & (pullback_daily["shrink_volume"] == True)]  # noqa: E712
            if len(dd):
                shrink_day = pos.get(str(dd.iloc[0]["date"]))
            stab_day = pos.get(first_pb.get("stabilization_day")) \
                if first_pb.get("stabilization_day") else None

        for strategy in STRATEGIES:
            out = {"code": code, "lifecycle_id": lc["lifecycle_id"],
                   "strategy": strategy,
                   "lifecycle_end_reason": lc["end_reason"],
                   "right_censored": bool(lc["right_censored"]),
                   "return_quality": RETURN_QUALITY,
                   "limitation": LIMITATION,
                   "signal_day": lc["breakout_day"],
                   "signal_day_gain_pct": sig_gain,
                   "capped_entered": None, "capped_not_entered_reason": None,
                   "missed_upside_pct": None, "missed_upside_rate": None,
                   "wait_window_max_gain_pct": None,
                   "fill_price_vs_breakout_pct": None, "wait_days": None,
                   "t1_fill_date": None, "t1_fill_price": None,
                   "t2_fill_date": None, "t2_fill_price": None,
                   "t3_fill_date": None, "t3_fill_price": None,
                   "t1_ret_20": None, "t2_ret_20": None, "t3_ret_20": None,
                   "avg_cost": None, "capital_position_days": None,
                   "max_position": None, "fraction_invested": None,
                   "fill_status_close": "not_filled",
                   "fill_date_close": None, "fill_price_close": None,
                   "fill_status_next": "not_filled",
                   "fill_date_next": None, "fill_price_next": None,
                   "not_filled_reason": None,
                   "new_high_in_window": None, "days_to_new_high": None}

            if strategy == "direct_chase":
                out["capped_entered"] = not (sig_gain is not None
                                             and sig_gain > cfg.chase_gain_cap_pct)
                if not out["capped_entered"]:
                    out["capped_not_entered_reason"] = "chase_gain_cap_exceeded"
                fpos = bo
                out["fill_status_close"] = "filled"
                out["fill_date_close"] = lc["breakout_day"]
                out["fill_price_close"] = _slip(cost, bo_close)
                _next_view(out, daily, code, fpos, cost)
                _outcome_block(out, daily, fpos, cost, bo, bo_close, code)

            elif strategy == "wait_first_pullback":
                fpos = shrink_day
                if fpos is not None:
                    out["fill_status_close"] = "filled"
                    out["fill_date_close"] = daily.index[fpos].strftime("%Y-%m-%d")
                    out["fill_price_close"] = _slip(cost, raw_price(daily, fpos))
                    _next_view(out, daily, code, fpos, cost)
                else:
                    out["not_filled_reason"] = (
                        "no_pullback_before_end" if first_pb is None
                        else "no_shrink_day")
                _wait_metrics(out, daily, bo, fpos, end, bo_close,
                              out.get("fill_price_close"))
                _outcome_block(out, daily, fpos, cost, bo, bo_close, code)

            elif strategy == "wait_support_hold":
                fpos = stab_day
                if fpos is not None:
                    out["fill_status_close"] = "filled"
                    out["fill_date_close"] = daily.index[fpos].strftime("%Y-%m-%d")
                    out["fill_price_close"] = _slip(cost, raw_price(daily, fpos))
                    _next_view(out, daily, code, fpos, cost)
                else:
                    out["not_filled_reason"] = (
                        "no_pullback_before_end" if first_pb is None
                        else "no_stabilization")
                _wait_metrics(out, daily, bo, fpos, end, bo_close,
                              out.get("fill_price_close"))
                _outcome_block(out, daily, fpos, cost, bo, bo_close, code)

            else:  # staged_entry
                t1p = bo
                t2p = shrink_day
                t3p = pos.get(lc["reattack_days"].split("|")[0]) \
                    if lc["reattack_days"] else None
                out["t1_fill_date"] = daily.index[t1p].strftime("%Y-%m-%d")
                out["t1_fill_price"] = _slip(cost, raw_price(daily, t1p))
                legs = [(t1p, out["t1_fill_price"], cfg.staged_tranches[0][0])]
                if t2p is not None:
                    out["t2_fill_date"] = daily.index[t2p].strftime("%Y-%m-%d")
                    out["t2_fill_price"] = _slip(cost, raw_price(daily, t2p))
                    legs.append((t2p, out["t2_fill_price"],
                                 cfg.staged_tranches[1][0]))
                if t3p is not None:
                    out["t3_fill_date"] = daily.index[t3p].strftime("%Y-%m-%d")
                    out["t3_fill_price"] = _slip(cost, raw_price(daily, t3p))
                    legs.append((t3p, out["t3_fill_price"],
                                 cfg.staged_tranches[2][0]))
                wsum = sum(w for _, _, w in legs)
                out["avg_cost"] = (sum(px * w for _, px, w in legs) / wsum
                                   if wsum else None)
                out["max_position"] = wsum
                out["fraction_invested"] = wsum
                out["fill_status_close"] = "filled" if wsum > 0 else "not_filled"
                out["fill_date_close"] = out["t1_fill_date"]
                out["fill_price_close"] = out["t1_fill_price"]
                _next_view(out, daily, code, t1p, cost)
                # 各批次单独表现 + 资金占用（20 日窗，从第一笔起）
                last = len(daily) - 1
                h20 = min(t1p + 20, last)
                cpx = raw_price(daily, h20)
                for tag, (lp, lpx) in zip(("t1", "t2", "t3"),
                                          [(t1p, out["t1_fill_price"]),
                                           (t2p, out["t2_fill_price"]
                                            if t2p is not None else None),
                                           (t3p, out["t3_fill_price"]
                                            if t3p is not None else None)]):
                    if lp is not None and lpx:
                        r = adjusted_return(daily, lp, h20)
                        out[f"{tag}_ret_20"] = r * 100.0 if r is not None else None
                out["capital_position_days"] = sum(
                    w * (h20 - lp) for lp, _, w in legs)
                # 分批整体：分母=总资金，未投入现金收益 0
                if t1p + 20 <= last:
                    port = sum(w * CAPITAL * (1.0 + (adjusted_return(daily, lp, h20) or 0.0))
                               for lp, _, w in legs)
                    net = _round_trip_net(
                        cost, out["avg_cost"] if wsum == 1.0 else out["t1_fill_price"],
                        cpx, daily.index[h20].date(), CAPITAL * wsum if wsum else CAPITAL)
                    out["ret_gross_20_close"] = (port / CAPITAL - 1.0) * 100.0
                    out["ret_net_20_close"] = net * 100.0 if net is not None else None
                    for h in (5, 10):
                        hp = min(t1p + h, last)
                        if t1p + h <= last:
                            g = adjusted_return(daily, t1p, hp)
                            out[f"ret_gross_{h}_close"] = g * 100.0 if g is not None else None
                    obs = min(20, last - t1p)
                    out["outcome_complete"] = obs == 20
                    out["outcome_observed_days"] = obs
                    out["failure_path"] = ("ok" if (out["ret_net_20_close"] or 0) >= 0
                                           else "entry_poor")
                else:
                    out["outcome_complete"] = False
                    out["outcome_observed_days"] = max(0, min(20, last - t1p))
                    out["failure_path"] = "right_censored"
                _wait_metrics(out, daily, bo, t2p, end, bo_close, None)
            rows.append(out)
    return pd.DataFrame(rows, columns=ENTRY_REPLAY_COLUMNS)
