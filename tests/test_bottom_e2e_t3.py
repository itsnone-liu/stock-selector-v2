"""T3 fixture 端到端：盘后扫描 → 池状态 → 小金叉通道 → 归档隔离，全程 tmp_path、零网络、零 data/ 写入。

机器可复现地验证（不依赖人工叙述）：
- 底部三倍量事件落池（active）且同日重扫去重；
- --select 专用通道输出与盘后扫描输出按 suffix（bottom_close）隔离，拒绝原因逐票可查；
- runs/ 归档同秒重跑追加序号，首次归档逐字节不变；
- 整个过程不写仓库 data/ 原始数据。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from stock_selector.bottom_pool import BottomPoolStore
from stock_selector.config import load_config
from stock_selector.pipeline import SelectorPipeline


def _event_frame() -> pd.DataFrame:
    """复用 tests/test_bottom.py 的事件生成器：深回撤+低位平台+安静量+三倍量大涨。"""
    spec = importlib.util.spec_from_file_location("tb_helpers", Path(__file__).with_name("test_bottom.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("tb_helpers", module)
    spec.loader.exec_module(module)
    frame = module.make_bottom_daily()
    # 事件票成交额需过流动性闸门（20日中位≥2000万）：把量级抬到千万股
    frame["volume"] = frame["volume"] * 30
    frame.loc[frame.index[-1], "volume"] = frame["volume"].iloc[-2] * 5 * 3.4
    frame["amount"] = frame["close"] * frame["volume"]
    return frame


def _bare_pipeline(config, tmp_path: Path, frame: pd.DataFrame) -> SelectorPipeline:
    """只装配被测路径所需属性，不触碰 TDX 数据目录与凭据（与 T3 归档测试同一模式）。"""
    pipeline = SelectorPipeline.__new__(SelectorPipeline)
    pipeline.config = config
    pipeline.output_dir = tmp_path / "output"
    pipeline.output_dir.mkdir(parents=True)
    pipeline.names = {}
    pipeline.bottom_pool = BottomPoolStore(tmp_path / "state" / "bottom_volume_events.csv")
    pipeline._daily_cache = {}
    pipeline.universe = lambda: pd.DataFrame({"代码": ["600001"], "名称": ["测试票"]})
    pipeline._daily = lambda code: frame if str(code).zfill(6) == "600001" else None
    return pipeline


def _snapshot_tree(root: Path) -> dict[str, float]:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_bottom_scan_channel_fixture_e2e(tmp_path, config):
    frame = _event_frame()
    pipeline = _bare_pipeline(config, tmp_path, frame)
    repo_data = Path(__file__).resolve().parents[1] / "data"
    data_before = _snapshot_tree(repo_data)
    asof = datetime(2026, 9, 15, 15, 10)

    # 1) 盘后扫描：事件落池 active，诊断计数可追溯
    scan = pipeline.run_bottom_scan(asof=asof)
    events = pd.read_csv(scan["new_events"], dtype={"代码": str})
    assert events["代码"].tolist() == ["600001"]
    assert events.iloc[0]["状态"] == "active"
    diag = json.loads((Path(scan["run_archive"]) / "diagnostics.json").read_text(encoding="utf-8"))
    assert diag["reasons"].get("bottom_volume_launch") == 1
    assert Path(scan["run_archive"]).name == "bottom_scan"
    pool = pd.read_csv(scan["active_pool"], dtype={"代码": str})
    assert pool["代码"].tolist() == ["600001"]

    # 2) 小金叉通道（--select 语义）：事件票要求周线趋势，未达标 → 拒绝逐票可见，不崩溃
    chan = pipeline.run_bottom_channel(asof=asof, realtime=False)
    assert Path(chan["diagnostics"]).name == "diagnostics_bottom_close.json"
    chan_diag = json.loads(Path(chan["diagnostics"]).read_text(encoding="utf-8"))
    assert chan_diag["asof"] == asof.isoformat()
    if "pool_size" not in chan_diag:  # 池非空：拒绝记录必须存在
        rejections = pd.read_csv(tmp_path / "output" / "rejections_bottom_close.csv", dtype={"代码": str})
        assert "600001" in set(rejections["代码"])
        assert (rejections["阶段"] == "trend").any() or (rejections["阶段"] != "").all()

    # 3) 同秒重扫：归档追加序号，首次归档逐字节保留；同日重扫池不重复
    sentinel = Path(scan["run_archive"]) / "new_events.csv"
    before = sentinel.read_bytes()
    scan2 = pipeline.run_bottom_scan(asof=asof)
    assert Path(scan2["run_archive"]).name == "bottom_scan-2"
    assert sentinel.read_bytes() == before
    assert len(pd.read_csv(scan2["active_pool"], dtype={"代码": str})) == 1

    # 4) 全程未写仓库 data/ 原始数据
    assert _snapshot_tree(repo_data) == data_before


def test_scan_and_channel_outputs_are_mode_isolated(tmp_path, config):
    """盘后扫描与通道输出的文件名零重叠：bottom_* 归档与 bottom_close 后缀互不覆盖。"""
    frame = _event_frame()
    pipeline = _bare_pipeline(config, tmp_path, frame)
    asof = datetime(2026, 9, 15, 15, 10)
    scan = pipeline.run_bottom_scan(asof=asof)
    chan = pipeline.run_bottom_channel(asof=asof, realtime=False)
    scan_names = {p.name for p in Path(scan["run_archive"]).iterdir()}
    assert scan_names == {"new_events.csv", "bottom_pool_active.csv", "diagnostics.json"}
    # 通道诊断名带 bottom_close 后缀，与普通盘后/盘中（close/realtime）隔离
    assert Path(chan["diagnostics"]).name.startswith("diagnostics_bottom_")
    assert Path(scan["diagnostics"]).name.startswith("bottom_scan_diagnostics_")
