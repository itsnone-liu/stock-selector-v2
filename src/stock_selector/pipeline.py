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
from stock_selector.output import reserve_run_dir, write_csv, write_json
from stock_selector.snapshots import VolumeSnapshotStore
from stock_selector.bottom_pool import BottomPoolStore
from stock_selector.strategies.bottom import bottom_volume_signal
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
        self.bottom_pool = BottomPoolStore(self.state_dir / "bottom_volume_events.csv")
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

    def _run_stage(self, pool: pd.DataFrame, stage: str, evaluator, asof: datetime) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        """单一阶段筛选：任何策略之前先过统一数据闸门。

        拦截顺序（与 `_run_signal_pipeline` 同一套 `check_daily_freshness` 语义）：
        空数据/缺失 → 过期 → 未来数据（含未排序帧里藏起来的未来行、asof 当日
        更晚时刻戳的行）→ 风险过滤 → 策略。闸门未通过的行绝不进入 evaluator。
        """
        accepted: list[dict] = []
        rejected: list[dict] = []
        counter = DiagnosticCounter()
        freshness_counter = DiagnosticCounter()
        at = pd.Timestamp(asof)
        for row in pool.to_dict("records"):
            code = str(row["代码"]).zfill(6)
            name = self._name(code, row.get("名称", ""))
            daily = self._daily(code)
            freshness = check_daily_freshness(daily, asof, self.config, realtime=False)
            freshness_counter.add(freshness)
            if not freshness.passed:
                result = RuleResult(freshness.decision, stage, freshness.reason, metrics=freshness.metrics)
            else:
                # 前视硬闸：即使闸门以任何方式放行，策略也只能看到 asof 时刻（含）之前的日线。
                visible = daily[pd.to_datetime(daily.index) <= at]
                risk = check_risk_filters(code, name, visible, self.config)
                result = evaluator(visible, row) if risk.passed else risk
            counter.add(result)
            payload = {"代码": code, "名称": name, "阶段": stage, "判定": result.decision.value, "原因": result.reason, "评分": result.score, **result.metrics}
            if result.passed:
                accepted.append({**row, **payload, "信号": "、".join(result.signals)})
            else:
                rejected.append(payload)
        diagnostics = vars(counter)
        diagnostics["freshness"] = vars(freshness_counter)
        return pd.DataFrame(accepted), pd.DataFrame(rejected), diagnostics

    def run_trends(self, pool: pd.DataFrame | None = None, asof: datetime | None = None) -> dict[str, Path]:
        """月线/周线趋势池。`asof` 显式决定数据新鲜度闸门与归档时间戳。"""
        at = asof or datetime.now()
        base = pool if pool is not None else self.universe()
        monthly, monthly_reject, monthly_diag = self._run_stage(base, "monthly", lambda daily, row: monthly_trend(daily, self.config), at)
        weekly, weekly_reject, weekly_diag = self._run_stage(monthly, "weekly", lambda daily, row: weekly_trend(daily, self.config), at)
        diagnostics = {"asof": at.isoformat(), "monthly": monthly_diag, "weekly": weekly_diag}
        # 固定文件名（monthly_pool.csv/weekly_pool.csv）是 SPEC §12 契约与下游
        # `after-close --pool` 的默认输入，必须保持；逐次不可覆盖的证据在 runs/ 归档。
        frames = {
            "monthly": ("monthly_pool.csv", monthly),
            "weekly": ("weekly_pool.csv", weekly),
            "monthly_rejections": ("monthly_rejections.csv", monthly_reject),
            "weekly_rejections": ("weekly_rejections.csv", weekly_reject),
        }
        paths = {key: write_csv(frame, self.output_dir / filename) for key, (filename, frame) in frames.items()}
        paths["diagnostics"] = write_json(diagnostics, self.output_dir / "trend_diagnostics.json")
        run_dir = reserve_run_dir(self.output_dir / "runs", at.strftime("%Y%m%d_%H%M%S"), "trends")
        for filename, frame in frames.values():
            write_csv(frame, run_dir / filename)
        write_json(diagnostics, run_dir / "diagnostics.json")
        paths["run_archive"] = run_dir
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

    def run_bottom_scan(self, asof: datetime | None = None) -> dict[str, object]:
        """盘后扫描全市场底部三倍量事件，并刷新池内既有事件状态。

        统一数据闸门在 `bottom_volume_signal` 之前拦截空/过期/未来日线；输出既写
        固定名最新指针，也写 `runs/<timestamp>/bottom_scan` 不可覆盖归档。
        """
        at = asof or datetime.now()
        expiry = int(self.config.get("bottom_volume", {}).get("expiry_trading_days", 60))
        refresh_counts = self.bottom_pool.refresh(self._daily, at, expiry)
        counter = DiagnosticCounter()
        freshness_counter = DiagnosticCounter()
        new_events: list[dict] = []
        for row in self.universe().to_dict("records"):
            code = str(row["代码"]).zfill(6)
            name = self._name(code, row.get("名称", ""))
            daily = self._daily(code)
            freshness = check_daily_freshness(daily, at, self.config, realtime=False)
            freshness_counter.add(freshness)
            if not freshness.passed:
                counter.add(RuleResult(freshness.decision, "bottom_volume", freshness.reason, metrics=freshness.metrics))
                continue
            risk = check_risk_filters(code, name, daily, self.config)
            if not risk.passed:
                continue
            result = bottom_volume_signal(daily, self.config)
            counter.add(result)
            if not result.passed:
                continue
            new_events.append(
                {
                    "代码": code,
                    "名称": name,
                    "事件日": str(pd.Timestamp(daily.index[-1]).date()),
                    "事件日最低": round(float(daily["low"].iloc[-1]), 3),
                    "量倍数": result.metrics.get("volume_multiple"),
                    "当日涨幅": result.metrics.get("day_change_pct"),
                    "回撤深度": result.metrics.get("drawdown_pct"),
                    "平台位置": result.metrics.get("platform_pct"),
                    "状态": "active",
                    "失效日": "",
                    "转化日": "",
                    "更新时间": at.isoformat(),
                }
            )
        self.bottom_pool.append(new_events)
        stamp = at.strftime("%Y%m%d")
        new_events_frame = pd.DataFrame(new_events)
        active_frame = self.bottom_pool.active()
        diagnostics: dict[str, object] = {**vars(counter), "freshness": vars(freshness_counter), "refresh": refresh_counts, "asof": at.isoformat()}
        # 固定/日期名文件是“最新指针”（同日重跑可被替换），逐次不可覆盖的证据在 runs/ 归档。
        paths: dict[str, object] = {
            "events_state": self.bottom_pool.path,
            "active_pool": write_csv(active_frame, self.output_dir / "bottom_pool_active.csv"),
            "new_events": write_csv(new_events_frame, self.output_dir / f"bottom_new_events_{stamp}.csv"),
            "diagnostics": write_json(diagnostics, self.output_dir / f"bottom_scan_diagnostics_{stamp}.json"),
        }
        run_dir = reserve_run_dir(self.output_dir / "runs", at.strftime("%Y%m%d_%H%M%S"), "bottom_scan")
        write_csv(new_events_frame, run_dir / "new_events.csv")
        write_csv(active_frame, run_dir / "bottom_pool_active.csv")
        write_json(diagnostics, run_dir / "diagnostics.json")
        paths["run_archive"] = run_dir
        return paths

    def run_bottom_channel(self, asof: datetime | None = None, realtime: bool = False) -> dict[str, Path]:
        """底部池小金叉通道：跳过月线多头，要求周线趋势(小金叉)+周线形态+日线买点。"""
        at = asof or datetime.now()
        expiry = int(self.config.get("bottom_volume", {}).get("expiry_trading_days", 60))
        self.bottom_pool.refresh(self._daily, at, expiry)
        active = self.bottom_pool.active()
        if active.empty:
            suffix = "bottom_realtime" if realtime else "bottom_close"
            diagnostics = {"pool_size": 0, "asof": at.isoformat(), "note": "bottom pool empty"}
            return {"diagnostics": write_json(diagnostics, self.output_dir / f"diagnostics_{suffix}.json")}
        quotes: dict[str, Quote] = {}
        errors: dict[str, str] = {}
        references: dict[str, float] = {}
        if realtime:
            provider = TencentQuoteProvider(
                int(self.config["realtime"].get("timeout_seconds", 15)),
                int(self.config["realtime"].get("batch_size", 50)),
            )
            quotes, errors = provider.fetch(active["代码"].tolist(), at)
            references = self.volume_snapshots.references(active["代码"].tolist(), at)
            self.volume_snapshots.save(quotes, at)
        suffix = "bottom_realtime" if realtime else "bottom_close"
        paths = self._run_signal_pipeline(
            active,
            at,
            quotes,
            errors,
            realtime=realtime,
            same_time_volumes=references,
            require_weekly_trend=True,
            suffix=suffix,
        )
        buy_path = paths.get("buy")
        if buy_path and Path(buy_path).exists() and Path(buy_path).stat().st_size > 0:
            try:
                frame = pd.read_csv(buy_path, dtype={"代码": str})
            except pd.errors.EmptyDataError:
                frame = pd.DataFrame()
            if not frame.empty:
                self.bottom_pool.mark_converted(frame["代码"].tolist(), at.date())
        return paths

    def _run_signal_pipeline(
        self,
        pool: pd.DataFrame,
        at: datetime,
        quotes: dict[str, Quote],
        quote_errors: dict[str, str],
        realtime: bool,
        skip_surge: bool = False,
        same_time_volumes: dict[str, float] | None = None,
        require_weekly_trend: bool = False,
        suffix: str | None = None,
    ) -> dict[str, Path]:
        same_time_volumes = same_time_volumes or {}
        surge_pass: list[dict] = []
        buy_pass: list[dict] = []
        green_pass: list[dict] = []
        rejections: list[dict] = []
        counters = {"freshness": DiagnosticCounter(), "risk": DiagnosticCounter(), "surge": DiagnosticCounter(), "buy": DiagnosticCounter()}
        if require_weekly_trend:
            counters["trend"] = DiagnosticCounter()
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
            # 前视硬闸：即使闸门以任何方式放行，下游阶段（风险/趋势/形态/买点）
            # 也只能看到 asof 时刻（含）之前的日线。
            daily = daily[pd.to_datetime(daily.index) <= pd.Timestamp(at)]
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
            if require_weekly_trend:
                trend = weekly_trend(daily, self.config)
                counters["trend"].add(trend)
                if not trend.passed:
                    rejections.append({"代码": code, "名称": name, "阶段": "trend", "原因": trend.reason, **trend.metrics})
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
        if suffix is None:
            if skip_surge:
                suffix = "board_realtime" if realtime else "board_close"
            else:
                suffix = "realtime" if realtime else "close"
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
        # 归档碰撞防护：同一秒同一 suffix 的重复运行追加序号，绝不覆盖既有归档。
        run_dir = reserve_run_dir(self.output_dir / "runs", at.strftime("%Y%m%d_%H%M%S"), str(suffix))
        for key, frame in frames.items():
            write_csv(frame, run_dir / f"{key}.csv")
        write_json(diagnostics, run_dir / "diagnostics.json")
        paths["run_archive"] = run_dir
        return paths
