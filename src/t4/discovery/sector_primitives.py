"""T4.4 Context Structure Discovery：sector primitives（LOO）与市场二维结构。

红线（继承 T4.1-T4.3）：
- sector membership 仍是 2026-09-21 快照 -> sector context 整族
  retrospective_context_only（价格计算 as-of <=T0，归类非时点）。
- LOO（leave-one-out）：事件挂载的 sector 聚合剔除 focal stock 本身，
  只用可分解统计量（count/sum），避免"股票自己突破抬高板块指标
  再反过来解释自己"的机械相关。
- Market 层用 T4.3 冻结的 as-of expanding percentile（breadth/new-high）。
"""
from __future__ import annotations

import sys
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))


def _gate_of(code6: str, gate_map: dict) -> str | None:
    for pfx in ("sh.", "sz."):
        g = gate_map.get(f"{pfx}{code6}")
        if g:
            return g
    return None


def build_sector_primitives(events: pd.DataFrame, lookback: int = 20,
                            min_hist: int = 20) -> pd.DataFrame:
    """事件级 sector context（LOO）+ market 对齐。

    输出（全部 as-of <=T0）：
    - sec_breadth_d5_loo / mkt_breadth_d5：5 日均上涨占比（LOO / 全市场）
    - sec_rel_breadth_d5 = 前者 − 后者
    - sec_nh_density_loo：板块内 20 日复权新高占比（当日，LOO）
    - sec_ret20_mean_loo / mkt_ret20_mean：等权**均值**收益 20 日复合
      （LOO 可分解口径；与 T4.1 中位口径的差异在 dictionary 披露）
    - sec_rel_strength20 = 前者 − 后者
    - 各自 as-of percentile（expanding，dates<T0，min 120）
    """
    from t4.context import build as tb
    smap = pd.read_parquet(ROOT / "output/research/t4/context/"
                           "stock_sector_map.parquet")
    gate_map = {c: g for c, g in zip(smap["code"], smap["industry_gate"])
                if pd.notna(g)}
    tb.set_stock_cache(ROOT / "data/adjustment_baostock/per_stock")

    # ---- 全市场逐日组件（用于 market 侧与板块侧） ----
    day_stats: dict[str, dict] = {}
    sec_day: dict[tuple[str, str], dict] = {}   # (date, gate) -> 组件
    stock_day: dict[tuple[str, str], tuple] = {}  # (code6, date) focal 值

    for code, dates, adj, pctchg, *_ in tb.iter_stock_daily_cached():
        code6 = code.split(".")[1]
        g = _gate_of(code6, gate_map)
        adj = np.asarray(adj, dtype=float)
        pch = np.asarray(pctchg, dtype=float)
        for i, d in enumerate(dates):
            up = bool(pch[i] > 0) if not np.isnan(pch[i]) else None
            # 20 日新高（复权 close 口径，与 T4.1 一致）
            lo = max(0, i - 20)
            win = adj[lo:i + 1]
            nh = None
            if len(win) == 21 and not np.isnan(win).any():
                nh = bool(adj[i] >= np.max(win[:-1]))
            r = float(np.log(adj[i] / adj[i - 1])) if (
                i > 0 and not np.isnan(adj[i]) and not np.isnan(adj[i - 1])
                and adj[i - 1] > 0) else None
            if up is None and nh is None and r is None:
                continue
            m = day_stats.setdefault(d, {"n": 0, "n_up": 0, "sum_r": 0.0,
                                         "nr": 0})
            if up is not None:
                m["n"] += 1
                m["n_up"] += int(up)
            if r is not None:
                m["sum_r"] += r
                m["nr"] += 1
            if g:
                s = sec_day.setdefault((d, g), {"n": 0, "n_up": 0,
                                                "n_nh": 0, "nnh": 0,
                                                "sum_r": 0.0, "nr": 0})
                if up is not None:
                    s["n"] += 1
                    s["n_up"] += int(up)
                if nh is not None:
                    s["nnh"] += 1
                    s["n_nh"] += int(nh)
                if r is not None:
                    s["sum_r"] += r
                    s["nr"] += 1
                stock_day[(code6, d)] = (up, nh, r)

    mdates = sorted(day_stats)
    mpos = {d: i for i, d in enumerate(mdates)}

    def mkt_series(key_num, key_den):
        num = np.array([day_stats[d][key_num] for d in mdates], float)
        den = np.array([day_stats[d][key_den] for d in mdates], float)
        return num, den

    mkt_up_n, mkt_n = mkt_series("n_up", "n")
    mkt_r_sum, mkt_nr = mkt_series("sum_r", "nr")
    mkt_breadth = mkt_up_n / np.maximum(mkt_n, 1)
    mkt_r20 = pd.Series(mkt_r_sum / np.maximum(mkt_nr, 1)).rolling(
        lookback).sum().to_numpy()

    # 事件挂载
    rows = []
    for r in events.itertuples(index=False):
        code6 = str(r.code).zfill(6)
        g = _gate_of(code6, gate_map)
        t0 = r.breakout_day
        i = mpos.get(t0)
        rec = {"breakout_event_id": r.breakout_event_id,
               "industry_gate": g, "breakout_day": t0}
        keys = ("sec_breadth_d5_loo", "sec_nh_density_loo",
                "sec_ret20_mean_loo", "sec_rel_breadth_d5",
                "sec_rel_strength20")
        if i is None or i < min_hist or g is None:
            for k in keys:
                rec[k] = None
            rec["mkt_breadth_d5"] = None
            rec["mkt_ret20_mean"] = None
            rec["loo_n"] = 0
            rows.append(rec)
            continue
        win = [mdates[j] for j in range(max(0, i - 4), i + 1)]
        # focal 值
        foc = {}
        for d in win:
            foc[d] = stock_day.get((code6, d), (None, None, None))
        # market 5 日 breadth（全市场，无 LOO）
        rec["mkt_breadth_d5"] = float(np.mean(
            [mkt_breadth[mpos[d]] for d in win if mpos.get(d) is not None]
            or [np.nan]))
        rec["mkt_ret20_mean"] = float(mkt_r20[i]) if np.isfinite(
            mkt_r20[i]) else None
        # sector LOO：窗内逐日 (n_up - up_focal)/(n - 1) 均值
        bs, nhs, rs = [], [], []
        n_loo = 99
        for d in win:
            s = sec_day.get((d, g))
            if not s or s["n"] < 2:
                continue
            up_f, nh_f, r_f = stock_day.get((code6, d), (None, None, None))
            if up_f is not None:
                bs.append((s["n_up"] - int(up_f)) / (s["n"] - 1))
            if s["nnh"] > 1 and nh_f is not None:
                nhs.append((s["n_nh"] - int(nh_f)) / (s["nnh"] - 1))
        # 20 日收益 LOO：sum over window of (sum_r - r_f)/(nr - 1)
        for d in [mdates[j] for j in range(max(0, i - lookback + 1), i + 1)]:
            s = sec_day.get((d, g))
            if not s or s["nr"] < 2:
                continue
            _, _, r_f = stock_day.get((code6, d), (None, None, None))
            rs.append((s["sum_r"] - (r_f or 0.0)) / (s["nr"] - 1))
        if bs:
            n_loo = min(n_loo, sec_day.get((t0, g), {}).get("n", 0))
        rec["sec_breadth_d5_loo"] = float(np.mean(bs)) if bs else None
        rec["sec_nh_density_loo"] = float(np.mean(nhs)) if nhs else None
        rec["sec_ret20_mean_loo"] = float(np.sum(rs)) if len(
            rs) >= min_hist else None
        rec["loo_n"] = int(n_loo) if n_loo < 99 else 0
        rec["sec_rel_breadth_d5"] = (
            rec["sec_breadth_d5_loo"] - rec["mkt_breadth_d5"]
            if rec["sec_breadth_d5_loo"] is not None
            and rec["mkt_breadth_d5"] is not None else None)
        rec["sec_rel_strength20"] = (
            rec["sec_ret20_mean_loo"] - rec["mkt_ret20_mean"]
            if rec["sec_ret20_mean_loo"] is not None
            and rec["mkt_ret20_mean"] is not None else None)
        rows.append(rec)
    return pd.DataFrame(rows)


def attach_asof_pct(sec: pd.DataFrame, cols: list[str],
                    min_history: int = 120) -> pd.DataFrame:
    """sector primitives 的 as-of expanding percentile（dates < T0，
    逐日板块值序列；跨板块 pooled——板块间相对位置也纳入 rank 语义，
    报告披露该口径）。"""
    sec = sec.sort_values("breakout_day").reset_index(drop=True)
    for c in cols:
        hist = []
        out = []
        vals = sec[c].to_numpy(float)
        days = sec["breakout_day"].to_numpy()
        gates = sec["industry_gate"].to_numpy(object)
        last_key = None
        h = []
        for v, d, g in zip(vals, days, gates):
            key = (d, g)
            if key != last_key:
                # 新 (日,板块)：昨日该板块的值进历史分布
                hist.extend(h)
                h = []
                last_key = key
            if len(hist) >= min_history and np.isfinite(v):
                hv = np.asarray(hist)
                out.append(float((hv < v).mean()))
            else:
                out.append(None)
            # 同 (日,板块) 只进历史一次：避免事件密度加权 rank 分布
            if np.isfinite(v) and not h:
                h.append(v)
        sec[f"{c}_asof_pct"] = out
    return sec
