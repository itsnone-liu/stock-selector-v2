from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import pandas as pd

from stock_selector.models import Decision
from stock_selector.output import write_csv, write_json
from stock_selector.strategies.buy import daily_buy
from stock_selector.strategies.risk import check_risk_filters


def run_backtest(pipeline, pool: pd.DataFrame, start: str, end: str, horizons: tuple[int, ...]) -> dict[str, Path]:
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    events: list[dict] = []
    for row in pool.to_dict("records"):
        code = str(row["代码"]).zfill(6)
        name = pipeline._name(code, row.get("名称", ""))
        daily = pipeline.store.daily(code)
        if daily is None or len(daily) < 80:
            continue
        if not check_risk_filters(code, name, daily, pipeline.config).passed:
            continue
        indices = [i for i, ts in enumerate(daily.index) if start_ts <= ts <= end_ts]
        for index in indices:
            history = daily.iloc[: index + 1]
            at = datetime.combine(pd.Timestamp(daily.index[index]).date(), time(15, 0))
            result = daily_buy(history, at, pipeline.config)
            if not result.passed:
                continue
            entry = float(daily.iloc[index]["close"])
            event = {
                "代码": code,
                "名称": name,
                "日期": pd.Timestamp(daily.index[index]).date().isoformat(),
                "买点类型": result.reason,
                "评分": result.score,
                "入选收盘": entry,
            }
            for horizon in horizons:
                future_index = index + horizon
                event[f"收益{horizon}日%"] = round((float(daily.iloc[future_index]["close"]) / entry - 1) * 100, 3) if future_index < len(daily) else None
            events.append(event)
    frame = pd.DataFrame(events)
    summary: dict = {"events": len(frame), "start": start, "end": end, "horizons": horizons}
    if not frame.empty:
        summary["by_buy_type"] = {}
        for buy_type, group in frame.groupby("买点类型"):
            item = {"count": len(group)}
            for horizon in horizons:
                column = f"收益{horizon}日%"
                valid = group[column].dropna()
                item[f"mean_{horizon}d_pct"] = round(float(valid.mean()), 4) if len(valid) else None
                item[f"win_rate_{horizon}d"] = round(float((valid > 0).mean()), 4) if len(valid) else None
            summary["by_buy_type"][buy_type] = item
    return {
        "events": write_csv(frame, pipeline.output_dir / "backtest_events.csv"),
        "summary": write_json(summary, pipeline.output_dir / "backtest_summary.json"),
    }
