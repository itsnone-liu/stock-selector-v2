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
    all_names = []
    for name, batch in ps.iter_code_batches(codes, 3, resume_from=done):
        ps.mark_partition(manifest_path, name, status="done", rows=len(batch),
                          codes=batch)
        done.add(name)
        all_names.append(name)
    assert len(all_names) == 4
    # 分区名 = 序号+首尾码+集合指纹（批次身份稳定，含代码范围）
    assert all(n.startswith("batch_") for n in all_names)
    for n, b in zip(all_names, [codes[0:3], codes[3:6], codes[6:9], codes[9:10]]):
        assert b[0] in n and b[-1] in n and ps.codes_fingerprint(b) in n

    # 人为中断：第二批次标记失败
    m = json.loads(manifest_path.read_text())
    m["partitions"][all_names[1]]["status"] = "failed"
    manifest_path.write_text(json.dumps(m))

    resumed = {name for name, _ in
               ps.iter_code_batches(codes, 3, resume_from=ps.completed_partitions(
                   json.loads(manifest_path.read_text())))}
    assert resumed == {all_names[1]}  # 只重算失败分区


def test_batch_identity_changes_with_batch_size_and_codes():
    codes = [f"{i:06d}" for i in range(10)]
    names_b3 = [n for n, _ in ps.iter_code_batches(codes, 3)]
    names_b5 = [n for n, _ in ps.iter_code_batches(codes, 5)]
    # 改变批量 -> 划分不同，分区名必然不同（不会串档复用）
    assert not (set(names_b3) & set(names_b5))
    # 相同批量+清单 -> 确定性身份
    again = [n for n, _ in ps.iter_code_batches(codes, 3)]
    assert again == names_b3
    # 清单裁剪 -> 分区数减少；同名分区（相同代码集合）复用是安全的，
    # 身份=代码集合：同名必然同集合
    codes2 = codes[:-1]
    m1 = dict(ps.iter_code_batches(codes, 3))
    m2 = dict(ps.iter_code_batches(codes2, 3))
    assert len(m2) == 3  # 9 只 -> 3 批
    for n in set(m1) & set(m2):
        assert m1[n] == m2[n]
    assert sorted(c for cs in m2.values() for c in cs) == codes2


def test_validate_resume_rejects_universe_and_batch_change(tmp_path):
    codes = [f"{i:06d}" for i in range(10)]
    manifest_path = tmp_path / ps.MANIFEST_NAME
    for name, batch in ps.iter_code_batches(codes, 3):
        ps.mark_partition(manifest_path, name, status="done", codes=batch)
    manifest = json.loads(manifest_path.read_text())
    manifest["universe_fingerprint"] = ps.codes_fingerprint(codes)
    manifest_path.write_text(json.dumps(manifest))

    # 完全一致 -> 放行
    assert ps.validate_resume(json.loads(manifest_path.read_text()), codes, 3) is None
    # 清单变化 -> 拒绝
    reason = ps.validate_resume(json.loads(manifest_path.read_text()),
                                codes + ["999999"], 3)
    assert reason and "清单" in reason
    # 批量变化 -> 拒绝（旧分区名不在新划分中）
    reason = ps.validate_resume(json.loads(manifest_path.read_text()), codes, 5)
    assert reason and "--batch" in reason


def test_closure_check_missing_overlap_and_rows():
    codes = [f"{i:06d}" for i in range(9)]
    manifest = {"partitions": {
        "p1": {"status": "done", "rows": 10, "codes": codes[0:3]},
        "p2": {"status": "done", "rows": 20, "codes": codes[3:6]},
        "p3": {"status": "failed", "rows": 5, "codes": codes[6:9]},
    }}
    res = ps.closure_check(manifest, codes)
    assert res["complete"] is False
    assert res["missing_codes_head"] == codes[6:9]
    assert res["rows_out"] == 30  # 只算 done 分区
    # 修复后闭合
    manifest["partitions"]["p3"] = {"status": "done", "rows": 5, "codes": codes[6:9]}
    res = ps.closure_check(manifest, codes)
    assert res["complete"] is True
    assert res["rows_out"] == 35
    # 分区重叠 -> 不闭合（防重复落盘宣布完成）
    manifest["partitions"]["p4"] = {"status": "done", "rows": 7, "codes": codes[0:2]}
    res = ps.closure_check(manifest, codes)
    assert res["complete"] is False
    assert res["partition_overlap"]


def test_validate_resume_run_spec_gate(tmp_path):
    """续跑必须校验完整运行口径（日期/范围/规则版本/配置/数据源）。"""
    codes = [f"{i:06d}" for i in range(6)]
    manifest_path = tmp_path / ps.MANIFEST_NAME
    for name, batch in ps.iter_code_batches(codes, 3):
        ps.mark_partition(manifest_path, name, status="done", codes=batch)
    spec1 = {"result_date_range": ["2024-01-01", "2024-12-31"],
             "universe_scope": "pool", "rule_version": "v1"}
    spec2 = {"result_date_range": ["2024-01-01", "2026-09-01"],
             "universe_scope": "all", "rule_version": "v1"}
    assert ps.run_spec_hash(spec1) != ps.run_spec_hash(spec2)
    # 口径确定可比对：同 dict 同 hash，键序无关
    assert ps.run_spec_hash(dict(reversed(list(spec1.items())))) == ps.run_spec_hash(spec1)

    m = json.loads(manifest_path.read_text())
    m["universe_fingerprint"] = ps.codes_fingerprint(codes)
    m["run_spec_hash"] = ps.run_spec_hash(spec1)
    manifest_path.write_text(json.dumps(m))
    old = json.loads(manifest_path.read_text())
    # 同口径 -> 放行
    assert ps.validate_resume(old, codes, 3, spec_hash=ps.run_spec_hash(spec1)) is None
    # 换日期/换范围续跑 -> 拒绝（旧分区口径不可比）
    reason = ps.validate_resume(old, codes, 3, spec_hash=ps.run_spec_hash(spec2))
    assert reason and "运行口径" in reason
    # 旧清单无口径记录（历史版本）-> 放行不做口径强校验（向后兼容）
    m2 = dict(old)
    m2.pop("run_spec_hash")
    assert ps.validate_resume(m2, codes, 3, spec_hash=ps.run_spec_hash(spec1)) is None


def test_resolve_mirror_or_csv_integrity(tmp_path, wide_df):
    """镜像只在清单+对账+上游指纹一致时采用；否则回退 CSV 原件。"""
    core = tmp_path / "core"
    core.mkdir()
    wide = wide_df
    csv = core / "universe_state_panel.csv"
    wide.to_csv(csv, index=False)
    mirror_root = tmp_path / "core_parquet"
    mirror = mirror_root / "universe_state_panel"

    # 无镜像 -> csv
    src, mode, _ = ps.resolve_mirror_or_csv(core, "universe_state_panel.csv")
    assert mode == "csv" and src == csv
    # 建镜像但无清单 -> csv
    ps.write_partitioned_parquet(wide, mirror)
    src, mode, reason = ps.resolve_mirror_or_csv(core, "universe_state_panel.csv")
    assert mode == "csv" and "清单" in reason
    # 清单在但对账缺失 -> csv
    ps.write_manifest(mirror_root, {"parity": {}, "upstream": {}})
    _, mode, reason = ps.resolve_mirror_or_csv(core, "universe_state_panel.csv")
    assert mode == "csv" and "对账" in reason
    # 对账过但上游指纹缺失 -> csv
    ps.write_manifest(mirror_root, {
        "parity": {"universe_state_panel.csv": True},
        "upstream": {"universe_state_panel.csv": {"md5": "deadbeef"}}})
    _, mode, reason = ps.resolve_mirror_or_csv(core, "universe_state_panel.csv")
    assert mode == "csv" and "不一致" in reason
    # 全部通过 -> 镜像
    ps.write_manifest(mirror_root, {
        "parity": {"universe_state_panel.csv": True},
        "upstream": {"universe_state_panel.csv": ps.fingerprint(csv)}})
    src, mode, _ = ps.resolve_mirror_or_csv(core, "universe_state_panel.csv")
    assert mode == "parquet" and src == mirror
    # 上游 CSV 变化 -> 回退 csv
    wide.iloc[0, 0] = "999999"
    wide.to_csv(csv, index=False)
    _, mode, reason = ps.resolve_mirror_or_csv(core, "universe_state_panel.csv")
    assert mode == "csv" and "不一致" in reason


def test_paged_chunks_order_by_event_date(tmp_path):
    """分块读取事件表按 first_trigger_date 排序（不再写死 date）。"""
    rows = [{"code": f"{c:06d}", "first_trigger_date": d, "signal": 1}
            for c in (2, 1)
            for d in pd.bdate_range("2024-01-01", periods=10).strftime("%Y-%m-%d")]
    parquet_dir = tmp_path / "pq"
    ps.write_partitioned_parquet(pd.DataFrame(rows), parquet_dir,
                                 date_col="first_trigger_date")
    chunks = list(ps.read_table(parquet_dir, chunk_rows=7,
                                date_col="first_trigger_date"))
    assert len(chunks) >= 2
    seen = []
    for ch in chunks:
        pairs = list(zip(ch["code"], ch["first_trigger_date"]))
        assert pairs == sorted(pairs)  # 块内 (code, 事件日期) 有序
        seen.extend(pairs)
    keys = [(c, d) for c in ("000001", "000002")
            for d in pd.bdate_range("2024-01-01", periods=10).strftime("%Y-%m-%d")]
    assert seen == sorted(keys)  # 全局有序：code, first_trigger_date


def test_read_table_date_col_event_table(tmp_path):
    """事件表用 first_trigger_date 过滤（episode 类），不是 date。"""
    rows = [{"code": "000001", "first_trigger_date": d, "signal": i}
            for i, d in enumerate(pd.bdate_range("2024-01-01", periods=20)
                                  .strftime("%Y-%m-%d"))]
    csv = tmp_path / "events.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    mid = ps.read_table(csv, start="2024-01-15", end="2024-01-31",
                        date_col="first_trigger_date")
    assert len(mid) == 10  # 1/15..1/26 的 10 个工作日
    assert (mid["first_trigger_date"] >= "2024-01-15").all()
    parquet_dir = tmp_path / "pq"
    ps.write_partitioned_parquet(pd.DataFrame(rows), parquet_dir,
                                 date_col="first_trigger_date")
    mid_pq = ps.read_table(parquet_dir, start="2024-01-15", end="2024-01-31",
                           date_col="first_trigger_date")
    assert len(mid_pq) == 10
    # 默认 date_col=date：无该列时过滤报错/不过滤的契约不适用事件表
    with pytest.raises(Exception):
        ps.read_table(csv, start="2024-01-15", end="2024-01-31")


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
