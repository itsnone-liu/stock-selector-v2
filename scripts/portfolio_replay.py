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
import hashlib
import json
import platform
import subprocess
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
from stock_selector.decision.execution import (CostModel, EXECUTION_MODEL_VERSION,
                                               execution_feasibility)  # noqa: E402
from stock_selector.decision.portfolio import Portfolio  # noqa: E402
from stock_selector.decision.regime import market_regime  # noqa: E402
from stock_selector.decision.replay import DecisionService, truncate_daily  # noqa: E402

CONF_RANK = {"high": 0, "medium": 1, "low": 2, "unknown": 3}


def replay_input_hash(frames: dict[str, pd.DataFrame], index_frame: pd.DataFrame,
                      cfg: dict, start: str, end: str) -> str:
    """区间内完整输入内容指纹；区间外未来数据不得改变该哈希。"""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    idx = index_frame.loc[(index_frame.index >= start_ts) & (index_frame.index <= end_ts)]
    h = hashlib.sha256(json.dumps({"start": start, "end": end, "config": cfg},
                                  ensure_ascii=False, sort_keys=True,
                                  default=str).encode())
    def update_frame(label: str, f: pd.DataFrame) -> None:
        h.update(label.encode())
        canonical = f.sort_index().sort_index(axis=1)
        h.update(pd.util.hash_pandas_object(canonical.index, index=False).values.tobytes())
        h.update(pd.util.hash_pandas_object(canonical, index=True).values.tobytes())
    update_frame("__index__", idx)
    for c, f in sorted(frames.items()):
        visible = f.loc[(f.index >= start_ts) & (f.index <= end_ts)]
        update_frame(c, visible)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run_manifest(cfg: dict, seed: int, codes: list[str], result: dict,
                 start_git_sha: str) -> dict:
    cfg_raw = json.dumps(cfg, ensure_ascii=False, sort_keys=True, default=str).encode()
    return {"git_sha": start_git_sha, "python": platform.python_version(), "seed": seed,
            "codes": sorted(codes), "config_sha256": hashlib.sha256(cfg_raw).hexdigest(),
            "input_snapshot_hash": result["summary"]["input_snapshot_hash"],
            "execution_model": result["summary"]["execution_model"]}


def run_portfolio_replay(frames: dict[str, pd.DataFrame], index_frame: pd.DataFrame,
                         cfg: dict, start: str, end: str, capital: float = 1_000_000.0,
                         top_per_day: int = 3, checkpoint: dtime = dtime(15, 5),
                         context_payload: dict | None = None,
                         service: DecisionService | None = None,
                         cost_model: CostModel | None = None) -> dict:
    """核心回放循环。frames: code→完整日线（函数内部做 PIT 截断）。

    service 可注入（测试用桩）；缺省现场构造。
    """
    if service is None:
        service = DecisionService(config=cfg, daily_loader=lambda c: frames.get(c),
                                  index_loader=lambda: index_frame)
    pf = Portfolio(cash=capital)
    exec_cfg = cfg.get("decision", {}).get("execution", {})
    configured_version = exec_cfg.get("model_version", EXECUTION_MODEL_VERSION)
    if configured_version != EXECUTION_MODEL_VERSION:
        raise ValueError(f"unsupported execution model: {configured_version}")
    costs = cost_model or CostModel(
        commission_rate=float(exec_cfg.get("commission_rate", 0.0003)),
        minimum_commission=float(exec_cfg.get("minimum_commission", 5.0)),
        slippage_bps=float(exec_cfg.get("slippage_bps", 5.0)),
        transfer_fee_rate=float(exec_cfg.get("transfer_fee_rate", 0.00001)))
    cap_cfg = cfg.get("decision", {}).get("portfolio", {})
    anchors: dict[str, ExitAnchor] = {}
    pending_exits: list[dict] = []   # T日信号 → T+1开盘执行
    pending_buys: list[dict] = []
    trades: list[dict] = []
    rejections: list[dict] = []
    daily_rows: list[dict] = []
    total_cost = 0.0

    days = [d for d in index_frame.index
            if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    days = sorted(days)
    day_bars = {c: f for c, f in frames.items()}
    for di, day in enumerate(days):
        ts = pd.Timestamp(day)
        asof = datetime(ts.year, ts.month, ts.day, checkpoint.hour, checkpoint.minute)
        execution_at = datetime(ts.year, ts.month, ts.day, 9, 30)
        prev_day = days[di - 1] if di > 0 else None

        # ---- 1. 早盘：执行昨日信号（开盘价成交） ----
        if prev_day is not None:
            # 卖出（先卖后买，释放现金与 caps 空间）。被停牌/跌停阻断则次日重试。
            retry_exits: list[dict] = []
            for pe in list(pending_exits):
                c = pe["code"]
                f = day_bars.get(c)
                if f is None or ts not in f.index:
                    rejections.append({"date": str(ts.date()), "code": c, "side": "sell",
                                       "reason": "missing_bar_or_suspended"})
                    retry_exits.append(pe)
                    continue
                bar = f.loc[ts]
                prev_rows = f[f.index < ts]
                prev_close = float(prev_rows.iloc[-1]["close"]) if len(prev_rows) else None
                feasible, blocked = execution_feasibility(c, bar, prev_close, "sell")
                if not feasible:
                    rejections.append({"date": str(ts.date()), "code": c, "side": "sell",
                                       "reason": blocked})
                    retry_exits.append(pe)
                    continue
                qty = pf.positions[c].sellable_qty(ts.date()) if c in pf.positions else 0.0
                if qty <= 0:
                    retry_exits.append(pe)
                    continue
                fill_px = costs.fill_price(float(bar["open"]), "sell")
                fee_parts = costs.fees(fill_px * qty, "sell", ts.date())
                sold = pf.sell(c, fill_px, qty, at=execution_at, fee=fee_parts["total"])
                if sold > 0:
                    total_cost += fee_parts["total"]
                    trades.append({"date": str(ts.date()), "code": c, "side": "sell",
                                   "price": round(fill_px, 4), "qty": sold,
                                   "gross_value": round(sold * fill_px, 2),
                                   "fees": round(fee_parts["total"], 2),
                                   "value": round(sold * fill_px - fee_parts["total"], 2),
                                   "reason": pe["rule"]})
                    anchors.pop(c, None)
            pending_exits = retry_exits
            # 买入：订单携带T日已知regime；成交日只复核价格/现金/可成交性。
            for pb in pending_buys:
                c = pb["code"]
                f = day_bars.get(c)
                if f is None or ts not in f.index or c in pf.positions:
                    continue
                bar = f.loc[ts]
                prev_rows = f[f.index < ts]
                prev_close = float(prev_rows.iloc[-1]["close"]) if len(prev_rows) else None
                feasible, blocked = execution_feasibility(c, bar, prev_close, "buy")
                if not feasible:
                    rejections.append({"date": str(ts.date()), "code": c, "side": "buy",
                                       "reason": blocked})
                    continue
                fill_px = costs.fill_price(float(bar["open"]), "buy")
                budget = min(pb["budget"], pf.equity * 0.2 - pf.position_value(c)) \
                    if pf.equity > 0 else 0.0
                qty = int(max(0.0, budget) / fill_px / 100) * 100  # 整手
                while qty > 0:
                    fees = costs.fees(fill_px * qty, "buy", ts.date())
                    if fill_px * qty + fees["total"] <= pf.cash:
                        break
                    qty -= 100
                if qty <= 0:
                    continue
                ok, reasons = pf.can_buy(c, fill_px, qty, cap_cfg, ts.date(),
                                         pb["signal_regime"], industry=None)
                if not ok:
                    rejections.append({"date": str(ts.date()), "code": c, "side": "buy",
                                       "reason": ";".join(reasons)})
                    continue
                fee_parts = costs.fees(fill_px * qty, "buy", ts.date())
                pf.buy(c, fill_px, float(qty), at=execution_at, fee=fee_parts["total"])
                total_cost += fee_parts["total"]
                trades.append({"date": str(ts.date()), "signal_date": pb["signal_date"],
                               "code": c, "side": "buy", "price": round(fill_px, 4),
                               "qty": qty, "gross_value": round(qty * fill_px, 2),
                               "fees": round(fee_parts["total"], 2),
                               "value": round(qty * fill_px + fee_parts["total"], 2),
                               "reason": pb["reason"], "signal_regime": pb["signal_regime"]})
                anchors[c] = ExitAnchor(
                    entry_date=str(ts.date()), entry_price=fill_px,
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
                             "stop": float(stop), "signal_date": str(ts.date()),
                             "signal_regime": regime,
                             "budget": pf.equity * 0.2,
                             "reason": "+".join(advice.get("rationale") or [])[:120]})
        # P0：先按全候选统一键排序，再截 top-N；输入 dict 顺序不得影响结果。
        pending_buys = sorted(buys, key=lambda x: (x["rank"], x["code"]))[:top_per_day]

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
        "rejections": pd.DataFrame(rejections),
        "daily": pd.DataFrame(daily_rows),
        "summary": {
            "start": start, "end": end, "codes": len(frames), "capital": capital,
            "input_snapshot_hash": replay_input_hash(frames, index_frame, cfg, start, end),
            "final_equity": round(float(eq.iloc[-1]), 2) if len(eq) else capital,
            "total_return": round(ret, 4), "max_drawdown": round(dd, 4),
            "n_trades": len(tdf),
            "buys": int((tdf["side"] == "buy").sum()) if len(tdf) else 0,
            "exit_reasons": exit_reasons,
            "total_cost": round(total_cost, 2),
            "n_execution_rejections": len(rejections),
            "execution_model": EXECUTION_MODEL_VERSION,
            "benchmark_equal_weight": round(bench, 4),
            "limitations": ["开盘涨跌停按日K开盘价保守近似（无盘口队列）",
                            "行业40%上限未启用（无历史行业映射）", "研究用"],
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
    p.add_argument("--trend-policy", default=None,
                   choices=["hard_gate", "feature_only", "off"],
                   help="覆盖 decision.weekly_trend_policy（A/B实验用）")
    p.add_argument("--out", default="output/research/portfolio_replay")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.trend_policy:
        cfg["decision"]["weekly_trend_policy"] = args.trend_policy
    start_git_sha = git_sha()  # 冻结启动时代码版本；长跑期间的新提交不得冒充本跑批
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
    if len(result["rejections"]):
        result["rejections"].to_csv(out / "execution_rejections.csv", index=False,
                                    encoding="utf-8-sig")
    result["daily"].to_csv(out / "daily_equity.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(run_manifest(cfg, args.seed, list(frames), result, start_git_sha),
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
