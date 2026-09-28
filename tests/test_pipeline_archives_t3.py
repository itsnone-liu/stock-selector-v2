"""T3：run_trends 显式 asof + 统一数据闸门，以及 runs/ 不可覆盖归档（确定性、无网络）。

覆盖：
- run_trends 在策略之前拦截 过期 / 未来 / 未排序帧隐藏未来行 / asof 当日更晚时刻戳 / 空数据；
- 闸门不会误伤新鲜数据（月线阶段仍真实执行）；
- run_trends 与 run_bottom_scan 的 runs/<timestamp>/ 归档同名碰撞时追加序号，
  既有归档内容逐字节保留（output.reserve_run_dir 的原子占位语义）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from conftest import make_daily
from stock_selector.bottom_pool import BottomPoolStore
from stock_selector.output import reserve_run_dir
from stock_selector.pipeline import SelectorPipeline


def _bare_pipeline(config, tmp_path: Path, frames: dict[str, pd.DataFrame | None]) -> SelectorPipeline:
    """只装配被测路径所需的属性，不触碰 TDX 数据目录与凭据。"""
    pipeline = SelectorPipeline.__new__(SelectorPipeline)
    pipeline.config = config
    pipeline.output_dir = tmp_path
    pipeline.names = {}
    pipeline._daily = lambda code: frames.get(str(code).zfill(6))
    pipeline.bottom_pool = BottomPoolStore(tmp_path / "state" / "bottom_volume_events.csv")
    codes = sorted(frames)
    pipeline.universe = lambda: pd.DataFrame({"代码": codes, "名称": ["" for _ in codes]})
    return pipeline


def _read_csv(path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype={"代码": str})
    except pd.errors.EmptyDataError:  # 空结果可能写成 0 字节
        return pd.DataFrame()


def _trends_diag(paths: dict) -> dict:
    return json.loads(Path(paths["diagnostics"]).read_text(encoding="utf-8"))


def _archive_diag(paths: dict) -> dict:
    return json.loads((Path(paths["run_archive"]) / "diagnostics.json").read_text(encoding="utf-8"))


def _hidden_future_frame() -> pd.DataFrame:
    """未来行藏在帧中间、末行是过去日期（未排序索引）——只按末行判断会漏掉。"""
    base = make_daily(periods=260, end="2026-09-14")
    future_row = base.iloc[-1].copy()
    future_row.name = pd.Timestamp("2026-09-20")
    frame = pd.concat([base.iloc[[-1]].copy(), future_row.to_frame().T, base.iloc[[-3]]])
    assert pd.to_datetime(frame.index)[-1] < pd.Timestamp("2026-09-20")
    return frame


def _bottom_daily(volume_multiple: float = 4.0) -> pd.DataFrame:
    n = 300
    idx = pd.bdate_range(end="2026-09-15", periods=n)
    close = np.concatenate([np.full(60, 10.0), np.linspace(10, 6.2, 40), np.full(200, 6.2)])
    open_ = close * 0.999
    high = np.concatenate([np.full(60, 10.2), np.linspace(10.2, 6.3, 40), np.full(200, 6.3)])
    low = close * 0.99  # 先按原始收盘算低点，再改写事件日 OHLC（与 SPEC §9 语义一致）
    vol = np.full(n, 1_000_000.0)
    close[-1], open_[-1], low[-1], high[-1] = 6.6, 6.15, 6.1, 6.65
    vol[-1] = volume_multiple * 1_000_000.0
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol, "amount": close * vol},
        index=idx,
    )


# ---- run_trends：统一数据闸门在策略之前 ----


def test_run_trends_blocks_stale_daily_before_strategy(config, tmp_path):
    pipeline = _bare_pipeline(config, tmp_path, {"600001": make_daily(periods=260, end="2026-09-01")})
    paths = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    diagnostics = _trends_diag(paths)
    assert diagnostics["monthly"]["freshness"]["reasons"].get("daily_data_stale") == 1
    assert diagnostics["monthly"]["total"] == 1
    assert diagnostics["monthly"]["passed"] == 0  # 未进入 monthly_trend
    assert diagnostics["weekly"]["total"] == 0  # 月线阶段未通过，不进入周线阶段
    rejections = _read_csv(paths["monthly_rejections"])
    assert list(rejections["原因"]) == ["daily_data_stale"]
    assert _read_csv(paths["monthly"]).empty


def test_run_trends_blocks_future_daily_before_strategy(config, tmp_path):
    pipeline = _bare_pipeline(config, tmp_path, {"600001": make_daily(periods=260, end="2026-09-16")})
    paths = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    diagnostics = _trends_diag(paths)
    assert diagnostics["monthly"]["freshness"]["reasons"].get("future_daily_bar") == 1
    assert diagnostics["monthly"]["freshness"]["errors"] == 1
    assert diagnostics["monthly"]["passed"] == 0
    assert _read_csv(paths["monthly"]).empty


def test_run_trends_blocks_unsorted_hidden_future_row(config, tmp_path):
    pipeline = _bare_pipeline(config, tmp_path, {"600001": _hidden_future_frame()})
    paths = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    diagnostics = _trends_diag(paths)
    assert diagnostics["monthly"]["freshness"]["reasons"].get("future_daily_bar") == 1
    assert diagnostics["monthly"]["passed"] == 0


def test_run_trends_blocks_same_day_later_timestamp_row(config, tmp_path):
    frame = make_daily(periods=260, end="2026-09-15")
    idx = list(frame.index)
    idx[-1] = pd.Timestamp("2026-09-15 14:30")  # asof 当日更晚时刻戳 = 未来数据
    frame.index = pd.DatetimeIndex(idx)
    pipeline = _bare_pipeline(config, tmp_path, {"600001": frame})
    intraday = pipeline.run_trends(asof=datetime(2026, 9, 15, 10, 30))
    assert _trends_diag(intraday)["monthly"]["freshness"]["reasons"].get("future_daily_bar") == 1
    after_close = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    assert _trends_diag(after_close)["monthly"]["freshness"]["reasons"].get("future_daily_bar") is None


def test_run_trends_blocks_empty_and_missing_daily(config, tmp_path):
    pipeline = _bare_pipeline(config, tmp_path, {"600001": pd.DataFrame(), "600002": None})
    paths = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    diagnostics = _trends_diag(paths)
    assert diagnostics["monthly"]["freshness"]["reasons"].get("missing_daily_data") == 2
    assert diagnostics["monthly"]["passed"] == 0
    assert _read_csv(paths["monthly"]).empty


def test_run_trends_gate_does_not_block_fresh_data(config, tmp_path):
    """反向保护：闸门不得误杀新鲜数据，月线阶段必须真实执行。"""
    pipeline = _bare_pipeline(config, tmp_path, {"600001": make_daily(periods=480, end="2026-09-15", drift=0.12)})
    paths = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    diagnostics = _trends_diag(paths)
    assert diagnostics["monthly"]["freshness"]["reasons"].get("daily_data_fresh") == 1
    assert diagnostics["monthly"]["total"] == 1
    assert diagnostics["monthly"]["reasons"].get("monthly_ma_bull") == 1


# ---- runs/ 归档：collision-safe、不覆盖 ----


def test_run_trends_keeps_spec_canonical_filenames(config, tmp_path):
    """SPEC §12 / CLI 契约：固定输出名仍是 monthly_pool.csv 与 weekly_pool.csv
    （after-close 默认吃 output/weekly_pool.csv，改名会静默断链）。"""
    pipeline = _bare_pipeline(config, tmp_path, {"600001": make_daily(periods=480, end="2026-09-15", drift=0.12)})
    paths = pipeline.run_trends(asof=datetime(2026, 9, 15, 15, 10))
    assert Path(paths["monthly"]).name == "monthly_pool.csv"
    assert Path(paths["weekly"]).name == "weekly_pool.csv"
    assert Path(paths["monthly_rejections"]).name == "monthly_rejections.csv"
    assert Path(paths["weekly_rejections"]).name == "weekly_rejections.csv"
    assert Path(paths["diagnostics"]).name == "trend_diagnostics.json"
    for name in ("monthly_pool.csv", "weekly_pool.csv", "trend_diagnostics.json"):
        assert (tmp_path / name).exists()
    assert not (tmp_path / "monthly.csv").exists()  # 不得出现改名后的旁路产物


def test_run_trends_archive_is_collision_safe(config, tmp_path):
    pipeline = _bare_pipeline(config, tmp_path, {"600001": make_daily(periods=480, end="2026-09-15", drift=0.12)})
    same_moment = datetime(2026, 9, 15, 15, 10)
    first = pipeline.run_trends(asof=same_moment)
    archive1 = Path(first["run_archive"])
    assert archive1.name == "trends"
    assert archive1.parent.parent == tmp_path / "runs"
    assert archive1.parent.name == "20260915_151000"
    for name in ("monthly_pool.csv", "weekly_pool.csv", "monthly_rejections.csv", "weekly_rejections.csv", "diagnostics.json"):
        assert (archive1 / name).exists()
    sentinel = archive1 / "keep.txt"
    sentinel.write_text("first-run-evidence", encoding="utf-8")
    before = (archive1 / "diagnostics.json").read_bytes()

    second = pipeline.run_trends(asof=same_moment)
    archive2 = Path(second["run_archive"])
    assert archive2 != archive1
    assert archive2.name == "trends-2"  # 同秒不覆盖，序号追加
    assert sentinel.read_text(encoding="utf-8") == "first-run-evidence"
    assert (archive1 / "diagnostics.json").read_bytes() == before
    assert (archive2 / "diagnostics.json").exists()


def test_run_trends_archive_records_explicit_asof(config, tmp_path):
    """显式 asof 同时决定闸门口径与归档时间戳，而不是跟随数据或当前时间。"""
    pipeline = _bare_pipeline(config, tmp_path, {"600001": make_daily(periods=480, end="2026-09-15", drift=0.12)})
    at = datetime(2026, 9, 15, 15, 10)
    paths = pipeline.run_trends(asof=at)
    assert Path(paths["run_archive"]).parent.name == "20260915_151000"
    assert _trends_diag(paths)["asof"] == at.isoformat()
    assert _archive_diag(paths)["asof"] == at.isoformat()


def test_run_bottom_scan_archive_is_collision_safe(config, tmp_path):
    pipeline = _bare_pipeline(config, tmp_path, {"600001": _bottom_daily()})
    same_moment = datetime(2026, 9, 15, 15, 10)
    first = pipeline.run_bottom_scan(asof=same_moment)
    archive1 = Path(first["run_archive"])
    assert archive1.name == "bottom_scan"
    assert archive1.parent.name == "20260915_151000"
    for name in ("new_events.csv", "bottom_pool_active.csv", "diagnostics.json"):
        assert (archive1 / name).exists()
    events = _read_csv(archive1 / "new_events.csv")
    assert events["代码"].tolist() == ["600001"]
    assert json.loads((archive1 / "diagnostics.json").read_text(encoding="utf-8"))["asof"] == same_moment.isoformat()
    sentinel = archive1 / "keep.txt"
    sentinel.write_text("first-run-evidence", encoding="utf-8")

    second = pipeline.run_bottom_scan(asof=same_moment)
    archive2 = Path(second["run_archive"])
    assert archive2.name == "bottom_scan-2"
    assert sentinel.read_text(encoding="utf-8") == "first-run-evidence"
    # SPEC §12 的固定/日期名保持“最新指针”语义，逐次不可覆盖的证据在归档里
    assert Path(first["new_events"]).name == "bottom_new_events_20260915.csv"
    assert Path(first["active_pool"]).name == "bottom_pool_active.csv"
    assert (archive2 / "diagnostics.json").exists()


def test_run_bottom_scan_blocks_future_daily_before_signal(config, tmp_path):
    future = _bottom_daily()
    future.index = pd.DatetimeIndex(list(future.index[:-1]) + [pd.Timestamp("2026-09-16")])
    pipeline = _bare_pipeline(config, tmp_path, {"600001": future})
    paths = pipeline.run_bottom_scan(asof=datetime(2026, 9, 15, 15, 10))
    diagnostics = json.loads(Path(paths["diagnostics"]).read_text(encoding="utf-8"))
    assert diagnostics["freshness"]["reasons"].get("future_daily_bar") == 1
    assert diagnostics["reasons"].get("bottom_volume_launch") is None  # 未进入信号
    assert _read_csv(Path(paths["new_events"])).empty
    assert pipeline.bottom_pool.load().empty  # 未来事件不得落池
    assert (Path(paths["run_archive"]) / "new_events.csv").exists()


def test_reserve_run_dir_is_collision_safe(tmp_path):
    root = tmp_path / "runs"
    first = reserve_run_dir(root, "20260915_151000", "trends")
    second = reserve_run_dir(root, "20260915_151000", "trends")
    third = reserve_run_dir(root, "20260915_151000", "trends")
    assert [first.name, second.name, third.name] == ["trends", "trends-2", "trends-3"]
    assert first.parent == second.parent == third.parent == root / "20260915_151000"
    # 占位目录可立即写入；重复占位不会复用同一目录
    (first / "a.txt").write_text("x", encoding="utf-8")
    assert (first / "a.txt").read_text(encoding="utf-8") == "x"
    assert not (second / "a.txt").exists()
