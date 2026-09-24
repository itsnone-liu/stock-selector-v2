"""T5.1 独立结果表：未来收益/峰值/回撤/新高/失守（censor 显式）。

物理分离：本模块只被 runner 在 state 表构建之后调用；
primitives_build 不 import 本模块。
所有 horizon 按个股有效交易日计数（跳过停牌日）；
从 state_date 当日收盘之后（下一个有效日）开始；窗口不完整
不当作零收益，记 complete=False + n_obs。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from t5.schemas import OUTCOME_COLS

FWD_RET = (1, 3, 5, 10)
FWD_PATH = (5, 10)


def build_dynamic_outcomes(state_index: pd.DataFrame, stocks,
                           mdates) -> pd.DataFrame:
    """state_index: state 表 (event_id, code, breakout_day, delta_day,
    state_date, row_present) 列。stocks=iter_stock_full 生成器。"""
    per_code = {}
    for code_full, dates, adj, raw, *_ in stocks:
        code6 = (code_full.split(".")[1]
                 if "." in code_full else code_full)
        per_code[code6] = (dates, adj, raw)

    rows_out = []
    for (eid, code, t0), g in state_index.groupby(
            ["event_id", "code", "breakout_day"], sort=False):
        got = per_code.get(code)
        dates, adj, raw = got if got else ([], [], [])
        dpos = {d: i for i, d in enumerate(dates)}
        i0 = dpos.get(t0)
        adj0 = adj[i0] if i0 is not None else None
        if got is None or i0 is None or not adj0:
            # 无行情/T0 无复权：整事件输出空行（censor 语义，不丢键）
            for r in g.itertuples(index=False):
                rows_out.append(_empty(eid, r.delta_day))
            continue
        # T0 之后有效日序列（固定）
        post = [(dates[i], adj[i], raw[i])
                for i in range(i0 + 1, len(dates))
                if adj[i] is not None]
        prior_d = [d for d in dates[:i0]]
        ref20 = max((raw[dates.index(d)] for d in prior_d[-20:]),
                    default=None) if len(prior_d) >= 20 else None

        g = g.sort_values("delta_day")
        fut_start = 0
        prior_peak = adj0          # 截至上一有效日的运行峰值（含 T0）
        for r in g.itertuples(index=False):
            j = dpos.get(r.state_date)
            a_t = adj[j] if (j is not None and r.row_present) else None
            if a_t is None:
                rows_out.append(_empty(eid, r.delta_day))
                continue
            # 游标推进：post 中 <= state_date 的日并入运行峰值
            while (fut_start < len(post)
                   and post[fut_start][0] <= r.state_date):
                prior_peak = max(prior_peak, post[fut_start][1])
                fut_start += 1
            base = a_t
            peak_t = prior_peak    # 含当日
            row = {"event_id": eid, "delta_day": r.delta_day}
            for h in FWD_RET:
                if len(post) - fut_start >= h:
                    row[f"fwd_ret_{h}d_log"] = float(
                        np.log(post[fut_start + h - 1][1] / base))
                    row[f"complete_{h}d"] = True
                else:
                    row[f"fwd_ret_{h}d_log"] = None
                    row[f"complete_{h}d"] = False
                row[f"n_obs_{h}d"] = min(len(post) - fut_start, h)
            for h in FWD_PATH:
                w = post[fut_start:fut_start + h]
                if len(w) >= h:
                    rets = [float(np.log(a / base)) for _, a, _ in w]
                    row[f"complete_path_{h}d"] = True
                    row[f"fwd_peak_ret_{h}d_log"] = max(rets)
                    runmax, mdd = -np.inf, 0.0
                    for x in rets:
                        runmax = max(runmax, x)
                        mdd = max(mdd, runmax - x)
                    row[f"fwd_mdd_{h}d_log"] = float(mdd)
                    row[f"fwd_new_high_{h}d"] = bool(
                        any(a > peak_t for _, a, _ in w))
                    row[f"fwd_lose_ref20_{h}d"] = (
                        bool(any(rw < ref20 for _, _, rw in w))
                        if ref20 else None)
                else:
                    row[f"complete_path_{h}d"] = False
                    row[f"fwd_peak_ret_{h}d_log"] = None
                    row[f"fwd_mdd_{h}d_log"] = None
                    row[f"fwd_new_high_{h}d"] = None
                    row[f"fwd_lose_ref20_{h}d"] = None
            rows_out.append(row)
    return pd.DataFrame(rows_out, columns=OUTCOME_COLS)


def _empty(eid, delta):
    r = {"event_id": eid, "delta_day": delta}
    for h in FWD_RET:
        r[f"fwd_ret_{h}d_log"] = None
        r[f"complete_{h}d"] = False
        r[f"n_obs_{h}d"] = 0
    for h in FWD_PATH:
        r[f"complete_path_{h}d"] = False
        r[f"fwd_peak_ret_{h}d_log"] = None
        r[f"fwd_mdd_{h}d_log"] = None
        r[f"fwd_new_high_{h}d"] = None
        r[f"fwd_lose_ref20_{h}d"] = None
    return r
