#!/usr/bin/env python3
"""组合级回放器（研究用，无成本模型）：多票 + caps + T+1 + E1-E5 组合语境。

执行模型（与决策栈语义一致）：
  - 检查点 = 每交易日 15:05（L2，盘后完整证据）；
  - 买/卖信号 T 日盘后产生 → T+1 开盘成交（close-confirm 模型）；
  - 结构止损位 = 信号日低点（ExitAnchor.structural_stop）；
  - 退出信号由 ExitMonitor 对持仓逐日评估（E1/E2/E3/E5），T+1 开盘执行；
  - caps：单票20% / 单日新增30% / 行业40%（无行业映射时跳过）/ regime 档位总仓
    （bull=100% / mid=50% / weak=0%）；
  - T+1：当日买入的 lot 次日才可卖（Portfolio.sellable_qty）。

组合语境进入决策：decide(advice) 在持仓时收到 anchor → 产生 hold/add/sell 而非
重复 buy；买入资格 = advice.action == "buy" 且无持仓。

用法：
  PYTHONPATH=src python3 scripts/portfolio_replay.py --sample 40 \
      --start 2025-06-01 --end 2026-09-15 --capital 1000000
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
from stock_selector.decision.exits import ExitAnchor  # noqa: E402
from stock_selector.decision.portfolio import Portfolio  # noqa: E402
from stock_selector.decision.regime import market_regime  # noqa: E402
from stock_selector.decision.replay import DecisionService, truncate_daily  # noqa: E402

CONF_RANK = {"high": 0, "medium": 1, "low": 2, "unknown": 3}


def run_portfolio_replay(frames: dict[str, pd.DataFrame], index_frame: pd.DataFrame,
                         cfg: dict, start: str, end: str, capital: float = 1_000_000.0,
                         top_per_day: int = 3, checkpoint: dtime = dtime(15, 5),
                         context_payload: dict | None = None,
                         service: DecisionService | None = None) -> dict:
    """核心回放循环。frames: code→完整日线（函数内部做 PIT 截断）。

    service 可注入（测试用桩）；缺省现场构造。
    """
    if service is None:
        service = DecisionService(config=cfg, daily_loader=lambda c: frames.get(c),
                                  index_loader=lambda: index_frame)
    pf = Portfolio(cash=capital)
    cap_cfg = cfg.get("decision", {}).get("portfolio", {})
    anchors: dict[str, ExitAnchor] = {}
    pending_exits: list[dict] = []   # T日信号 → T+1开盘执行
    pending_buys: list[dict] = []
    trades: list[dict] = []
    daily_rows: list[dict] = []

    days = [d for d in index_frame.index
            if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    days = sorted(days)
    day_bars = {c: f for c, f in frames.items()}
    regime, _ = market_regime(index_frame, datetime.combine(days[0], dtime(15, 5)))

    for di, day in enumerate(days):
        ts = pd.Timestamp(day)
        asof = datetime(ts.year, ts.month, ts.day, checkpoint.hour, checkpoint.minute)
        prev_day = days[di - 1] if di > 0 else None

        # ---- 1. 早盘：执行昨日信号（开盘价成交） ----
        if prev_day is not None:
            # 卖出（先卖后买，释放现金与 caps 空间）
            for pe in [x for x in pending_exits]:
                c = pe["code"]
                f = day_bars.get(c)
                if f is None or ts not in f.index:
                    continue
                open_px = float(f.loc[ts, "open"])
                qty = pf.positions[c].sellable_qty(ts.date()) if c in pf.positions else 0.0
                if qty <= 0:
                    continue  # T+1：全部为当日买入（理论上不会，信号隔日）
                sold = pf.sell(c, open_px, qty, at=asof)
                if sold > 0:
                    trades.append({"date": str(ts.date()), "code": c, "side": "sell",
                                   "price": round(open_px, 4), "qty": sold,
                                   "value": round(sold * open_px, 2),
                                   "reason": pe["rule"]})
                    anchors.pop(c, None)
            pending_exits = []
            # 买入（按信号日置信度排序，caps 约束在信号日预算、成交日复核）
            for pb in sorted(pending_buys, key=lambda x: (x["rank"], x["code"])):
                c = pb["code"]
                f = day_bars.get(c)
                if f is None or ts not in f.index or c in pf.positions:
                    continue
                open_px = float(f.loc[ts, "open"])
                if open_px <= 0:
                    continue
                regime_now, _ = market_regime(truncate_daily(index_frame, asof), asof)
                budget = min(pb["budget"], pf.equity * 0.2 - pf.position_value(c)) \
                    if pf.equity > 0 else 0.0
                qty = int(max(0.0, budget) / open_px / 100) * 100  # 整手
                if qty <= 0:
                    continue
                ok, reasons = pf.can_buy(c, open_px, qty, cap_cfg, ts.date(), regime_now,
                                         industry=None)
                if not ok:
                    continue
                if qty * open_px > pf.cash:
                    qty = int(pf.cash / open_px / 100) * 100
                    if qty <= 0:
                        continue
                pf.buy(c, open_px, float(qty), at=asof)
                trades.append({"date": str(ts.date()), "code": c, "side": "buy",
                               "price": round(open_px, 4), "qty": qty,
                               "value": round(qty * open_px, 2), "reason": pb["reason"]})
                anchors[c] = ExitAnchor(
                    entry_date=str(ts.date()), entry_price=open_px,
                    structural_stop=pb["stop"], time_stop_days=int(
                        cfg["decision"]["exits"]["time_stop_days"]),
                    trail_pct=float(cfg["decision"]["exits"]["trail_pct"]) / 100.0,
                    max_hold_days=int(cfg["decision"]["exits"]["max_hold_days"]))
            pending_buys = []

        # ---- 2. 盘后：评估决策栈（持仓→退出监控；空仓→买入候选） ----
        regime, _ = market_regime(truncate_daily(index_frame, asof), asof)
        buys: list[dict] = []
        for c, f in day_bars.items():
            if ts not in f.index:
                continue
            advice = service.evaluate(c, asof, context_payload=context_payload,
                                      portfolio=pf, anchor=anchors.get(c))
            if c in pf.positions and advice.get("exit_signals"):
                for sig in advice["exit_signals"]:
                    if sig.get("action") == "sell":
                        pending_exits.append({"code": c, "rule": sig.get("rule", "?")})
                        break
                continue  # 持仓日不再重复评估买点
            if advice.get("action") == "buy" and c not in pf.positions:
                stop = advice.get("invalidation", {}).get("structural_stop") \
                    or float(f.loc[ts, "low"])
                buys.append({"code": c, "rank": CONF_RANK.get(advice.get("confidence", "low"), 3),
                             "stop": float(stop),
                             "budget": pf.equity * 0.2,
                             "reason": "+".join(advice.get("rationale") or [])[:120]})
        for pb in buys[:top_per_day]:
            pending_buys.append(pb)

        # ---- 3. 收盘估值 ----
        marks = {c: float(f.loc[ts, "close"]) for c, f in day_bars.items()
                 if c in pf.positions and ts in f.index}
        pf.mark(marks)
        inv = pf.invested_value()
        daily_rows.append({"date": str(ts.date()), "equity": round(pf.equity, 2),
                           "cash": round(pf.cash, 2), "invested": round(inv, 2),
                           "n_pos": len(pf.positions), "regime": regime or "?"})

    # ---- 汇总 ----
    eq = pd.Series([r["equity"] for r in daily_rows], index=[r["date"] for r in daily_rows])
    ret = eq.iloc[-1] / capital - 1 if len(eq) else 0.0
    dd = (eq / eq.cummax() - 1).min() if len(eq) else 0.0
    # 基准：同池等权日收益（close-to-close）
    pool_ret: list[float] = []
    frames_close = pd.DataFrame({c: f["close"] for c, f in day_bars.items()})
    span = frames_close.loc[(frames_close.index >= pd.Timestamp(start))
                            & (frames_close.index <= pd.Timestamp(end))]
    if len(span) > 1:
        pool_ret = span.pct_change().mean(axis=1).dropna().tolist()
    bench = float((1 + pd.Series(pool_ret)).prod() - 1) if pool_ret else 0.0
    tdf = pd.DataFrame(trades)
    exit_reasons = tdf[tdf["side"] == "sell"]["reason"].value_counts().to_dict() if len(tdf) else {}
    return {
        "trades": tdf,
        "daily": pd.DataFrame(daily_rows),
        "summary": {
            "start": start, "end": end, "codes": len(frames), "capital": capital,
            "final_equity": round(float(eq.iloc[-1]), 2) if len(eq) else capital,
            "total_return": round(ret, 4), "max_drawdown": round(dd, 4),
            "n_trades": len(tdf),
            "buys": int((tdf["side"] == "buy").sum()) if len(tdf) else 0,
            "exit_reasons": exit_reasons,
            "benchmark_equal_weight": round(bench, 4),
            "limitations": ["无成本/滑点", "退出=close-confirm次日开盘模型",
                            "行业40%上限未启用（无行业映射）", "研究用"],
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=None)
    p.add_argument("--codes", default=None, help="逗号分隔；缺省用--sample种子抽样")
    p.add_argument("--sample", type=int, default=40)
    p.add_argument("--seed", type=int, default=20260916)
    p.add_argument("--start", default="2025-06-01")
    p.add_argument("--end", default="2026-09-15")
    p.add_argument("--capital", type=float, default=1_000_000.0)
    p.add_argument("--top-per-day", type=int, default=3)
    p.add_argument("--min-amount", type=float, default=2e7)
    p.add_argument("--out", default="output/research/portfolio_replay")
    args = p.parse_args()

    cfg = load_config(args.config)
    store = TdxStore(cfg["paths"]["tdx_dir"])
    if args.codes:
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
    else:
        all_codes = sorted(store.list_codes())
        rng = np.random.default_rng(args.seed)
        codes = rng.choice(all_codes, size=min(args.sample, len(all_codes)),
                           replace=False).tolist()
    frames: dict[str, pd.DataFrame] = {}
    for code, f in stream_qualified_codes(store, codes, args.min_amount, yield_frames=True):
        frames[code] = f
    print(f"合格样本 {len(frames)}/{len(codes)}")
    index_frame = index_daily(cfg["paths"]["tdx_dir"], "sh", "000001")

    result = run_portfolio_replay(frames, index_frame, cfg, args.start, args.end,
                                  capital=args.capital, top_per_day=args.top_per_day)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if len(result["trades"]):
        result["trades"].to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    result["daily"].to_csv(out / "daily_equity.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
