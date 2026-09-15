from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from stock_selector.config import resolve_project_path
from stock_selector.data.realtime import TencentQuoteProvider
from stock_selector.data.tdx import TdxStore, load_name_map
from stock_selector.freshness import check_daily_freshness, check_quote_freshness
from stock_selector.models import Decision, DiagnosticCounter, Quote, RuleResult
from stock_selector.output import write_csv, write_json
from stock_selector.snapshots import VolumeSnapshotStore
from stock_selector.strategies.buy import daily_buy
from stock_selector.strategies.risk import check_risk_filters
from stock_selector.strategies.surge import weekly_surge
from stock_selector.strategies.trend import monthly_trend, weekly_trend

LOG = logging.getLogger(__name__)


def load_pool(path: str | Path, board: str | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    code_candidates = [c for c in frame.columns if ("代码" in c or str(c).lower() == "code") and "board" not in str(c).lower()]
    if not code_candidates:
        raise ValueError(f"No stock code column in {path}")
    name_candidates = [c for c in frame.columns if ("名称" in c or str(c).lower() == "name") and "board" not in str(c).lower() and "板块" not in str(c)]
    frame["代码"] = frame[code_candidates[0]].astype(str).str.strip().str.zfill(6)
    frame["名称"] = frame[name_candidates[0]].fillna("") if name_candidates else ""
    if board:
        masks = []
        for column in ("board", "板块", "板块名称", "source_boards"):
            if column in frame.columns:
                masks.append(frame[column].fillna("").astype(str).str.contains(board, regex=False))
        if not masks:
            raise ValueError(f"Board filter requested but no board column in {path}")
        mask = masks[0]
        for extra in masks[1:]:
            mask = mask | extra
        frame = frame[mask].copy()
    return frame.drop_duplicates("代码")


class SelectorPipeline:
    def __init__(self, config: dict):
        self.config = config
        self.store = TdxStore(config["paths"]["tdx_dir"])
        self.names = load_name_map(config["paths"].get("names_file"))
        self.output_dir = resolve_project_path(config, config["paths"]["output_dir"])
        self.state_dir = resolve_project_path(config, config["paths"]["state_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.volume_snapshots = VolumeSnapshotStore(self.state_dir / "intraday_volume_snapshots.csv")
        self._daily_cache: dict[str, pd.DataFrame | None] = {}

    def _daily(self, code: str) -> pd.DataFrame | None:
        code = str(code).zfill(6)
        if code not in self._daily_cache:
            self._daily_cache[code] = self.store.daily(code)
        return self._daily_cache[code]

    def _name(self, code: str, supplied: str = "") -> str:
        supplied = "" if pd.isna(supplied) else str(supplied).strip()
        return supplied or self.names.get(code, "")

    def universe(self) -> pd.DataFrame:
        codes = self.store.list_codes(self.config["universe"].get("include_b_share", False))
        return pd.DataFrame({"代码": codes, "名称": [self._name(code) for code in codes]})

    def _run_stage(self, pool: pd.DataFrame, stage: str, evaluator) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        accepted: list[dict] = []
        rejected: list[dict] = []
        counter = DiagnosticCounter()
        for row in pool.to_dict("records"):
            code = str(row["代码"]).zfill(6)
            name = self._name(code, row.get("名称", ""))
            daily = self._daily(code)
            if daily is None:
                result = RuleResult(Decision.SKIP, stage, "missing_daily_data")
            else:
                risk = check_risk_filters(code, name, daily, self.config)
                result = evaluator(daily, row) if risk.passed else risk
            counter.add(result)
            payload = {"代码": code, "名称": name, "阶段": stage, "判定": result.decision.value, "原因": result.reason, "评分": result.score, **result.metrics}
            if result.passed:
                accepted.append({**row, **payload, "信号": "、".join(result.signals)})
            else:
                rejected.append(payload)
        return pd.DataFrame(accepted), pd.DataFrame(rejected), vars(counter)

    def run_trends(self, pool: pd.DataFrame | None = None) -> dict[str, Path]:
        base = pool if pool is not None else self.universe()
        monthly, monthly_reject, monthly_diag = self._run_stage(base, "monthly", lambda daily, row: monthly_trend(daily, self.config))
        weekly, weekly_reject, weekly_diag = self._run_stage(monthly, "weekly", lambda daily, row: weekly_trend(daily, self.config))
        paths = {
            "monthly": write_csv(monthly, self.output_dir / "monthly_pool.csv"),
            "weekly": write_csv(weekly, self.output_dir / "weekly_pool.csv"),
            "monthly_rejections": write_csv(monthly_reject, self.output_dir / "monthly_rejections.csv"),
            "weekly_rejections": write_csv(weekly_reject, self.output_dir / "weekly_rejections.csv"),
            "diagnostics": write_json({"monthly": monthly_diag, "weekly": weekly_diag}, self.output_dir / "trend_diagnostics.json"),
        }
        return paths

    def run_realtime(self, pool: pd.DataFrame, asof: datetime | None = None) -> dict[str, Path]:
        at = asof or datetime.now()
        provider = TencentQuoteProvider(
            int(self.config["realtime"].get("timeout_seconds", 15)),
            int(self.config["realtime"].get("batch_size", 50)),
            100.0 if self.config["realtime"].get("tencent_volume_unit", "hand") == "hand" else 1.0,
        )
        quotes, quote_errors = provider.fetch(pool["代码"].tolist(), at)
        references = self.volume_snapshots.references(pool["代码"].tolist(), at)
        self.volume_snapshots.save(quotes, at)
        return self._run_signal_pipeline(pool, at, quotes, quote_errors, realtime=True, same_time_volumes=references)

    def run_after_close(self, pool: pd.DataFrame, asof: datetime | None = None) -> dict[str, Path]:
        at = asof or datetime.now()
        return self._run_signal_pipeline(pool, at, {}, {}, realtime=False)

    def run_board(self, pool: pd.DataFrame, asof: datetime | None = None, realtime: bool = False) -> dict[str, Path]:
        at = asof or datetime.now()
        quotes: dict[str, Quote] = {}
        errors: dict[str, str] = {}
        if realtime:
            provider = TencentQuoteProvider(
                int(self.config["realtime"].get("timeout_seconds", 15)),
                int(self.config["realtime"].get("batch_size", 50)),
            )
            quotes, errors = provider.fetch(pool["代码"].tolist(), at)
            references = self.volume_snapshots.references(pool["代码"].tolist(), at)
            self.volume_snapshots.save(quotes, at)
        else:
            references = {}
        return self._run_signal_pipeline(pool, at, quotes, errors, realtime=realtime, skip_surge=True, same_time_volumes=references)

    def _run_signal_pipeline(
        self,
        pool: pd.DataFrame,
        at: datetime,
        quotes: dict[str, Quote],
        quote_errors: dict[str, str],
        realtime: bool,
        skip_surge: bool = False,
        same_time_volumes: dict[str, float] | None = None,
    ) -> dict[str, Path]:
        same_time_volumes = same_time_volumes or {}
        surge_pass: list[dict] = []
        buy_pass: list[dict] = []
        green_pass: list[dict] = []
        rejections: list[dict] = []
        counters = {"freshness": DiagnosticCounter(), "risk": DiagnosticCounter(), "surge": DiagnosticCounter(), "buy": DiagnosticCounter()}
        for row in pool.to_dict("records"):
            code = str(row["代码"]).zfill(6)
            name = self._name(code, row.get("名称", ""))
            daily = self._daily(code)
            if daily is None:
                result = RuleResult(Decision.SKIP, "risk", "missing_daily_data")
                counters["risk"].add(result)
                rejections.append({"代码": code, "名称": name, "阶段": "risk", "原因": result.reason})
                continue
            freshness = check_daily_freshness(daily, at, self.config, realtime)
            counters["freshness"].add(freshness)
            if not freshness.passed:
                rejections.append({"代码": code, "名称": name, "阶段": "freshness", "原因": freshness.reason, **freshness.metrics})
                continue
            risk = check_risk_filters(code, name, daily, self.config)
            counters["risk"].add(risk)
            if not risk.passed:
                rejections.append({"代码": code, "名称": name, "阶段": "risk", "原因": risk.reason, **risk.metrics})
                continue
            quote = quotes.get(code)
            if realtime and quote is None:
                result = RuleResult(Decision.SKIP, "surge", quote_errors.get(code, "missing_realtime_quote"))
                counters["surge"].add(result)
                rejections.append({"代码": code, "名称": name, "阶段": "quote", "原因": result.reason})
                continue
            if realtime:
                quote_freshness = check_quote_freshness(quote, at, self.config)
                counters["freshness"].add(quote_freshness)
                if not quote_freshness.passed:
                    rejections.append({"代码": code, "名称": name, "阶段": "freshness", "原因": quote_freshness.reason, **quote_freshness.metrics})
                    continue
            if skip_surge:
                surge = RuleResult(Decision.PASS, "surge", "board_mode_skips_surge", 0.0)
            else:
                surge = weekly_surge(daily, at, self.config, quote)
            counters["surge"].add(surge)
            if not surge.passed:
                rejections.append({"代码": code, "名称": name, "阶段": "surge", "原因": surge.reason, **surge.metrics})
                continue
            surge_row = {"代码": code, "名称": name, "形态": surge.reason, "周线评分": surge.score, **surge.metrics}
            surge_pass.append(surge_row)
            if quote and quote.price < quote.previous_close:
                green_pass.append({**surge_row, "实时价": quote.price, "昨收": quote.previous_close, "日涨幅%": round((quote.price / quote.previous_close - 1) * 100, 3)})
            upstream = surge.score
            buy = daily_buy(daily, at, self.config, upstream, quote, same_time_volumes.get(code))
            counters["buy"].add(buy)
            if not buy.passed:
                rejections.append({"代码": code, "名称": name, "阶段": "buy", "原因": buy.reason, **buy.metrics})
                continue
            buy_pass.append({"代码": code, "名称": name, "买点类型": buy.reason, "综合评分": buy.score, "信号": "、".join(buy.signals), **buy.metrics})
        suffix = "realtime" if realtime else "close"
        if skip_surge:
            suffix = "board_realtime" if realtime else "board_close"
        diagnostics = {key: vars(value) for key, value in counters.items()}
        diagnostics["quote_errors"] = quote_errors
        diagnostics["same_time_volume_references"] = len(same_time_volumes)
        diagnostics["asof"] = at.isoformat()
        frames = {
            "surge": pd.DataFrame(surge_pass),
            "buy": pd.DataFrame(buy_pass).sort_values("综合评分", ascending=False) if buy_pass else pd.DataFrame(),
            "green": pd.DataFrame(green_pass),
            "rejections": pd.DataFrame(rejections),
        }
        paths = {
            key: write_csv(frame, self.output_dir / f"{('surge_green' if key == 'green' else key)}_{suffix}.csv")
            for key, frame in frames.items()
        }
        paths["diagnostics"] = write_json(diagnostics, self.output_dir / f"diagnostics_{suffix}.json")
        run_dir = self.output_dir / "runs" / at.strftime("%Y%m%d_%H%M%S") / suffix
        for key, frame in frames.items():
            write_csv(frame, run_dir / f"{key}.csv")
        write_json(diagnostics, run_dir / "diagnostics.json")
        paths["run_archive"] = run_dir
        return paths
