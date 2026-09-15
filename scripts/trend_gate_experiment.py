#!/usr/bin/env python3
"""周趋势硬门槛裁决实验（A/B/C 三档 + 分组统计）。

问题（2026-09-16 评审提出）：weekly_trend 至今是 BUY 硬门槛，但滚动验证
只裁决了"日线标签无超额"（R3），从未裁决硬门槛本身。核心问题升级为：
**周趋势是领先信息、同步信息，还是滞后的多余确认？**

设计（PIT、流式、单帧内存）：
  - 候选日 = 月线通过 AND 周级动能 active_up AND 日线标签命中 AND regime∈{bull,mid}
    （即 feature_only 口径下的完整买点集合；hard_gate 是其子集 trend≠none）
  - A(hard_gate) = 候选 ∧ trend≠none；B(feature_only)=全部候选；C(off) 同 B
    （C 与 B 的差异仅在趋势特征参与度，此处收益统计等价）
  - 分组：trend ∈ {ma_bull, macd_cross, macd_stabilizing, none}
    → n / fwd5 / fwd10 / fwd20 均值中位 / MAE10 / MFE10（次日开盘入场）
  - 稳定性：按半年分桶看各组 fwd10 中位符号是否跨期一致（walk-forward 语义）
  - 判别：none 组 MFE 高且 MAE 不恶化 ⇒ 周趋势=多余慢确认；none 组差 ⇒ 硬门槛有过滤价值

PIT 手段：每股只保留尾部 550 根的滚动切片评估（月线需≤23个月、周线≤14周、
标签/动能≤2周，均被覆盖）；regime 按日全体股票共享一次计算。

用法：
  PYTHONPATH=src python3 scripts/trend_gate_experiment.py --sample 800 \
      --start 2022-01-04 --out output/research/trend_gate
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_decision import stream_qualified_codes  # noqa: E402
from stock_selector.config import load_config  # noqa: E402
from stock_selector.data.tdx import TdxStore  # noqa: E402
from stock_selector.data.tdx_index import index_daily  # noqa: E402
from stock_selector.decision.labels import daily_labels  # noqa: E402
from stock_selector.decision.regime import market_regime  # noqa: E402
from stock_selector.decision.replay import truncate_daily  # noqa: E402
from stock_selector.decision.weekly_momentum import ACTIVE_UP, weekly_momentum  # noqa: E402
from stock_selector.strategies.trend import monthly_trend, weekly_trend  # noqa: E402

TAIL = 550  # 滚动切片长度（PIT：覆盖月线/周线/标签全部回看窗）


def trend_category(trend_result) -> str:
    sig = set(trend_result.signals or [])
    if "ma_bull" in sig or trend_result.reason == "ma_bull":
        return "ma_bull"
    if "macd_cross" in sig:
        return "macd_cross"
    if "macd_stabilizing" in sig:
        return "macd_stabilizing"
    return "none"


def run(frames_iter, index_frame, cfg, start, end):
    dcfg = cfg.get("decision", cfg)
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    # regime 按日预计算（全体共享）
    days = [d for d in index_frame.index if start_ts <= d <= pd.Timestamp(end_ts) + pd.Timedelta(days=40)]
    regime_by_day: dict[pd.Timestamp, str | None] = {}
    for d in days:
        asof = datetime(d.year, d.month, d.day, 15, 5)
        rg, _ = market_regime(truncate_daily(index_frame, asof), asof)
        regime_by_day[pd.Timestamp(d)] = rg

    rows: list[dict] = []
    n_codes = n_days_eval = 0
    for code, daily in frames_iter:
        n_codes += 1
        if daily is None or len(daily) < 120:
            continue
        highs, lows = daily["high"].to_numpy(), daily["low"].to_numpy()
        closes, opens = daily["close"].to_numpy(), daily["open"].to_numpy()
        idx = daily.index
        n = len(idx)
        eval_from = max(60, int(pd.Index(idx).searchsorted(pd.Timestamp(start), side="left")))
        for i in range(eval_from, n):
            ts = idx[i]
            if ts > end_ts:
                break
            rg = regime_by_day.get(ts)
            if rg not in ("bull", "mid"):
                continue
            lo = max(0, i - TAIL + 1)
            frame = daily.iloc[lo:i + 1]
            asof = datetime(ts.year, ts.month, ts.day, 15, 5)
            # 廉价前置：月线不通过直接跳过（省掉动能/标签计算）
            m = monthly_trend(frame, cfg)
            if not m.passed:
                continue
            mom = weekly_momentum(frame, asof, cfg, None)
            if mom.state != ACTIVE_UP:
                continue
            lab = daily_labels(frame, asof, cfg, None)
            if not any(lab.labels.values()):
                continue
            tr = weekly_trend(frame, cfg)
            cat = trend_category(tr)
            n_days_eval += 1
            # 前瞻收益（次日开盘入场；不足窗口记 NaN）
            def _fwd(k):
                j = i + 1 + k
                if j >= n or i + 1 >= n:
                    return np.nan
                return closes[j] / opens[i + 1] - 1.0
            e = i + 1
            if e < n:
                hi = highs[e:min(n, e + 10)]
                lo10 = lows[e:min(n, e + 10)]
                mae = (lo10.min() / opens[e] - 1.0) if len(lo10) else np.nan
                mfe = (hi.max() / opens[e] - 1.0) if len(hi) else np.nan
            else:
                mae = mfe = np.nan
            rows.append({
                "code": code, "date": str(ts.date()), "weekday": ts.weekday(),
                "regime": rg, "trend": cat, "label": lab.primary_type,
                "mom_origin": mom.evidence_origin,
                "fwd5": _fwd(4), "fwd10": _fwd(9), "fwd20": _fwd(19),
                "mae10": mae, "mfe10": mfe,
                "half": f"{ts.year}H{1 if ts.month <= 6 else 2}",
            })
    return pd.DataFrame(rows), n_codes, n_days_eval


def summarize(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if df.empty:
        empty = pd.DataFrame()
        return empty, empty, {"n_total": 0, "note": "no_candidates"}

    def _agg(g):
        return pd.Series({
            "n": len(g),
            "fwd5_med": g.fwd5.median(), "fwd10_med": g.fwd10.median(),
            "fwd20_med": g.fwd20.median(),
            "fwd10_mean": g.fwd10.mean(),
            "mae10_med": g.mae10.median(), "mfe10_med": g.mfe10.median(),
            "mfe_mae_ratio": (g.mfe10.median() / abs(g.mae10.median())
                              if g.mae10.median() < 0 else np.nan),
        })
    pooled = df.groupby("trend").apply(_agg, include_groups=False)
    per_half = df.groupby(["half", "trend"]).apply(_agg, include_groups=False)
    # walk-forward 符号一致性：fwd10_med>0 的半年占比
    sign = (per_half["fwd10_med"] > 0).groupby("trend").mean().rename("fwd10_pos_half_ratio")
    verdict = {
        "n_total": len(df),
        "n_hard_gate_A": int((df.trend != "none").sum()),
        "n_feature_only_B": len(df),
        "B_minus_A_n": int((df.trend == "none").sum()),
        "fwd10_pos_ratio": sign.to_dict(),
        "arms": "A=hard_gate(trend≠none) ⊂ B=feature_only(全部候选)；C(off)收益统计与B等价",
    }
    return pooled, per_half, verdict


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=None)
    p.add_argument("--sample", type=int, default=800)
    p.add_argument("--seed", type=int, default=20260916)
    p.add_argument("--start", default="2022-01-04")
    p.add_argument("--end", default="2026-09-15")
    p.add_argument("--min-amount", type=float, default=2e7)
    p.add_argument("--out", default="output/research/trend_gate")
    args = p.parse_args()

    cfg = load_config(args.config)
    store = TdxStore(cfg["paths"]["tdx_dir"])
    rng = np.random.default_rng(args.seed)
    codes = sorted(store.list_codes())
    picked = rng.choice(codes, size=min(args.sample, len(codes)), replace=False).tolist()
    print(f"样本 {len(picked)} 只（seed={args.seed}）", flush=True)
    frames_iter = stream_qualified_codes(store, picked, args.min_amount, yield_frames=True)
    index_frame = index_daily(cfg["paths"]["tdx_dir"], "sh", "000001")

    df, n_codes, n_eval = run(frames_iter, index_frame, cfg, args.start, args.end)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "candidates.csv", index=False, encoding="utf-8-sig")
    pooled, per_half, verdict = summarize(df)
    pooled.round(4).to_csv(out / "pooled_by_trend.csv", encoding="utf-8-sig")
    per_half.round(4).to_csv(out / "per_half_by_trend.csv", encoding="utf-8-sig")
    (out / "verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2, default=str),
                                      encoding="utf-8")
    print(f"codes={n_codes} eval_days={n_eval} candidates={len(df)}", flush=True)
    print(pooled.round(4).to_string(), flush=True)
    print(json.dumps(verdict, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
