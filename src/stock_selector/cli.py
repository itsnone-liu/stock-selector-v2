from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from stock_selector.config import load_config
from stock_selector.pipeline import SelectorPipeline, load_pool


def _parse_asof(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _print_paths(paths: dict[str, Path]) -> None:
    for name, path in paths.items():
        print(f"{name}: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一A股选股系统 v2")
    parser.add_argument("--config", help="自定义YAML配置；未指定时使用config/default.yaml")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    sub = parser.add_subparsers(dest="command", required=True)

    universe = sub.add_parser("universe", help="导出经过代码范围识别的证券列表")
    universe.add_argument("--output", default="output/universe.csv")

    trends = sub.add_parser("trends", help="运行月线和周线趋势池")
    trends.add_argument("--pool", help="可选输入股票池CSV；默认扫描本地TDX全市场")

    after_close = sub.add_parser("after-close", help="在已有周线池上运行盘后周线形态和日线买点")
    after_close.add_argument("--pool", default="output/weekly_pool.csv")
    after_close.add_argument("--asof", help="ISO时间，如2026-09-15T15:10:00")

    realtime = sub.add_parser("realtime", help="在已有周线池上运行实时选股")
    realtime.add_argument("--pool", default="output/weekly_pool.csv")
    realtime.add_argument("--asof", help="ISO时间；默认当前时间")

    board = sub.add_parser("board", help="针对任意板块/股票池直接运行日线买点")
    board.add_argument("--pool", required=True)
    board.add_argument("--board", help="按板块名称或source_boards包含关系过滤")
    board.add_argument("--realtime", action="store_true")
    board.add_argument("--asof", help="ISO时间；默认当前时间")

    backtest = sub.add_parser("backtest", help="回测日线买点的后续收益")
    backtest.add_argument("--pool", required=True)
    backtest.add_argument("--start", required=True)
    backtest.add_argument("--end", required=True)
    backtest.add_argument("--horizons", default="1,3,5,10")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config(args.config)
    pipeline = SelectorPipeline(config)
    if args.command == "universe":
        target = Path(args.output)
        if not target.is_absolute():
            target = Path(config["_project_root"]) / target
        frame = pipeline.universe()
        from stock_selector.output import write_csv
        print(write_csv(frame, target))
        return 0
    if args.command == "trends":
        pool = load_pool(args.pool) if args.pool else None
        _print_paths(pipeline.run_trends(pool))
        return 0
    if args.command == "after-close":
        _print_paths(pipeline.run_after_close(load_pool(args.pool), _parse_asof(args.asof)))
        return 0
    if args.command == "realtime":
        _print_paths(pipeline.run_realtime(load_pool(args.pool), _parse_asof(args.asof)))
        return 0
    if args.command == "board":
        pool = load_pool(args.pool, args.board)
        _print_paths(pipeline.run_board(pool, _parse_asof(args.asof), args.realtime))
        return 0
    if args.command == "backtest":
        from stock_selector.backtest import run_backtest
        horizons = tuple(int(item) for item in args.horizons.split(",") if item.strip())
        _print_paths(run_backtest(pipeline, load_pool(args.pool), args.start, args.end, horizons))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
