#!/usr/bin/env python3
"""滚动窗口 + 样本外验证框架（研究用，无成本模型）。

裁决 2026-09-15 单窗口回测的两个存疑结论：
  R1 regime 反转（weak 档前瞻收益最好是否窗口依赖）
  R2 base_scores 权重依据失效（特征-收益关系是否稳定）
附带：标签组合（R3）与退出规则（R4）的跨窗口稳定性。

方法纪律：
  - 评估窗：2021-12 起每 6 个月一个非重叠窗口（最后一窗到数据尾）；
  - walk-forward：结论在窗口 i 成立与否，用窗口 i+1 复制率衡量（绝不自证）；
  - 特征分位桶：边界只用估计期（2021-12..2022-12）数据定，后续窗口为样本外；
  - 流式两遍扫描（一遍定边，一遍积累），单帧内存，适配 4GB 机器。

用法：
  PYTHONPATH=src python3 scripts/rolling_validation.py [--sample 1500] [--phases all]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_decision import LABELS, causal_features, regime_series, stream_qualified_codes  # noqa: E402
from stock_selector.config import load_config  # noqa: E402
from stock_selector.data.tdx import TdxStore  # noqa: E402
from stock_selector.data.tdx_index import index_daily  # noqa: E402

EST_START, EST_END = "2021-12-01", "2022-12-01"   # 估计期（定分位边）
DATA_START = "2021-12-01"                          # 评估窗起点（60bar热身后）
FEATURES = ("mom20", "mom60", "vr20", "malignment")


def half_year_windows(end: str) -> list[tuple[str, str]]:
    wins, y, m = [], 2021, 12
    while True:
        ny, nm = (y + 1, 6) if m == 12 else (y, m + 6)
        s, e = f"{y}-{m:02d}-01", f"{ny}-{nm:02d}-01"
        if pd.Timestamp(s) >= pd.Timestamp(end):
            break
        if pd.Timestamp(e) > pd.Timestamp(end):
            e = end
        wins.append((s, e))
        y, m = ny, nm
    return wins


def window_of(date) -> int | None:
    ts = pd.Timestamp(date)
    for i, (s, e) in enumerate(WINDOWS):
        if pd.Timestamp(s) <= ts < pd.Timestamp(e):
            return i
    return None


def extra_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"]
    mom20 = close / close.shift(20) - 1
    mom60 = close / close.shift(60) - 1
    vr20 = frame["volume"] / frame["volume"].rolling(20).mean()
    ma5 = close.rolling(5).mean(); ma10 = close.rolling(10).mean(); ma20 = close.rolling(20).mean()
    malignment = ((ma5 > ma10).astype(int) + (ma10 > ma20).astype(int) + (close > ma20).astype(int)) / 3.0
    return pd.DataFrame({"mom20": mom20, "mom60": mom60, "vr20": vr20, "malignment": malignment},
                        index=frame.index)


def pass1_edges(store, codes, cfg, min_amount, sample_codes) -> dict[str, tuple]:
    """估计期内收集特征值 → 三分位边界（样本外纪律：只看估计期）。"""
    vals = {k: [] for k in FEATURES}
    for code, f in stream_qualified_codes(store, sample_codes, min_amount, yield_frames=True):
        if code not in sample_codes_set:
            continue
        ef = extra_features(f)
        m = (ef.index >= pd.Timestamp(EST_START)) & (ef.index < pd.Timestamp(EST_END))
        for k in FEATURES:
            v = ef.loc[m, k].dropna().to_numpy()
            if len(v):
                vals[k].append(v)
    edges = {}
    for k, chunks in vals.items():
        arr = np.concatenate(chunks)
        edges[k] = tuple(float(x) for x in np.quantile(arr, (1/3, 2/3)))
        print(f"  edges[{k}] tercile: {edges[k][0]:.4f} / {edges[k][1]:.4f}  (n={len(arr)})")
    return edges


def main() -> None:
    global WINDOWS
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=None)
    p.add_argument("--sample", type=int, default=1500)
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--min-amount", type=float, default=2e7)
    p.add_argument("--out", default="output/research/rolling")
    args = p.parse_args()

    cfg = load_config(args.config)
    store = TdxStore(cfg["paths"]["tdx_dir"])
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    end = "2026-09-16"
    WINDOWS = half_year_windows(end)
    print(f"评估窗 {len(WINDOWS)} 个: {WINDOWS[0][0]} .. {WINDOWS[-1][1]}")

    index_frame = index_daily(cfg["paths"]["tdx_dir"], "sh", "000001")
    reg = regime_series(index_frame)                      # date → bull/mid/weak
    regime_days = reg.loc[reg.index >= pd.Timestamp(DATA_START)]
    win_regime_days = defaultdict(lambda: defaultdict(int))
    for d, t in regime_days.items():
        wi = window_of(d)
        if wi is not None and t:
            win_regime_days[wi][t] += 1
    pd.DataFrame([{"window": f"W{i} {s[:7]}-{e[:7]}", **dict(win_regime_days.get(i, {}))}
                  for i, (s, e) in enumerate(WINDOWS)]
                 ).to_csv(out_dir / "window_regime_days.csv", index=False, encoding="utf-8-sig")

    all_codes = sorted(store.list_codes())
    rng = np.random.default_rng(args.seed)
    sample_codes = set(all_codes if len(all_codes) <= args.sample
                       else rng.choice(all_codes, size=args.sample, replace=False).tolist())
    global sample_codes_set
    sample_codes_set = sample_codes
    print(f"样本 {len(sample_codes)} / 全市场 {len(all_codes)}（seed={args.seed}）")

    # ---- pass 1：估计期分位边 ----
    edges = pass1_edges(store, all_codes, cfg, args.min_amount, sorted(sample_codes))

    # ---- pass 2：流式积累 ----
    from backtest_decision import simulate_exit
    trail_pct = float(cfg["decision"]["exits"]["trail_pct"]) / 100.0
    time_stop = int(cfg["decision"]["exits"]["time_stop_days"])
    max_hold = int(cfg["decision"]["exits"]["max_hold_days"])
    rules = ("E1_close", "E1_intraday", "E2_fixed5", "E3_trail8", "E5_combo")

    # key → [n, sum5, win5, sum10, win10]；exits key → [n, sum, win, holdsum]
    acc_regime = defaultdict(lambda: [0, 0.0, 0, 0.0, 0])
    acc_label = defaultdict(lambda: [0, 0.0, 0])
    acc_feat = defaultdict(lambda: [0, 0.0, 0])
    acc_exit = defaultdict(lambda: [0, 0.0, 0, 0.0])
    stocks_per_win = defaultdict(set)

    start_ts = pd.Timestamp(DATA_START)
    for n_done, (code, f) in enumerate(stream_qualified_codes(store, sorted(sample_codes),
                                                              args.min_amount, yield_frames=True), 1):
        feat = causal_features(f, cfg)
        if feat is None:
            continue
        ef = extra_features(f)
        m = feat.index >= start_ts
        feat, ef = feat[m], ef[m]
        if feat.empty:
            continue
        close = f["close"]
        fwd5 = (close.shift(-5) / close - 1).reindex(feat.index) * 100
        fwd10 = (close.shift(-10) / close - 1).reindex(feat.index) * 100
        reg_al = reg.reindex(f.index).reindex(feat.index)  # 交易日对齐
        wins_idx = [window_of(d) for d in feat.index]

        o = f["open"].to_numpy(float); h = f["high"].to_numpy(float)
        lo = f["low"].to_numpy(float); c = f["close"].to_numpy(float)
        dates = f.index

        for pos, (day, row) in enumerate(feat.iterrows()):
            wi = wins_idx[pos]
            if wi is None:
                continue
            stocks_per_win[wi].add(code)
            tier = reg_al.iloc[pos]
            if isinstance(tier, str):
                a = acc_regime[(wi, tier)]
                a[0] += 1
                if not np.isnan(fwd5.iloc[pos]):
                    a[1] += fwd5.iloc[pos]; a[2] += fwd5.iloc[pos] > 0
                if not np.isnan(fwd10.iloc[pos]):
                    a[3] += fwd10.iloc[pos]; a[4] += fwd10.iloc[pos] > 0
            hits = [k for k in LABELS if row[k]]
            key = "+".join(hits) if hits else "baseline"
            b = acc_label[(wi, key)]
            b[0] += 1
            if not np.isnan(fwd5.iloc[pos]):
                b[1] += fwd5.iloc[pos]; b[2] += fwd5.iloc[pos] > 0
            for k in FEATURES:
                v = ef[k].iloc[pos]
                if np.isnan(v):
                    continue
                t = 2 if v > edges[k][1] else (0 if v < edges[k][0] else 1)
                g = acc_feat[(wi, k, t)]
                g[0] += 1
                if not np.isnan(fwd5.iloc[pos]):
                    g[1] += fwd5.iloc[pos]; g[2] += fwd5.iloc[pos] > 0
            if hits:
                i0 = int(dates.get_indexer([day])[0])
                if i0 >= 0:
                    stop = float(lo[i0])
                    for rule in rules:
                        res = simulate_exit(o, h, lo, c, i0, stop, rule,
                                            trail_pct=trail_pct, time_stop=time_stop, max_hold=max_hold)
                        if res is None:
                            continue
                        ret, held = res
                        x = acc_exit[(wi, rule)]
                        x[0] += 1; x[1] += ret; x[2] += ret > 0; x[3] += held
        if n_done % 200 == 0:
            print(f"  pass2: {n_done}/{len(sample_codes)} stocks")

    wlab = [f"W{i} {s[:7]}-{e[:7]}" for i, (s, e) in enumerate(WINDOWS)]

    def win_label(i):
        return wlab[i]

    df = pd.DataFrame([{"window": win_label(wi), "tier": tier, "n": a[0],
                        "fwd5_mean": a[1] / a[0], "fwd5_win": a[2] / max(a[0], 1),
                        "fwd10_mean": a[3] / a[0], "fwd10_win": a[4] / max(a[0], 1)}
                       for (wi, tier), a in sorted(acc_regime.items())])
    df.to_csv(out_dir / "regime_by_window.csv", index=False, encoding="utf-8-sig")

    dl = pd.DataFrame([{"window": win_label(wi), "combo": combo, "n": a[0],
                        "fwd5_mean": a[1] / max(a[0], 1), "fwd5_win": a[2] / max(a[0], 1)}
                       for (wi, combo), a in sorted(acc_label.items())])
    dl.to_csv(out_dir / "labels_by_window.csv", index=False, encoding="utf-8-sig")

    dfe = pd.DataFrame([{"window": win_label(wi), "feature": feat, "tercile": t,
                         "n": a[0], "fwd5_mean": a[1] / max(a[0], 1),
                         "fwd5_win": a[2] / max(a[0], 1)}
                        for (wi, feat, t), a in sorted(acc_feat.items())])
    dfe.to_csv(out_dir / "feature_terciles_by_window.csv", index=False, encoding="utf-8-sig")

    dx = pd.DataFrame([{"window": win_label(wi), "rule": rule, "n": a[0],
                        "ret_mean": a[1] / a[0], "win": a[2] / a[0],
                        "avg_hold": a[3] / a[0]}
                       for (wi, rule), a in sorted(acc_exit.items())])
    dx.to_csv(out_dir / "exits_by_window.csv", index=False, encoding="utf-8-sig")

    pd.Series({f"W{i}": len(s) for i, s in stocks_per_win.items()}).to_csv(
        out_dir / "stocks_per_window.csv", encoding="utf-8-sig")
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
