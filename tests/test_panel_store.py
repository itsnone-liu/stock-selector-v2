"""阶段零验收测试：对应方案 4.2 节五项通过标准。

1. 断点续跑：人为中断后只重算未完成分区
2. 列裁剪：请求少量字段时不加载整张宽表
3. 版本隔离：配置或规则改变后写入新目录，不覆盖旧产物
4. 确定性：相同输入重复运行，行数、事件编号和摘要一致
5. 资源日志：每个批次都能看到耗时、内存和输出规模
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from stock_selector.research import panel_store as ps

pytest.importorskip("duckdb")


@pytest.fixture
def wide_df() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=60).strftime("%Y-%m-%d")
    rows = []
    for code in ("000001", "600000", "300750"):
        for d in dates:
            rows.append({"code": code, "date": d, **{
                f"feat_{i}": float(i) for i in range(20)}})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 1. 断点续跑

def test_resume_skips_completed_partitions(tmp_path):
    codes = [f"{i:06d}" for i in range(10)]
    manifest_path = tmp_path / ps.MANIFEST_NAME
    done = set()
    for name, batch in ps.iter_code_batches(codes, 3, resume_from=done):
        ps.mark_partition(manifest_path, name, status="done", rows=len(batch))
        done.add(name)
    assert done == {f"batch_{i:04d}" for i in range(4)}

    # 人为中断：batch_0002 标记失败
    m = json.loads(manifest_path.read_text())
    m["partitions"]["batch_0002"]["status"] = "failed"
    manifest_path.write_text(json.dumps(m))

    resumed = {name for name, _ in
               ps.iter_code_batches(codes, 3, resume_from=ps.completed_partitions(
                   json.loads(manifest_path.read_text())))}
    assert resumed == {"batch_0002"}  # 只重算失败分区


# ---------------------------------------------------------------- 2. 列裁剪

def test_column_pruning_parquet(tmp_path, wide_df):
    ps.write_partitioned_parquet(wide_df, tmp_path / "pq")
    df = ps.read_table(tmp_path / "pq", columns=["code", "date", "feat_3"])
    assert list(df.columns) == ["code", "date", "feat_3"]
    assert len(df) == len(wide_df)


def test_column_pruning_csv_and_zst(tmp_path, wide_df):
    csv_path = tmp_path / "t.csv"
    wide_df.to_csv(csv_path, index=False)
    df = ps.read_table(csv_path, columns=["code", "feat_7"])
    assert list(df.columns) == ["code", "feat_7"]

    import subprocess
    zst = tmp_path / "t.csv.zst"
    subprocess.run(["zstd", "-q", "-3", str(csv_path), "-o", str(zst)], check=True)
    df2 = ps.read_table(zst, columns=["date", "feat_7"])
    assert list(df2.columns) == ["date", "feat_7"]
    assert df2["feat_7"].tolist() == df["feat_7"].tolist()
    # 前导零保留
    assert set(df["code"]) == {"000001", "600000", "300750"}


# ---------------------------------------------------------------- 3. 版本隔离

def test_version_isolation(tmp_path):
    v1 = ps.fresh_version_dir(tmp_path, "v1")
    ps.write_manifest(v1, {"rule_version": "r1"})
    with pytest.raises(FileExistsError):
        ps.fresh_version_dir(tmp_path, "v1")  # 已封存版本禁止覆盖
    v2 = ps.fresh_version_dir(tmp_path, "v2")
    assert v1.exists() and v2.exists()
    assert json.loads((v1 / ps.MANIFEST_NAME).read_text())["rule_version"] == "r1"


# ---------------------------------------------------------------- 4. 确定性

def test_deterministic_write_and_event_ids(tmp_path, wide_df):
    a = ps.write_partitioned_parquet(wide_df, tmp_path / "a")
    b = ps.write_partitioned_parquet(wide_df, tmp_path / "b")
    assert a["rows"] == b["rows"]
    fa = sorted(f["file"] for f in a["files"].values())
    fb = sorted(f["file"] for f in b["files"].values())
    assert fa == fb
    ra = ps.read_table(tmp_path / "a").reset_index(drop=True)
    rb = ps.read_table(tmp_path / "b").reset_index(drop=True)
    pd.testing.assert_frame_equal(ra, rb)

    e1 = ps.stable_event_id(wide_df["code"], wide_df["date"], "r1")
    e2 = ps.stable_event_id(wide_df["code"], wide_df["date"], "r1")
    assert e1 == e2                       # 同规则跨运行稳定
    e3 = ps.stable_event_id(wide_df["code"], wide_df["date"], "r2")
    assert e1 != e3                       # 规则换代则编号换代
    assert len(set(e1)) == len(e1)        # code+date 唯一 -> eid 唯一


# ---------------------------------------------------------------- 5. 资源日志

def test_resource_logger_records_batches(tmp_path):
    log = ps.ResourceLogger(tmp_path)
    rec = log.batch("batch_0000", 1234, stage="base-check")
    assert {"batch", "rows", "rss_mb", "elapsed_total_s"} <= set(rec)
    assert rec["rows"] == 1234
    lines = (tmp_path / ps.RESOURCE_LOG_NAME).read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["batch"] == "batch_0000"


def test_memory_guard_thresholds(tmp_path):
    log = ps.ResourceLogger(tmp_path)
    # 用极小阈值强制触发 warn/stop（真实内存必然大于 1MB）
    assert log.memory_guard(limit_mb=1.0) == "stop"
    assert log.memory_guard(limit_mb=1e9, warn_ratio=0.0) == "warn"


# ---------------------------------------------------------------- 端到端回读

def test_roundtrip_parquet_equals_csv(tmp_path, wide_df):
    ps.write_partitioned_parquet(wide_df, tmp_path / "pq")
    wide_df.to_csv(tmp_path / "t.csv", index=False)
    from_parquet = ps.read_table(tmp_path / "pq").sort_values(["code", "date"]).reset_index(drop=True)
    from_csv = ps.read_table(tmp_path / "t.csv").sort_values(["code", "date"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(from_parquet, from_csv)


def test_read_filters_and_chunking(tmp_path, wide_df):
    ps.write_partitioned_parquet(wide_df, tmp_path / "pq")
    df = ps.read_table(tmp_path / "pq", start="2024-02-01", end="2024-02-29",
                       codes=["600000"])
    assert (df["date"] >= "2024-02-01").all() and (df["date"] <= "2024-02-29").all()
    assert set(df["code"]) == {"600000"}

    chunks = list(ps.read_table(tmp_path / "pq", chunk_rows=50))
    assert sum(len(c) for c in chunks) == len(wide_df)
    assert all(len(c) <= 50 for c in chunks)
