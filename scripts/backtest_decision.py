"""决策层新口径回测（研究脚本，非生产规则）。

三块评估，全部 PIT（特征只用 ≤t 数据）：
A. 日线买点多标签：三条件独立判定 + 组合 + 旧elif首中分类对照，
   前向收益按 1/3/5/10 日（信号收盘计）与次日开盘入场两种口径，
   并按大盘 regime 分层；
B. 周级动能模式对照：revised_weekday vs unified，周五收盘状态 → 次周收益；
C. 退出规则模拟：E1/E2/E3/E5，触发≠成交（收盘确认→次日开盘成交；
   盘中触发→当日按 stop/开盘孰低成交）。

已知局限（写进报告）：
- 幸存者偏差：universe 为当前上市股票；
- 不含交易成本；
- 盘中L1量能折算未校准（等分钟数据），本评估为 EOD 口径；
- 结论不直接晋升生产规则（需样本外）。

用法：
PYTHONPATH=src python3 scripts/backtest_decision.py \
  --start 2024-09-01 --end 2026-09-15 --out output/research/decision_eval
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from stock_selector.config import load_config
from stock_selector.data.tdx import TdxStore
from stock_selector.data.tdx_index import index_daily
from stock_selector.decision.labels import daily_labels
from stock_selector.decision.replay import truncate_daily
from stock_selector.decision.weekly_momentum import weekly_momentum
from stock_selector.indicators import macd

LABELS = ("pullback_holds", "shrinking_volume_acceleration", "two_day_acceleration")
LABEL_SHORT = {"pullback_holds": "PB", "shrinking_volume_acceleration": "SV", "two_day_acceleration": "TD"}
HORIZONS = (1, 3, 5, 10)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=None)
    p.add_argument("--phase", default="all", choices=("all", "labels", "weekly", "exits"),
                   help="分阶段执行（内存受限机器）；labels 结果落盘后可单跑 weekly/exits")
    p.add_argument("--start", default="2024-09-01")
    p.add_argument("--end", default="2026-09-15")
    p.add_argument("--min-amount", type=float, default=2e7, help="120日成交额中位数下限（元）")
    p.add_argument("--sample-labels", type=int, default=1200)
    p.add_argument("--sample-weekly", type=int, default=300)
    p.add_argument("--sample-entries", type=int, default=20000)
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--out", default="output/research/decision_eval")
    return p


def causal_features(frame: pd.DataFrame, cfg: dict) -> pd.DataFrame | None:
    """向量化的因果特征（与 decision/labels.py EOD 语义一致）。"""
    if len(frame) < 80:
        return None
    close, open_ = frame["close"], frame["open"]
    vol = frame["volume"]
    dc = (close / close.shift(1) - 1.0) * 100
    yc = dc.shift(1)
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    near10 = (close - ma10).abs() / ma10 <= float(cfg["buy"].get("ma_tolerance_pct", 1.0)) / 100.0
    near20 = (close - ma20).abs() / ma20 <= float(cfg["buy"].get("ma_tolerance_pct", 1.0)) / 100.0
    vr = vol / vol.shift(1)
    maximum = float(cfg["buy"].get("acceleration_max_change_pct", 3.5))
    pmin = float(cfg["buy"].get("pullback_change_min_pct", -3.0))
    pmax = float(cfg["buy"].get("pullback_change_max_pct", 2.0))
    y_bull = close.shift(1) > open_.shift(1)
    out = pd.DataFrame(index=frame.index)
    out["dc"], out["yc"], out["vr"] = dc, yc, vr
    out["pullback_holds"] = (dc >= pmin) & (dc <= pmax) & (near10 | near20)
    out["shrinking_volume_acceleration"] = (dc > 0) & (dc > yc) & (dc < maximum) & (vr < 1)
    out["two_day_acceleration"] = y_bull & (dc > 0) & (dc >= yc) & (dc < maximum)
    # 旧 elif 首中分类
    primary = pd.Series("", index=frame.index)
    for name in LABELS:
        primary = primary.mask((primary == "") & out[name], name)
    out["primary"] = primary
    return out


def regime_series(index_frame: pd.DataFrame) -> pd.Series:
    close = index_frame["close"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    r = pd.Series("mid", index=index_frame.index)
    r[(close > ma20) & (close > ma60)] = "bull"
    r[(close < ma20) & (close < ma60)] = "weak"
    r[ma20.isna() | ma60.isna()] = None
    return r


def stream_qualified_codes(store: TdxStore, codes: list[str], min_amount: float,
                           yield_frames: bool = False):
    """流式过滤合格股票：一次只持有一帧（内存受限机器）。"""
    for code in codes:
        f = store.daily(code)
        if f is None or len(f) < 160:
            continue
        recent = f["amount"].iloc[-120:]
        if len(recent) < 60 or recent.median() < min_amount:
            continue
        yield (code, f) if yield_frames else code


def evaluate_exits_streaming(store: TdxStore, codes: list[str], cfg: dict,
                             start: str, end: str, min_amount: float,
                             rng: np.random.Generator, sample: int, out_dir: Path) -> None:
    """流式退出模拟：不缓存帧，逐股票算标签→模拟→丢弃。"""
    rules = ("E1_close", "E1_intraday", "E2_fixed5", "E3_trail8", "E5_combo")
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    records = []
    trail_pct = float(cfg["decision"]["exits"]["trail_pct"]) / 100.0
    time_stop = int(cfg["decision"]["exits"]["time_stop_days"])
    max_hold = int(cfg["decision"]["exits"]["max_hold_days"])
    n_stocks = 0
    for code, f in stream_qualified_codes(store, codes, min_amount, yield_frames=True):
        n_stocks += 1
        feat = causal_features(f, cfg)
        if feat is None:
            continue
        feat = feat.loc[(feat.index >= start_ts) & (feat.index <= end_ts)]
        if feat.empty or not feat[list(LABELS)].any(axis=1).any():
            continue
        o = f["open"].to_numpy(float); h = f["high"].to_numpy(float)
        low = f["low"].to_numpy(float); c = f["close"].to_numpy(float)
        dates = f.index
        for day, row in feat[feat[list(LABELS)].any(axis=1)].iterrows():
            i0 = int(dates.get_indexer([day])[0])
            if i0 < 0:
                continue
            stop = float(low[i0])
            labels_hit = "+".join(LABEL_SHORT[k] for k in LABELS if row[k])
            for rule in rules:
                res = simulate_exit(o, h, low, c, i0, stop, rule,
                                    trail_pct=trail_pct, time_stop=time_stop, max_hold=max_hold)
                if res is None:
                    continue
                ret, held = res
                records.append({"code": code, "day": str(day.date()), "rule": rule,
                                "labels": labels_hit, "ret_pct": round(ret, 3), "hold_days": held})
        if n_stocks % 500 == 0:
            print(f"  exits streaming: {n_stocks} stocks, {len(records)} records")
    df = pd.DataFrame(records)
    if df.empty:
        print("  exits: no records")
        return
    if len(df) > sample * 5:
        df = df.sample(n=sample * 5, random_state=int(rng.integers(1 << 30)))
    df.to_csv(out_dir / "exit_trades.csv", index=False, encoding="utf-8-sig")
    summary = df.groupby("rule")["ret_pct"].agg(
        n="size", mean="mean", median="median",
        win=lambda s: (s > 0).mean()).round(3)
    summary["avg_hold_days"] = df.groupby("rule")["hold_days"].mean().round(2)
    summary.to_csv(out_dir / "exit_summary.csv", encoding="utf-8-sig")
    by_labels = df.groupby(["rule", "labels"])["ret_pct"].agg(n="size", mean="mean", win=lambda s: (s > 0).mean()).round(3)
    by_labels.to_csv(out_dir / "exit_by_labels.csv", encoding="utf-8-sig")


def main() -> None:
    args = build_parser().parse_args()
    cfg = load_config(args.config)
    store = TdxStore(cfg["paths"]["tdx_dir"])
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    print("[1/5] loading universe ...")
    codes = store.list_codes()
    if args.phase in ("labels", "all"):
        frames = dict(stream_qualified_codes(store, codes, args.min_amount, yield_frames=True))
        print(f"  universe: {len(frames)} stocks (amount>={args.min_amount:.0f})")
        idx = index_daily(cfg["paths"]["tdx_dir"], cfg["decision"]["index"]["market"], str(cfg["decision"]["index"]["code"]))
        print(f"  index rows: {len(idx)}")

        print("[2/5] label panel + consistency check ...")
        panel, hit = evaluate_labels(frames, cfg, idx, args.start, args.end, rng, args.sample_labels, out_dir)
        stats = json.loads((out_dir / "label_stats.json").read_text(encoding="utf-8"))
        print(f"  consistency vs daily_labels: {stats['consistency_vs_daily_labels']:.3f} on {len(frames)} stocks")
        frames.clear()  # 释放内存
    else:
        hit = pd.read_csv(out_dir / "label_signals.csv", index_col=0) if (out_dir / "label_signals.csv").exists() else pd.DataFrame()

    if args.phase in ("weekly", "all"):
        print("[3/5] weekly momentum modes ...")
        evaluate_weekly_modes_streaming(store, codes, cfg, args.start, args.end, args.min_amount,
                                        rng, args.sample_weekly, out_dir)

    if args.phase in ("exits", "all"):
        print("[4/5] exit simulation (streaming) ...")
        evaluate_exits_streaming(store, codes, cfg, args.start, args.end, args.min_amount,
                                 rng, args.sample_entries, out_dir)

    print("[5/5] done ->", out_dir)


def evaluate_labels(frames: dict[str, pd.DataFrame], cfg: dict, index_frame: pd.DataFrame,
                    start: str, end: str, rng: np.random.Generator,
                    sample: int, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    regime = regime_series(index_frame)
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    for code, f in frames.items():
        feat = causal_features(f, cfg)
        if feat is None:
            continue
        feat = feat.loc[(feat.index >= start_ts) & (feat.index <= end_ts)]
        if feat.empty:
            continue
        close = f["close"].reindex(feat.index)
        open_ = f["open"].reindex(feat.index)
        for h in HORIZONS:
            feat[f"fwd{h}"] = (close.shift(-h) / close - 1.0) * 100
        feat["fwd5_open_entry"] = (close.shift(-5) / open_.shift(-1) - 1.0) * 100
        feat["regime"] = regime.reindex(feat.index).values
        feat["code"] = code
        rows.append(feat)
    panel = pd.concat(rows)
    # 一致性校验：随机抽点与原实现比对
    checks = []
    check_idx = rng.choice(len(panel), size=min(80, len(panel)), replace=False)
    sample_codes = panel["code"].unique()
    cache = {c: frames[c] for c in sample_codes}
    for i in check_idx:
        row = panel.iloc[i]
        code, day = row["code"], row.name
        trunc = truncate_daily(cache[code], datetime(day.year, day.month, day.day, 15, 10))
        ref = daily_labels(trunc, datetime(day.year, day.month, day.day, 15, 10), cfg)
        mine = {k: bool(row[k]) for k in LABELS}
        checks.append(all(mine[k] == bool(ref.labels[k]) for k in LABELS))
    consistency = float(np.mean(checks)) if checks else float("nan")

    hit = panel[panel[list(LABELS)].any(axis=1)].copy()
    if len(hit) > sample:
        hit = hit.sample(n=sample, random_state=int(rng.integers(1 << 30)))
    hit.to_csv(out_dir / "label_signals.csv", index=True, encoding="utf-8-sig")

    def _table(df: pd.DataFrame, key: str) -> pd.DataFrame:
        g = df.groupby(key)
        t = pd.DataFrame({
            "n": g.size(),
            "fwd1": g["fwd1"].mean(), "fwd3": g["fwd3"].mean(),
            "fwd5": g["fwd5"].mean(), "fwd10": g["fwd10"].mean(),
            "win5": g["fwd5"].apply(lambda s: (s > 0).mean()),
            "open_entry_fwd5": g["fwd5_open_entry"].mean(),
        })
        return t.round(3)

    # 独立标签（允许多标签）
    indep = []
    for name in LABELS:
        sub = panel[panel[name]]
        if len(sub):
            indep.append(_table(sub.assign(k=name), "k"))
    indep = pd.concat(indep) if indep else pd.DataFrame()

    # 组合
    def combo_key(row) -> str:
        return "+".join(LABEL_SHORT[k] for k in LABELS if row[k]) or "none"
    panel["_combo"] = panel.apply(combo_key, axis=1)
    combos = _table(panel[panel[list(LABELS)].any(axis=1)], "_combo")

    # 旧 elif 首中（分配偏差对照）
    primary = _table(panel[panel["primary"] != ""], "primary")

    # regime 分层（任意标签命中）
    by_regime = _table(panel[panel[list(LABELS)].any(axis=1)], "regime")

    # 标签 × regime
    cross = []
    for name in LABELS:
        sub = panel[panel[name] & panel["regime"].notna()]
        if len(sub):
            cross.append(_table(sub.assign(k=name), ["k", "regime"]))
    cross = pd.concat(cross) if cross else pd.DataFrame()

    for name, df in (("labels_independent", indep), ("label_combos", combos),
                     ("old_elif_primary", primary), ("any_label_by_regime", by_regime),
                     ("label_x_regime", cross)):
        if len(df):
            df.to_csv(out_dir / f"{name}.csv", encoding="utf-8-sig")
    panel_stats = {
        "stocks": len(frames), "signal_days_total": int(panel[list(LABELS)].any(axis=1).sum()),
        "signal_days_sampled": len(hit), "consistency_vs_daily_labels": consistency,
    }
    (out_dir / "label_stats.json").write_text(json.dumps(panel_stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return panel, hit


def evaluate_weekly_modes_streaming(store: TdxStore, codes: list[str], cfg: dict,
                                    start: str, end: str, min_amount: float,
                                    rng: np.random.Generator,
                                    sample: int, out_dir: Path) -> None:
    qualified = list(stream_qualified_codes(store, codes, min_amount))
    print(f"  qualified: {len(qualified)} stocks")
    if len(qualified) > sample:
        idx = rng.choice(len(qualified), size=sample, replace=False)
        chosen = [qualified[i] for i in idx]
    else:
        chosen = qualified
    fridays = pd.date_range(start=start, end=end, freq="W-FRI")
    rows = []
    for n, code in enumerate(chosen):
        f = store.daily(code)
        if f is None:
            continue
        close = f["close"]
        for fri in fridays:
            if pd.Timestamp(f.index[-1]) < fri:
                continue
            asof = datetime(fri.year, fri.month, fri.day, 15, 10)
            trunc = truncate_daily(f, asof)
            if trunc is None or len(trunc) < 80:
                continue
            fwd = None
            later = close[close.index > fri]
            if len(later) >= 5:
                fwd = (later.iloc[4] / trunc["close"].iloc[-1] - 1.0) * 100
            for mode in ("revised_weekday", "unified"):
                try:
                    res = weekly_momentum(trunc, asof, cfg, mode=mode)
                except Exception:
                    continue
                rows.append({"code": code, "week": str(fri.date()), "mode": mode,
                             "state": res.state, "origin": res.evidence_origin,
                             "fwd_week_pct": fwd})
        if (n + 1) % 25 == 0:
            print(f"  weekly modes: {n + 1}/{len(chosen)} stocks")
    frame = pd.DataFrame(rows)
    frame.to_csv(out_dir / "weekly_mode_states.csv", index=False, encoding="utf-8-sig")
    have = frame.dropna(subset=["fwd_week_pct"])
    summary = []
    for mode, grp in have.groupby("mode"):
        for state, g in grp.groupby("state"):
            summary.append({"mode": mode, "state": state, "n": len(g),
                            "fwd_week_mean": round(g["fwd_week_pct"].mean(), 3),
                            "fwd_week_median": round(g["fwd_week_pct"].median(), 3),
                            "win": round((g["fwd_week_pct"] > 0).mean(), 3)})
    pd.DataFrame(summary).to_csv(out_dir / "weekly_mode_summary.csv", index=False, encoding="utf-8-sig")
    pivot = have.pivot_table(index=["code", "week"], columns="mode", values="state", aggfunc="first")
    if {"revised_weekday", "unified"}.issubset(pivot.columns):
        agree = pd.crosstab(pivot["revised_weekday"], pivot["unified"])
        agree.to_csv(out_dir / "weekly_mode_agreement.csv", encoding="utf-8-sig")


def simulate_exit(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  i0: int, stop: float, rule: str, trail_pct: float = 0.08,
                  time_stop: int = 5, max_hold: int = 20) -> tuple[float, int] | None:
    """i0=信号日；次日开盘买入。返回 (收益%, 持有交易日) 或 None（无法成交）。"""
    n = len(close)
    e = i0 + 1
    if e >= n:
        return None
    entry = open_[e]
    if not np.isfinite(entry) or entry <= 0:
        return None
    peak = entry
    d = e
    while d < n - 1 and (d - e) < max_hold + 1:
        c = close[d]
        peak = max(peak, c)
        if rule == "E1_close":
            if c < stop and d > e:
                nxt = open_[d + 1]
                return ((nxt / entry - 1) * 100 if np.isfinite(nxt) else (c / entry - 1) * 100), d - e
        elif rule == "E1_intraday":
            if d > e and low[d] <= stop:
                fill = min(open_[d], stop) if open_[d] > stop else open_[d]
                return (fill / entry - 1) * 100, d - e
        elif rule == "E3_trail8":
            if c < peak * (1 - trail_pct) and d > e:
                nxt = open_[d + 1]
                return ((nxt / entry - 1) * 100 if np.isfinite(nxt) else (c / entry - 1) * 100), d - e
        elif rule == "E2_fixed5":
            if (d - e) >= time_stop:
                return (c / entry - 1) * 100, d - e
        elif rule == "E5_combo":
            trig = (c < stop) or (c < peak * (1 - trail_pct))
            if trig and d > e:
                nxt = open_[d + 1]
                return ((nxt / entry - 1) * 100 if np.isfinite(nxt) else (c / entry - 1) * 100), d - e
        d += 1
    c = close[min(d, n - 1)]
    return (c / entry - 1) * 100, max(d - e, 1)

