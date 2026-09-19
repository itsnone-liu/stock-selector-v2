"""统一存储接口（阶段零）：格式隐藏、分区读取、列裁剪、断点续跑、运行清单。

设计约束（见 docs/plans/STAGED_RESEARCH_PLAN_20260919.md 第二节）：
- 分析代码只 import 本模块，不直接读文件；后端切换（csv/csv.zst/parquet）不改业务逻辑。
- 所有读取支持：所需列裁剪、日期区间、股票代码过滤、分块迭代。
- 产物目录必须带 MANIFEST（上游指纹、规则版本、配置指纹、代码提交、分区状态、资源日志）。
- 上游指纹一致时已完成分区直接复用；只补算缺失分区。
- 写出默认 Parquet(ZSTD) 分区，禁止再生成 13GB 单体宽表。

运行环境：python>=3.11（README 惯例 PY=/root/.hermes/hermes-agent/venv/bin/python3），
duckdb>=1.5 为可选 research 依赖（pyproject [project.optional-dependencies].research）。
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd

try:  # parquet 后端；缺失时自动降级 csv/zst
    import duckdb

    HAS_DUCKDB = True
except Exception:  # pragma: no cover - 环境缺依赖时仍可跑 csv 路径
    HAS_DUCKDB = False

MANIFEST_NAME = "MANIFEST.json"
RESOURCE_LOG_NAME = "resource_log.jsonl"

# 股票代码含前导零，任何后端读取都强制字符串，防止 000001 -> 1
DEFAULT_STR_COLUMNS = ("code",)


# --------------------------------------------------------------------------
# 指纹与清单
# --------------------------------------------------------------------------

def fingerprint(path: str | Path) -> dict:
    """文件指纹：全量 md5（一次性成本，清单缓存后按 size+mtime 复用）。"""
    p = Path(path)
    h = hashlib.md5()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    st = p.stat()
    return {"path": str(p), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "md5": h.hexdigest()}


def cached_fingerprint(path: str | Path, cache: dict) -> dict:
    key = str(path)
    st = os.stat(key)
    hit = cache.get(key)
    if hit and hit["size"] == st.st_size and hit["mtime_ns"] == st.st_mtime_ns:
        return hit
    fp = fingerprint(key)
    cache[key] = fp
    return fp


def git_commit(repo_dir: str | Path = ".") -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def write_manifest(out_dir: str | Path, manifest: dict) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return path


def read_manifest(out_dir: str | Path) -> dict | None:
    path = Path(out_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text())


def completed_partitions(manifest: dict | None) -> set[str]:
    """断点续跑：已完成且指纹未失效的分区名集合。"""
    if not manifest:
        return set()
    return {name for name, rec in manifest.get("partitions", {}).items()
            if rec.get("status") == "done"}


def fresh_version_dir(base_out: str | Path, version: str) -> Path:
    """版本隔离：状态/规则/配置改变时写新版本目录，绝不覆盖上一版。"""
    out = Path(base_out) / version
    if out.exists() and (out / MANIFEST_NAME).exists():
        raise FileExistsError(
            f"版本目录已存在且已封存: {out}；规则或配置改变请递增 version，"
            f"禁止覆盖上一版产物")
    out.mkdir(parents=True, exist_ok=True)
    return out


# --------------------------------------------------------------------------
# 资源日志与内存红线
# --------------------------------------------------------------------------

def _rss_mb() -> float:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except Exception:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3


class ResourceLogger:
    """每批记录耗时、常驻内存、行数与磁盘增长（jsonl 追加 + 峰值汇总）。"""

    def __init__(self, out_dir: str | Path):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.path = self.out / RESOURCE_LOG_NAME
        self.t0 = time.time()
        self.peak_rss_mb = 0.0

    def batch(self, name: str, rows: int, *, stage: str = "",
              extra: dict | None = None) -> dict:
        rss = _rss_mb()
        self.peak_rss_mb = max(self.peak_rss_mb, rss)
        rec = {"batch": name, "stage": stage, "rows": rows,
               "rss_mb": round(rss, 1), "elapsed_total_s": round(time.time() - self.t0, 1),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if extra:
            rec.update(extra)
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def memory_guard(self, limit_mb: float, warn_ratio: float = 0.88) -> str:
        """返回 ok | warn | stop；stop 时调用方应停当前分区并降低批量。"""
        rss = _rss_mb()
        self.peak_rss_mb = max(self.peak_rss_mb, rss)
        if rss >= limit_mb:
            return "stop"
        if rss >= limit_mb * warn_ratio:
            return "warn"
        return "ok"


# --------------------------------------------------------------------------
# 读取：统一后端
# --------------------------------------------------------------------------

def resolve_backend(source: str | Path) -> str:
    p = Path(source)
    if p.is_dir():
        names = list(p.rglob("*.parquet"))
        if names:
            return "parquet_dir"
        names = list(p.rglob("*.csv.zst")) + list(p.rglob("*.zst"))
        if names:
            return "csvzst_dir"
        names = list(p.rglob("*.csv"))
        if names:
            return "csv_dir"
        raise FileNotFoundError(f"目录中无可识别数据文件: {p}")
    suffix = "".join(p.suffixes[-2:]) if p.suffixes else ""
    if p.suffix == ".parquet":
        return "parquet"
    if suffix.endswith(".zst"):
        return "csvzst"
    if p.suffix == ".csv":
        return "csv"
    raise ValueError(f"无法识别的存储格式: {p}")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_source(backend: str, path: Path) -> str:
    if backend == "parquet":
        return f"read_parquet('{path.as_posix()}')"
    if backend == "parquet_dir":
        files = sorted(x.as_posix() for x in path.rglob("*.parquet"))
        inner = ", ".join(f"'{f}'" for f in files)
        return f"read_parquet([{inner}])"
    if backend == "csv":
        return f"read_csv_auto('{path.as_posix()}', types={{'code': 'VARCHAR'}})"
    raise ValueError(f"duckdb 不处理后端 {backend}")


def _iter_csv_like(path: Path, columns: Sequence[str] | None,
                   chunk_rows: int | None) -> Iterator[pd.DataFrame]:
    """csv / csv.zst 流式读取（zstd -dc 管道，零额外依赖）。"""
    usecols = list(columns) if columns else None
    if path.suffix == ".zst":
        proc = subprocess.Popen(["zstd", "-dc", "-q", str(path)],
                                stdout=subprocess.PIPE)
        assert proc.stdout is not None
        reader = pd.read_csv(proc.stdout, chunksize=chunk_rows or (1 << 30),
                             usecols=usecols, dtype={c: str for c in DEFAULT_STR_COLUMNS})
        for chunk in reader:
            yield chunk
        proc.stdout.close()
        if proc.wait() != 0:
            raise RuntimeError(f"zstd 解压失败: {path}")
    else:
        for chunk in pd.read_csv(path, chunksize=chunk_rows or (1 << 30),
                                 usecols=usecols,
                                 dtype={c: str for c in DEFAULT_STR_COLUMNS}):
            yield chunk


def read_table(source: str | Path, *,
               columns: Sequence[str] | None = None,
               start: str | None = None, end: str | None = None,
               codes: Sequence[str] | None = None,
               chunk_rows: int | None = None,
               date_col: str = "date") -> pd.DataFrame | Iterator[pd.DataFrame]:
    """统一读取入口。

    - columns: 列裁剪（parquet 走投影下推；csv 走 usecols，均不整帧加载）
    - start/end: 闭区间日期过滤（YYYY-MM-DD），作用于 date_col 指定的
      日期列（默认 "date"；episode 类事件表传 first_trigger_date）
    - codes: 股票代码过滤
    - chunk_rows: 给定则返回迭代器（分块流式），否则返回单个 DataFrame
    """
    p = Path(source)
    backend = resolve_backend(p)

    if backend in ("csv", "csvzst"):
        it = _iter_csv_like(p, columns, chunk_rows)
        if chunk_rows:
            return _filtered_chunks(it, start, end, codes, date_col)
        df = next(it)
        return _filter_frame(df, start, end, codes, date_col)

    if not HAS_DUCKDB:
        raise RuntimeError("parquet 后端需要 duckdb（pip 安装 duckdb>=1.5）")

    if backend in ("csv_dir", "csvzst_dir"):
        # 目录混合 csv/zst：逐文件走 pandas 路径后拼接（研究数据目录通常同构）
        frames = []
        for f in sorted(p.rglob("*.csv")) + sorted(p.rglob("*.csv.zst")):
            frames.append(read_table(f, columns=columns, start=start, end=end,
                                     codes=codes, date_col=date_col))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return _chunked_or_single(df, chunk_rows)

    # parquet / parquet_dir
    if chunk_rows:
        # 分页生成器自持连接（惰性求值，不能被 finally 提前关闭）
        return _paged_chunks_source(_sql_source(backend, p), columns,
                                    _where_sql(start, end, codes, date_col),
                                    chunk_rows, _norm_col=date_col)
    con = duckdb.connect()
    try:
        sel = ", ".join(_quote_ident(c) for c in columns) if columns else "*"
        where = _where_sql(start, end, codes, date_col)
        q = f"SELECT {sel} FROM {_sql_source(backend, p)}"
        if where:
            q += " WHERE " + where
        return _normalize_dates(con.execute(q).df(), date_col)
    finally:
        con.close()


def _normalize_dates(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """接口契约：日期键列统一为 ISO 字符串（与 CSV 路径一致），后端无感知。"""
    if date_col in df.columns and not pd.api.types.is_object_dtype(df[date_col]):
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    return df


def _where_sql(start, end, codes, date_col: str = "date") -> str:
    parts = []
    if start or end:
        lo = start or "0000-01-01"
        hi = end or "9999-12-31"
        parts.append(f"{_quote_ident(date_col)} BETWEEN '{lo}' AND '{hi}'")
    if codes:
        vals = ", ".join("'" + c.replace("'", "''") + "'"
                         for c in dict.fromkeys(codes))
        parts.append(f"code IN ({vals})")
    return " AND ".join(parts)


def _paged_chunks_source(source_sql: str, columns, where_sql: str,
                         n: int, _norm_col: str = "date") -> Iterator[pd.DataFrame]:
    con = duckdb.connect()
    try:
        sel = ", ".join(_quote_ident(c) for c in columns) if columns else "*"
        q = f"SELECT {sel} FROM {source_sql}"
        if where_sql:
            q += " WHERE " + where_sql
        q += " ORDER BY code, date"
        offset = 0
        while True:
            df = _normalize_dates(
                con.execute(f"{q} LIMIT {n} OFFSET {offset}").df(),
                _norm_col)
            if not len(df):
                return
            yield df
            offset += n
    finally:
        con.close()


def _filter_frame(df: pd.DataFrame, start, end, codes,
                  date_col: str = "date") -> pd.DataFrame:
    if start or end:
        lo = start or "0000-01-01"
        hi = end or "9999-12-31"
        df = df[(df[date_col] >= lo) & (df[date_col] <= hi)]
    if codes:
        df = df[df["code"].isin(set(codes))]
    return df.reset_index(drop=True)


def _filtered_chunks(it, start, end, codes, date_col: str = "date") -> Iterator[pd.DataFrame]:
    for chunk in it:
        out = _filter_frame(chunk, start, end, codes, date_col)
        if len(out):
            yield out


def _chunked_or_single(df, chunk_rows):
    if not chunk_rows:
        return df
    return _simple_chunks(df, chunk_rows)


def _simple_chunks(df: pd.DataFrame, n: int) -> Iterator[pd.DataFrame]:
    for i in range(0, len(df), n):
        yield df.iloc[i:i + n]


# --------------------------------------------------------------------------
# 写出：分区 Parquet（确定性）
# --------------------------------------------------------------------------

def write_partitioned_parquet(df: pd.DataFrame, out_dir: str | Path, *,
                              partition_by: str = "year",
                              date_col: str = "date",
                              sort_by: Sequence[str] | None = None,
                              row_group_size: int = 200_000,
                              single_file_max_gb: float = 2.0) -> dict:
    """按年份分区写出 Parquet(ZSTD)。确定性：列序=df 列序，行序=sort_by。

    date_col 指定分区键日期列（默认 "date"；事件表可传 first_trigger_date）。
    single_file_max_gb 为软约束：单分区超出时按股票代码段再切分，
    禁止生成超限单体文件。
    """
    if not HAS_DUCKDB:
        raise RuntimeError("写出 parquet 需要 duckdb")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if partition_by != "year":
        raise ValueError("阶段零仅支持 year 分区")
    if date_col not in df.columns:
        raise ValueError(f"分区键需要 {date_col} 列")
    if sort_by is None:
        sort_by = ("code", date_col)

    work = df.copy()
    work[date_col] = work[date_col].astype(str)
    work["_year"] = work[date_col].str.slice(0, 4)
    work = work.sort_values(list(sort_by)).reset_index(drop=True)

    written = {}
    con = duckdb.connect()
    try:
        for year in sorted(work["_year"].unique()):
            part = work[work["_year"] == year].drop(columns=["_year"])
            target = out / f"year={year}.parquet"
            _split_and_write(con, part, target, row_group_size,
                             single_file_max_gb, written, year)
    finally:
        con.close()
    return {"rows": int(len(work)), "files": written}


def _split_and_write(con, part: pd.DataFrame, target: Path,
                     row_group_size: int, max_gb: float,
                     written: dict, label: str) -> None:
    # 先整体写临时文件，超限时按代码段二分重切（软约束，保守估算后处理）
    tmp = target.with_suffix(".parquet.tmp")
    con.register("_part", part)
    con.execute(
        f"COPY (SELECT * FROM _part) TO '{tmp.as_posix()}' "
        f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {row_group_size})")
    con.unregister("_part")
    size_gb = tmp.stat().st_size / 1e9
    if size_gb > max_gb:
        # 按代码首字母段拆分为多文件，保持行序稳定
        tmp.unlink()
        part = part.sort_values("code").reset_index(drop=True)
        buckets = sorted({c[:2] for c in part["code"]})
        per = max(1, -(-len(buckets) // max(1, int(size_gb / max_gb) + 1)))
        for i in range(0, len(buckets), per):
            seg = buckets[i:i + per]
            sub = part[part["code"].str.slice(0, 2).isin(seg)]
            f = out_file = target.with_name(
                f"{target.stem}_seg{i // per:02d}{target.suffix}")
            con.register("_sub", sub)
            con.execute(
                f"COPY (SELECT * FROM _sub) TO '{f.as_posix()}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {row_group_size})")
            con.unregister("_sub")
            written[f"{label}/seg{i // per:02d}"] = {
                "file": f.name, "rows": int(len(sub)),
                "bytes": f.stat().st_size}
    else:
        tmp.rename(target)
        written[label] = {"file": target.name, "rows": int(len(part)),
                          "bytes": target.stat().st_size}


# --------------------------------------------------------------------------
# CSV -> 分区 Parquet 镜像（duckdb 流式，不经 pandas 物化，低内存）
# --------------------------------------------------------------------------

def convert_csv_to_parquet_year(csv_path: str | Path, out_dir: str | Path, *,
                                date_col: str = "date",
                                row_group_size: int = 200_000) -> dict:
    """核心层 CSV 原件转 year 分区 Parquet 镜像（ZSTD）。

    duckdb COPY 流式执行，内存占用远低于 pandas 往返；返回行数对账信息。
    date_col 允许 episode 类表用 first_trigger_date 作为分区键。
    """
    if not HAS_DUCKDB:
        raise RuntimeError("转换需要 duckdb")
    src = Path(csv_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        years = [r[0] for r in con.execute(
            f"SELECT DISTINCT substr(CAST({_quote_ident(date_col)} AS VARCHAR),"
            f" 1, 4) FROM read_csv_auto("
            f"'{src.as_posix()}', types={{'code': 'VARCHAR'}}) ORDER BY 1").fetchall()]
        total_csv = con.execute(
            f"SELECT count(*) FROM read_csv_auto('{src.as_posix()}', "
            f"types={{'code': 'VARCHAR'}})").fetchone()[0]
        written = {}
        for year in years:
            target = out / f"year={year}.parquet"
            con.execute(
                f"COPY (SELECT * FROM read_csv_auto('{src.as_posix()}', "
                f"types={{'code': 'VARCHAR'}}) "
                f"WHERE substr(CAST({_quote_ident(date_col)} AS VARCHAR), 1, 4)"
                f" = '{year}') "
                f"TO '{target.as_posix()}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {row_group_size})")
            written[str(year)] = {"file": target.name,
                                  "bytes": target.stat().st_size}
        total_pq = sum(
            con.execute(f"SELECT count(*) FROM read_parquet("
                        f"'{(out / f'year={y}.parquet').as_posix()}')").fetchone()[0]
            for y in years)
        return {"source": str(src), "rows_csv": int(total_csv),
                "rows_parquet": int(total_pq),
                "parity": total_csv == total_pq, "files": written}
    finally:
        con.close()


# --------------------------------------------------------------------------
# 事件编号（稳定、跨运行一致）
# --------------------------------------------------------------------------

def stable_event_id(codes: Iterable[str], dates: Iterable[str],
                    rule_version: str) -> list[str]:
    """eid = md5(code|date|rule_version)[:16]；rule_version 变化则编号换代，
    旧编号永远可追溯，不被复用。"""
    return [hashlib.md5(f"{c}|{d}|{rule_version}".encode()).hexdigest()[:16]
            for c, d in zip(codes, dates)]


# --------------------------------------------------------------------------
# 股票批次与断点续跑
# --------------------------------------------------------------------------

def codes_fingerprint(codes: Sequence[str]) -> str:
    """批次代码集合指纹：排序去重后 md5[:12]，作为分区身份。"""
    joined = ",".join(sorted(dict.fromkeys(codes)))
    return hashlib.md5(joined.encode()).hexdigest()[:12]


def iter_code_batches(codes: Sequence[str], batch_size: int,
                      resume_from: set[str] | None = None
                      ) -> Iterator[tuple[str, list[str]]]:
    """股票分批；分区名 = 序号+首尾码+集合指纹。

    批次身份由代码集合决定而非序号：改变 --batch 重新划分后，
    旧序号分区不会与新批次混淆（不同集合指纹必然不同名）。
    resume_from 匹配的是完整分区名，因此只有集合完全一致时才复用。
    """
    ordered = sorted(dict.fromkeys(codes))
    n_batches = (len(ordered) + batch_size - 1) // batch_size
    for i in range(n_batches):
        chunk = ordered[i * batch_size:(i + 1) * batch_size]
        name = f"batch_{i:04d}_{chunk[0]}-{chunk[-1]}_{codes_fingerprint(chunk)}"
        if resume_from and name in resume_from:
            continue
        yield name, chunk


def mark_partition(manifest_path: Path, name: str, *, status: str,
                   rows: int = 0, seconds: float = 0.0, rss_mb: float = 0.0,
                   codes: Sequence[str] | None = None,
                   **extra) -> None:
    """原子更新清单中的分区状态（读-改-写，单进程约定下安全）。

    codes 记录该批次的股票清单，闭合检查据此验证覆盖无遗漏。
    """
    m = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"partitions": {}}
    rec = {"status": status, "rows": rows, "seconds": round(seconds, 2),
           "rss_mb": round(rss_mb, 1), **extra}
    if codes is not None:
        rec["codes"] = sorted(codes)
        rec["n_codes"] = len(rec["codes"])
    m.setdefault("partitions", {})[name] = rec
    manifest_path.write_text(json.dumps(m, ensure_ascii=False, indent=2))


def validate_resume(old: dict, codes: Sequence[str], batch_size: int) -> str | None:
    """断点续跑一致性闸门：通过返回 None，否则返回拒绝原因。

    - 股票清单指纹必须与上次运行一致（universe_fingerprint）
    - 已完成分区名必须全部落在当前批次划分内（--batch 不变）
    """
    if not old.get("partitions"):
        return None
    fp = codes_fingerprint(codes)
    if old.get("universe_fingerprint") != fp:
        return ("股票清单与上次运行不同（universe_fingerprint 不匹配）；"
                "续跑要求相同股票范围，清单变更请换新版本目录重跑")
    current = {name for name, _ in iter_code_batches(codes, batch_size)}
    stale = set(old["partitions"]) - current
    if stale:
        return (f"{len(stale)} 个已完成分区不属于当前批次划分（--batch 或清单顺序变化）；"
                "请保持与上次相同的 --batch 续跑，或换新版本目录重跑")
    return None


def closure_check(manifest: dict, expected_codes: Sequence[str]) -> dict:
    """闭合检查：done 分区代码并集 = 预期全集且两两不重叠。

    rows_out 取全部 done 分区行之和（而非本次运行累计），
    防止续跑后清单错误宣布完成。
    """
    done_rec = {n: r for n, r in manifest.get("partitions", {}).items()
                if r.get("status") == "done"}
    covered: set[str] = set()
    overlap: set[str] = set()
    for rec in done_rec.values():
        cs = set(rec.get("codes", []))
        overlap |= covered & cs
        covered |= cs
    expected = set(expected_codes)
    missing = sorted(expected - covered)
    rows_total = sum(int(r.get("rows", 0)) for r in done_rec.values())
    complete = not missing and not overlap
    return {
        "expected_codes": len(expected),
        "covered_codes": len(covered & expected),
        "missing_count": len(missing),
        "missing_codes_head": missing[:20],
        "partition_overlap": sorted(overlap)[:20],
        "done_partitions": len(done_rec),
        "rows_out": rows_total,
        "complete": complete,
    }
