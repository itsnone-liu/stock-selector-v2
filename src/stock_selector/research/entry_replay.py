"""第四批（阶段三研究）：四种入场策略回放。

语义契约（docs/plans/STAGE4_LIFECYCLE_ENTRY_REPLAY_SPEC.md §5-§10b，冻结）：
- 每个生命周期 × 四种策略各一行；无突破的生命周期输出四行未成交记录
  （reason=no_breakout_signal），不静默丢弃样本；
- 四种策略回放同一批生命周期事件，不得各自筛选总体；
- 收盘信号与次日开盘两视角完全独立：成交日、收益起点、5/10/20 收益、
  MFE/MAE、完整性、失败路径、未成交原因全部分列，绝不混用；
- 「下一交易日」按市场交易日历：下一市场日无个股行情即停牌
  （missing_bar_or_suspended），不得滑到复牌日冒充次日成交；
- 回调候选限定在本生命周期内（first_day/shrink/stabilization 均不晚于
  lifecycle.end_day），事件按日期排序取最早；
- 双价格口径：raw_price 用于信号/成交/涨跌停/滑点（卖出同扣滑点）；
  收益层 adjusted_return 当前为未复权工程口径（return_quality=
  unadjusted_exploratory），仅限工程验证，禁止策略结论与调参；
- 模拟资金 100,000 元/生命周期；卖出=观察期第 5/10/20 个交易日收盘；
- 分批 30/30/40：组合价值 = 未投入现金 + Σ 各批持仓价值；窗口内未成交
  批次保持现金（收益 0）；各批最低佣金分别计算；资金占用天数非负；
  次日视角下每批独立检查可成交性；
- 新高判定：成交后完整 20 个交易日内（含第 20 日）首次回到突破收盘
  之上；不足 20 日记缺失；5/10/20 分别保存完整性与观察天数；
- 等待类输出成交/错失与等待成本三指标；未来数据只进 outcome。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from stock_selector.decision.execution import (
    EXECUTION_MODEL_VERSION, CostModel, execution_feasibility,
)

RULE_VERSION = "entry_replay_stage4_v5"
RETURN_QUALITY = "unadjusted_exploratory"
LIMITATION = "approximate_limit_ratio"

STRATEGIES = ("direct_chase", "wait_first_pullback", "wait_support_hold",
              "staged_entry")

CAPITAL = 100_000.0
HORIZONS = (5, 10, 20)

NOT_FILLED_REASONS = (
    "no_breakout_signal", "no_pullback_before_end", "no_shrink_day",
    "no_stabilization", "open_limit_up_buy_blocked",
    "missing_bar_or_suspended",
)


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
# 双价格口径接口
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
    rets = [r for r in (adjusted_return(daily, p0, j)
                        for j in range(p0, min(p1 + 1, len(daily))))
            if r is not None]
    return (max(rets) if rets else None, min(rets) if rets else None)


def _cols() -> list:
    c = ["code", "lifecycle_id", "strategy", "lifecycle_end_reason",
         "right_censored", "return_quality", "limitation",
         "anchor_day", "signal_day", "signal_day_gain_pct",
         "fill_status_close", "fill_date_close", "fill_price_close",
         "not_filled_reason_close",
         "fill_status_next", "fill_date_next", "fill_price_next",
         "not_filled_reason_next"]
    c += [f"ret_gross_{h}_{v}" for h in HORIZONS for v in ("close", "next")]
    c += [f"ret_net_{h}_{v}" for h in HORIZONS for v in ("close", "next")]
    c += ["mfe_20_close", "mae_20_close", "mfe_20_next", "mae_20_next",
          "new_high_in_window_close", "days_to_new_high_close",
          "new_high_in_window_next", "days_to_new_high_next"]
    c += [f"outcome_{h}d_complete" for h in HORIZONS]
    c += [f"outcome_{h}d_observed" for h in HORIZONS]
    c += [f"outcome_{h}d_complete_next" for h in HORIZONS]
    c += [f"outcome_{h}d_observed_next" for h in HORIZONS]
    c += ["outcome_complete", "outcome_observed_days",
          "failure_path_close", "failure_path_next",
          "capped_entered", "capped_not_entered_reason",
          "missed_upside_pct", "missed_upside_rate",
          "wait_window_max_gain_pct", "fill_price_vs_breakout_pct",
          "wait_days"]
    c += ["t1_fill_date", "t1_fill_price", "t2_fill_date", "t2_fill_price",
          "t3_fill_date", "t3_fill_price",
          "t1_ret_20", "t2_ret_20", "t3_ret_20",
          "avg_cost", "capital_position_days", "max_position",
          "fraction_invested"]
    c += [f"{t}_next_{f}" for t in ("t1", "t2", "t3")
          for f in ("status", "date", "price", "reason")]
    c += ["fraction_invested_next", "max_position_next", "avg_cost_next",
          "capital_position_days_next"]
    return c


ENTRY_REPLAY_COLUMNS = _cols()


def _pos_map(daily: pd.DataFrame) -> dict:
    return {ts.strftime("%Y-%m-%d"): i for i, ts in enumerate(daily.index)}


def _next_market_session(market_cal: pd.DatetimeIndex,
                         day: pd.Timestamp) -> pd.Timestamp | None:
    m = market_cal.searchsorted(day, side="right")
    return market_cal[m] if m < len(market_cal) else None


def _round_trip_net(cost: CostModel, buy_px: float, sell_px: float,
                    sell_day: date, capital: float = CAPITAL) -> float | None:
    """净收益率：买卖都含滑点，费用按金额比例、每笔最低佣金分别计。"""
    if buy_px <= 0:
        return None
    shares = capital / buy_px
    gross = shares * sell_px
    buy_fees = cost.fees(capital, "buy", sell_day)["total"]
    sell_fees = cost.fees(gross, "sell", sell_day)["total"]
    return (gross - sell_fees) / (capital + buy_fees) - 1.0


def _view_outcome(out: dict, daily: pd.DataFrame, view: str,
                  start_pos: int | None, cost: CostModel,
                  buy_price: float | None,
                  breakout_close: float) -> None:
    """单视角结果列。close 视角 start=成交日；next 视角 start=次日成交日。"""
    suffix = view
    if start_pos is None or not buy_price or buy_price <= 0:
        for h in HORIZONS:
            out[f"ret_gross_{h}_{suffix}"] = None
            out[f"ret_net_{h}_{suffix}"] = None
        for k in ("mfe_20", "mae_20"):
            out[f"{k}_{suffix}"] = None
        out[f"new_high_in_window_{suffix}"] = None
        out[f"days_to_new_high_{suffix}"] = None
        out[f"failure_path_{suffix}"] = None
        return
    last = len(daily) - 1
    ck = (lambda h: f"outcome_{h}d_complete") if view == "close" else \
        (lambda h: f"outcome_{h}d_complete_next")
    ok_ = (lambda h: f"outcome_{h}d_observed") if view == "close" else \
        (lambda h: f"outcome_{h}d_observed_next")
    for h in HORIZONS:
        end_pos = start_pos + h
        complete = end_pos <= last
        out[ck(h)] = complete
        out[ok_(h)] = min(h, max(0, last - start_pos))
        # 毛收益 = 市场价格比：close 视角买=成交日收盘，next 视角买=次日
        # 开盘（滑点与费用只进净收益）
        base = raw_price(daily, start_pos) if view == "close" \
            else raw_price(daily, start_pos, "open")
        g = None
        if complete and base > 0:
            g = raw_price(daily, end_pos) / base - 1.0
        out[f"ret_gross_{h}_{suffix}"] = g * 100.0 if g is not None else None
        if complete:
            sell_day = daily.index[end_pos].date()
            sell_px = cost.fill_price(raw_price(daily, end_pos), "sell")
            net = _round_trip_net(cost, buy_price, sell_px, sell_day)
            out[f"ret_net_{h}_{suffix}"] = net * 100.0 if net is not None else None
        else:
            out[f"ret_net_{h}_{suffix}"] = None
    # MFE/MAE 基准 = 本视角实际成交市场价（close=成交日收盘；next=次日开盘）
    mfe_base = raw_price(daily, start_pos) if view == "close" \
        else raw_price(daily, start_pos, "open")
    path_rets = [raw_price(daily, j) / mfe_base - 1.0
                 for j in range(start_pos, min(start_pos + 20, last) + 1)]
    out[f"mfe_20_{suffix}"] = max(path_rets) * 100.0
    out[f"mae_20_{suffix}"] = min(path_rets) * 100.0
    # 新高：完整 20 日窗（含第 20 日）；不足 20 日记缺失
    if start_pos + 20 <= last:
        # 从成交后第一个交易日起搜索（成交日本身不算）；等于突破价也算
        nh = next((j - start_pos for j
                   in range(start_pos + 1, start_pos + 20 + 1)
                   if raw_price(daily, j) >= breakout_close), None)
        out[f"new_high_in_window_{suffix}"] = nh is not None
        out[f"days_to_new_high_{suffix}"] = nh
    else:
        out[f"new_high_in_window_{suffix}"] = None
        out[f"days_to_new_high_{suffix}"] = None
    comp_key = "outcome_20d_complete" if view == "close" \
        else "outcome_20d_complete_next"
    if out.get(comp_key) is False:
        out[f"failure_path_{suffix}"] = "right_censored"
    elif out.get(f"ret_net_20_{suffix}") is not None:
        out[f"failure_path_{suffix}"] = (
            "ok" if out[f"ret_net_20_{suffix}"] >= 0 else "entry_poor")
    else:
        out[f"failure_path_{suffix}"] = "trend_failed"


def _next_fill(daily: pd.DataFrame, market_cal: pd.DatetimeIndex, code: str,
               fill_pos: int, cost: CostModel) -> tuple:
    """按市场日历找下一市场交易日的开盘成交。

    返回 (npos, price)；失败返回 (None, reason)。
    下一市场日无个股行情 = 停牌，不滑到复牌日。
    """
    nxt_day = _next_market_session(market_cal, daily.index[fill_pos])
    if nxt_day is None:
        return None, "missing_bar_or_suspended"
    key = nxt_day.strftime("%Y-%m-%d")
    pmap = _pos_map(daily)
    npos = pmap.get(key)
    if npos is None:
        return None, "missing_bar_or_suspended"
    prev_close = raw_price(daily, fill_pos)
    ok, reason = execution_feasibility(code, daily.iloc[npos], prev_close, "buy")
    if not ok:
        return None, reason
    return npos, cost.fill_price(raw_price(daily, npos, "open"), "buy")


def _next_view(out: dict, daily: pd.DataFrame, market_cal: pd.DatetimeIndex,
               code: str, fill_pos: int, cost: CostModel) -> int | None:
    npos, price_or_reason = _next_fill(daily, market_cal, code, fill_pos, cost)
    if npos is None:
        out["fill_status_next"] = "not_filled"
        out["not_filled_reason_next"] = price_or_reason
        return None
    out["fill_status_next"] = "filled"
    out["fill_date_next"] = daily.index[npos].strftime("%Y-%m-%d")
    out["fill_price_next"] = price_or_reason
    return npos


def _wait_metrics(out: dict, daily: pd.DataFrame, breakout_pos: int,
                  fill_pos: int | None, end_pos: int,
                  breakout_close: float, fill_price: float | None) -> None:
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


def _harmonic_avg_cost(px_weights: list) -> float | None:
    """平均持仓成本（按资金比例投入）：Σw / Σ(w/P)，价格含买入滑点。"""
    if not px_weights:
        return None
    tw = sum(w for _, w in px_weights)
    denom = sum(w / px for px, w in px_weights if px > 0)
    return tw / denom if denom > 0 else None


def _nav_path_extremes(daily: pd.DataFrame, start_pos: int,
                       leg_bases: list, horizon: int = 20) -> tuple:
    """组合净值路径极值（分批专用口径，与全仓策略不可直接比较）。

    逐日价值 = 1（现金+面值），已成交批次替换为市值 w*C_j/base；
    未成交批次保持现金。返回 (max_ret, min_ret) 相对起点组合面值。
    """
    last = len(daily) - 1
    vals = []
    for j in range(start_pos, min(start_pos + horizon, last) + 1):
        v = 1.0
        for lp, base, w in leg_bases:
            if lp <= j and base > 0:
                v += w * (raw_price(daily, j) / base - 1.0)
        vals.append(v)
    return max(vals) - 1.0, min(vals) - 1.0


def _blank_row(code, lc, strategy) -> dict:
    out = {"code": code, "lifecycle_id": lc["lifecycle_id"],
           "strategy": strategy,
           "lifecycle_end_reason": lc["end_reason"],
           "right_censored": bool(lc["right_censored"]),
           "return_quality": RETURN_QUALITY, "limitation": LIMITATION}
    for c in ENTRY_REPLAY_COLUMNS:
        out.setdefault(c, None)
    out.update({"fill_status_close": "not_filled",
                "fill_status_next": "not_filled"})
    return out


def _first_shrink_day(pullback_daily, event_id, pos, end_pos) -> int | None:
    dd = pullback_daily[
        (pullback_daily["event_id"] == event_id)
        & (pullback_daily["shrink_volume"] == True)]  # noqa: E712
    days = [d for d in (pos.get(str(x)) for x in dd["date"])
            if d is not None and d <= end_pos]
    return min(days) if days else None


def _staged_legs_next(daily, market_cal, code, tspecs, cost,
                      out: dict) -> list:
    """按批次身份（t1/t2/t3）独立检查次日可成交性。

    逐批写入 {t}_next_status/date/price/reason；返回成功批次
    [(npos, price, weight)]（阻断批不进 next 组合）。
    """
    weights = {"t1": 0.30, "t2": 0.30, "t3": 0.40}
    ok = []
    for tag, tp in tspecs:
        if tp is None:
            continue
        npos, pr = _next_fill(daily, market_cal, code, tp, cost)
        if npos is None:
            out[f"{tag}_next_status"] = "not_filled"
            out[f"{tag}_next_reason"] = pr
        else:
            out[f"{tag}_next_status"] = "filled"
            out[f"{tag}_next_date"] = daily.index[npos].strftime("%Y-%m-%d")
            out[f"{tag}_next_price"] = pr
            ok.append((npos, pr, weights[tag]))
    return ok


def replay_entries(code: str, lifecycles: pd.DataFrame, daily: pd.DataFrame,
                   pullback_events: list, pullback_daily: pd.DataFrame,
                   cfg: ReplayConfig | None = None,
                   cost: CostModel | None = None,
                   market_cal: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """单股四策略回放：每 lifecycle×strategy 一行（无突破也输出四行）。"""
    cfg = cfg or ReplayConfig()
    cost = cost or CostModel()
    if market_cal is None:
        market_cal = daily.index
    pos = _pos_map(daily)
    last = len(daily) - 1
    rows: list[dict] = []
    for lc in (lifecycles.to_dict("records") if len(lifecycles) else []):
        for k in ("breakout_day", "reattack_days", "end_day", "anchor_day",
                  "reattack_pullback_event_ids"):
            lc[k] = lc[k] if isinstance(lc[k], str) else None
        for e in pullback_events:
            if not isinstance(e.get("stabilization_day"), str):
                e["stabilization_day"] = None
        bo = pos.get(lc["breakout_day"]) if lc["breakout_day"] else None
        end = pos.get(lc["end_day"]) if lc["end_day"] in pos else last

        # 本生命周期内的回调事件（first_day 晚于突破且不晚于 end），取最早
        pbs = sorted((e for e in pullback_events
                      if lc["breakout_day"] and
                      lc["breakout_day"] < e["first_day"] <= lc["end_day"]),
                     key=lambda x: x["first_day"])
        first_pb = pbs[0] if pbs else None
        shrink_pos = stab_pos = None
        if first_pb is not None:
            shrink_pos = _first_shrink_day(pullback_daily,
                                           first_pb["event_id"], pos, end)
            sd = first_pb.get("stabilization_day")
            sp = pos.get(sd) if sd else None
            stab_pos = sp if (sp is not None and sp <= end) else None

        bo_close = raw_price(daily, bo) if bo is not None else None
        prev_close = raw_price(daily, bo - 1) if bo and bo > 0 else None
        sig_gain = (bo_close / prev_close - 1.0) * 100.0 \
            if (bo_close and prev_close) else None

        for strategy in STRATEGIES:
            out = _blank_row(code, lc, strategy)
            out["anchor_day"] = lc["anchor_day"]
            out["signal_day"] = lc["breakout_day"]
            out["signal_day_gain_pct"] = sig_gain

            if bo is None:
                out["not_filled_reason_close"] = "no_breakout_signal"
                out["not_filled_reason_next"] = "no_breakout_signal"
                rows.append(out)
                continue

            if strategy == "direct_chase":
                out["capped_entered"] = not (sig_gain is not None
                                             and sig_gain > cfg.chase_gain_cap_pct)
                if not out["capped_entered"]:
                    out["capped_not_entered_reason"] = "chase_gain_cap_exceeded"
                out["fill_status_close"] = "filled"
                out["fill_date_close"] = lc["breakout_day"]
                out["fill_price_close"] = cost.fill_price(bo_close, "buy")
                npos = _next_view(out, daily, market_cal, code, bo, cost)
                _view_outcome(out, daily, "close", bo, cost,
                              out["fill_price_close"], bo_close)
                _view_outcome(out, daily, "next", npos, cost,
                              out.get("fill_price_next"), bo_close)

            elif strategy in ("wait_first_pullback", "wait_support_hold"):
                fpos = shrink_pos if strategy == "wait_first_pullback" else stab_pos
                if fpos is not None:
                    out["fill_status_close"] = "filled"
                    out["fill_date_close"] = daily.index[fpos].strftime("%Y-%m-%d")
                    out["fill_price_close"] = cost.fill_price(
                        raw_price(daily, fpos), "buy")
                    npos = _next_view(out, daily, market_cal, code, fpos, cost)
                    _view_outcome(out, daily, "close", fpos, cost,
                                  out["fill_price_close"], bo_close)
                    _view_outcome(out, daily, "next", npos, cost,
                                  out.get("fill_price_next"), bo_close)
                else:
                    reason = ("no_pullback_before_end" if first_pb is None
                              else ("no_shrink_day"
                                    if strategy == "wait_first_pullback"
                                    else "no_stabilization"))
                    out["not_filled_reason_close"] = reason
                    out["not_filled_reason_next"] = reason
                _wait_metrics(out, daily, bo, fpos, end, bo_close,
                              out.get("fill_price_close"))

            else:  # staged_entry
                t1p = bo
                t2p = shrink_pos
                # T3 = 第二批所选回调事件（突破后首次回调）配对的再上攻；
                # reattack_pullback_event_ids 与 reattack_days 一一同序。
                # 该回调无再上攻则第三批不成交，不得借用其他回调的再上攻。
                t3p = None
                if lc["reattack_days"] and first_pb is not None:
                    rdays = lc["reattack_days"].split("|")
                    rids = (lc["reattack_pullback_event_ids"] or "").split("|")
                    for rday, rid in zip(rdays, rids):
                        if rid == first_pb["event_id"]:
                            tp = pos.get(rday)
                            if tp is not None and tp <= end:
                                t3p = tp
                            break
                if t3p is not None and t2p is None:
                    t3p = None  # 第三批存在 ⇒ 第二批必须存在
                out["t1_fill_date"] = daily.index[t1p].strftime("%Y-%m-%d")
                out["t1_fill_price"] = cost.fill_price(raw_price(daily, t1p), "buy")
                legs = [(t1p, out["t1_fill_price"], 0.30)]
                if t2p is not None and t2p <= end:
                    out["t2_fill_date"] = daily.index[t2p].strftime("%Y-%m-%d")
                    out["t2_fill_price"] = cost.fill_price(
                        raw_price(daily, t2p), "buy")
                    legs.append((t2p, out["t2_fill_price"], 0.30))
                if t3p is not None:
                    out["t3_fill_date"] = daily.index[t3p].strftime("%Y-%m-%d")
                    out["t3_fill_price"] = cost.fill_price(
                        raw_price(daily, t3p), "buy")
                    legs.append((t3p, out["t3_fill_price"], 0.40))
                wsum = sum(w for _, _, w in legs)
                out["avg_cost"] = _harmonic_avg_cost(
                    [(px, w) for _, px, w in legs])
                out["max_position"] = wsum
                out["fraction_invested"] = wsum
                out["fill_status_close"] = "filled"
                out["fill_date_close"] = out["t1_fill_date"]
                out["fill_price_close"] = out["t1_fill_price"]

                # ---- close 视角组合：现金 + Σ 窗口内已成交批次 ----
                for h in HORIZONS:
                    wend = t1p + h
                    complete = wend <= last
                    out[f"outcome_{h}d_complete"] = complete
                    out[f"outcome_{h}d_observed"] = min(h, max(0, last - t1p))
                    if not complete:
                        out[f"ret_gross_{h}_close"] = None
                        out[f"ret_net_{h}_close"] = None
                        continue
                    # 现金基数 = 窗口内已成交批次之外的现金（窗口后才
                    # 成交的批次仍持币，收益 0）
                    legs_in = [(lp, lpx, lw) for lp, lpx, lw in legs
                               if lp <= wend]
                    cash = 1.0 - sum(lw for _, _, lw in legs_in)
                    sell_px = cost.fill_price(raw_price(daily, wend), "sell")
                    sell_day = daily.index[wend].date()
                    port_gross = cash
                    port_net = cash
                    end_close = raw_price(daily, wend)
                    for lp, lpx, lw in legs_in:
                        base = raw_price(daily, lp)
                        if base <= 0:
                            continue
                        port_gross += lw * (1.0 + end_close / base - 1.0)
                        net = _round_trip_net(cost, lpx, sell_px, sell_day,
                                              capital=CAPITAL * lw)
                        if net is not None:
                            port_net += lw * (1.0 + net)
                    out[f"ret_gross_{h}_close"] = (port_gross - 1.0) * 100.0
                    out[f"ret_net_{h}_close"] = (port_net - 1.0) * 100.0

                # ---- next 视角：每批独立判断次日可成交性；观察窗口起点
                # = 第一笔实际成功成交批次的次日成交日（T1 失败不丢弃后续） ----
                tspecs = [("t1", t1p), ("t2", t2p), ("t3", t3p)]
                ok_legs = _staged_legs_next(daily, market_cal, code, tspecs,
                                            cost, out)
                # next 视角实际仓位（收盘理论 vs 次日实际分开记录）
                wsum_n = sum(lw for _, _, lw in ok_legs)
                out["fraction_invested_next"] = wsum_n
                out["max_position_next"] = wsum_n
                out["avg_cost_next"] = _harmonic_avg_cost(
                    [(px, lw) for _, px, lw in ok_legs])
                if ok_legs:
                    npos_eff = min(np_ for np_, _, _ in ok_legs)
                    first_ok = next(x for x in ok_legs if x[0] == npos_eff)
                    out["fill_status_next"] = "filled"
                    out["fill_date_next"] = daily.index[npos_eff].strftime(
                        "%Y-%m-%d")
                    out["fill_price_next"] = first_ok[1]
                    for h in HORIZONS:
                        wend = npos_eff + h
                        out[f"outcome_{h}d_complete_next"] = wend <= last
                        out[f"outcome_{h}d_observed_next"] = min(
                            h, max(0, last - npos_eff))
                        if wend > last:
                            out[f"ret_gross_{h}_next"] = None
                            out[f"ret_net_{h}_next"] = None
                            continue
                        legs_in = [(np_, npx, lw) for np_, npx, lw in ok_legs
                                   if np_ <= wend]
                        cash = 1.0 - sum(lw for _, _, lw in legs_in)
                        port_gross = cash
                        port_net = cash
                        sell_px = cost.fill_price(raw_price(daily, wend), "sell")
                        sell_day = daily.index[wend].date()
                        end_close = raw_price(daily, wend)
                        for np_, npx, lw in legs_in:
                            base = raw_price(daily, np_, "open")  # 市场价口径
                            if base <= 0:
                                continue
                            port_gross += lw * (1.0 + end_close / base - 1.0)
                            net = _round_trip_net(cost, npx, sell_px, sell_day,
                                                  capital=CAPITAL * lw)
                            if net is not None:
                                port_net += lw * (1.0 + net)
                        out[f"ret_gross_{h}_next"] = (port_gross - 1.0) * 100.0
                        out[f"ret_net_{h}_next"] = (port_net - 1.0) * 100.0
                    # next 资金占用（窗口末=min(起点+20, 数据末)，非负）
                    wend20 = min(npos_eff + 20, last)
                    out["capital_position_days_next"] = sum(
                        lw * max(0, wend20 - np_)
                        for np_, _, lw in ok_legs)
                    # 组合净值路径 MFE/MAE（各批 next 开盘基准；分批专用口径）
                    nav_bases = [(np_, raw_price(daily, np_, "open"), lw)
                                 for np_, _, lw in ok_legs]
                    mfe, mae = _nav_path_extremes(daily, npos_eff, nav_bases)
                    out["mfe_20_next"] = mfe * 100.0
                    out["mae_20_next"] = mae * 100.0
                    if npos_eff + 20 <= last:
                        nh = next((j - npos_eff for j
                                   in range(npos_eff + 1, npos_eff + 20 + 1)
                                   if raw_price(daily, j) >= bo_close), None)
                        out["new_high_in_window_next"] = nh is not None
                        out["days_to_new_high_next"] = nh
                    if out.get("outcome_20d_complete_next") is False:
                        out["failure_path_next"] = "right_censored"
                    else:
                        n20 = out.get("ret_net_20_next")
                        out["failure_path_next"] = ("ok" if (n20 is not None
                                                             and n20 >= 0)
                                                    else "entry_poor") \
                            if n20 is not None else "trend_failed"
                else:
                    # 三批次日全部失败：整行未成交，原因取首批（主锚）
                    _, r1 = _next_fill(daily, market_cal, code, t1p, cost)
                    out["fill_status_next"] = "not_filled"
                    out["not_filled_reason_next"] = r1

                # ---- close 视角补充：MFE/MAE（组合净值路径口径，从 T1 日起）
                # + 新高 ----
                nav_bases_c = [(lp, raw_price(daily, lp), lw)
                               for lp, _, lw in legs]
                mfe, mae = _nav_path_extremes(daily, t1p, nav_bases_c)
                out["mfe_20_close"] = mfe * 100.0
                out["mae_20_close"] = mae * 100.0
                if t1p + 20 <= last:
                    nh = next((j - t1p for j
                               in range(t1p + 1, t1p + 20 + 1)
                               if raw_price(daily, j) >= bo_close), None)
                    out["new_high_in_window_close"] = nh is not None
                    out["days_to_new_high_close"] = nh
                # 各批次单独表现（close 视角）+ 资金占用（非负）
                for tag, (lp, lpx) in zip(
                        ("t1", "t2", "t3"),
                        [(t1p, out["t1_fill_price"]),
                         (t2p, out["t2_fill_price"]) if t2p is not None else (None, None),
                         (t3p, out["t3_fill_price"]) if t3p is not None else (None, None)]):
                    if lp is not None and lpx:
                        r = adjusted_return(daily, lp, lp + 20) \
                            if lp + 20 <= last else None
                        out[f"{tag}_ret_20"] = r * 100.0 if r is not None else None
                h20 = min(t1p + 20, last)
                out["capital_position_days"] = sum(
                    w * max(0, h20 - lp) for lp, _, w in legs)
                if out.get("outcome_20d_complete") is False:
                    out["failure_path_close"] = "right_censored"
                else:
                    c20 = out.get("ret_net_20_close")
                    out["failure_path_close"] = ("ok" if (c20 is not None
                                                          and c20 >= 0)
                                                 else "entry_poor") \
                        if c20 is not None else "trend_failed"
                out["outcome_complete"] = out.get("outcome_20d_complete")
                out["outcome_observed_days"] = out.get("outcome_20d_observed")
                _wait_metrics(out, daily, bo, t2p, end, bo_close, None)
            # 兼容主判列（非 staged 在 _view_outcome 内已写）
            if strategy != "staged_entry":
                out["outcome_complete"] = out.get("outcome_20d_complete")
                out["outcome_observed_days"] = out.get("outcome_20d_observed")
            rows.append(out)
    return pd.DataFrame(rows, columns=ENTRY_REPLAY_COLUMNS)
