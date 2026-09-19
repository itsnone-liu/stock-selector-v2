"""统一阶段入口（阶段零骨架）：阶段选择、版本目录、清单、断点、资源日志。

用法（README 惯例 PY=/root/.hermes/hermes-agent/venv/bin/python3）：

    python scripts/run_research_stage.py --stage base-check \
        --core-dir output/research/momentum_panel_v3 \
        --out output/research/lifecycle_v1 --resume

阶段注册表（对应 docs/plans/STAGED_RESEARCH_PLAN_20260919.md 提交批次）：
    base-check      第一批：底座自检（读通核心层、清单、资源日志）
    weekly-state    第二批：周线双轴（state_axes）
    pullback        第三批：回调特征与事件去重
    lifecycle       第四批：行情事件与入场回放
    entry-replay    第四批：入场回放
    posneg          第五批：正负路径分析
    chase           第五批：追高分层
    exit-replay     第六批：退出回放
    context-position 第七批：背景仓位

除 base-check 外均为占位：到对应批次再实现，防止阶段越权提前。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_selector.research import panel_store as ps  # noqa: E402

STAGES = ["base-check", "weekly-state", "pullback", "lifecycle", "entry-replay",
          "posneg", "chase", "exit-replay", "context-position"]

BATCH_OF_STAGE = {  # 阶段 -> 方案提交批次
    "base-check": "第一批", "weekly-state": "第二批", "pullback": "第三批",
    "lifecycle": "第四批", "entry-replay": "第四批", "posneg": "第五批",
    "chase": "第五批", "exit-replay": "第六批", "context-position": "第七批",
}

# (文件名, 日期键列)：episode 类表用 first_trigger_date
CORE_FILES = [("signal_panel.csv", "date"),
              ("outcome_panel.csv", "date"),
              ("universe_state_panel.csv", "date"),
              ("episode_panel.csv", "first_trigger_date"),
              ("strategy_episode_panel.csv", "first_trigger_date")]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="分阶段研究统一入口（阶段零骨架）")
    p.add_argument("--stage", required=True, choices=STAGES)
    p.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    p.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    p.add_argument("--codes-limit", type=int, default=None,
                   help="股票上限（冒烟 50 / 中等 300）")
    p.add_argument("--batch", type=int, default=100, help="每批股票数")
    p.add_argument("--workers", type=int, default=1,
                   help="并行度：阶段零仅支持单进程")
    p.add_argument("--resume", action="store_true", help="跳过已完成分区")
    p.add_argument("--summary-only", action="store_true", help="只做汇总")
    p.add_argument("--memory-limit-mb", type=int, default=2500,
                   help="峰值内存红线（2.2G 预警/2.5G 停批）")
    p.add_argument("--core-dir", default="output/research/momentum_panel_v3",
                   help="核心证据层目录")
    p.add_argument("--out", default=None, help="输出目录")
    p.add_argument("--build-parquet", action="store_true",
                   help="base-check 附带：核心层转分区 Parquet 镜像")
    p.add_argument("--rule-version", default="stage0_v1")
    p.add_argument("--config-fingerprint", default="{}")
    return p


def stage_base_check(args: argparse.Namespace) -> int:
    core = Path(args.core_dir)
    if not core.exists():
        print(f"核心层目录不存在: {core}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else core.parent / "lifecycle_v1" / "base_check"
    out.mkdir(parents=True, exist_ok=True)
    log = ps.ResourceLogger(out)
    manifest_path = out / ps.MANIFEST_NAME
    prev = ps.read_manifest(out) or {}
    fp_cache = dict(prev.get("_fingerprint_cache", {}))

    t0 = time.time()
    records = {}
    for name, date_col in CORE_FILES:
        path = core / name
        if not path.exists():
            records[name] = {"status": "missing"}
            continue
        t1 = time.time()
        head = ps.read_table(path, columns=["code", date_col],
                             start=args.start, end=args.end)
        n = len(head)
        codes = head["code"].nunique() if n else 0
        d0 = head[date_col].min() if n else ""
        d1 = head[date_col].max() if n else ""
        del head
        rec = log.batch(name, n, stage="base-check",
                        extra={"codes": int(codes), "date_min": str(d0),
                               "date_max": str(d1)})
        records[name] = {"status": "done", "rows": n, "codes": int(codes),
                         "date_col": date_col,
                         "date_min": str(d0), "date_max": str(d1),
                         "seconds": round(time.time() - t1, 2)}
        fp_cache.update({name: ps.cached_fingerprint(path, fp_cache)})

    manifest = {
        "stage": "base-check",
        "rule_version": args.rule_version,
        "config_hash": ps.config_hash(args.config_fingerprint),
        "commit": ps.git_commit(Path(__file__).resolve().parents[1]),
        "core_dir": str(core),
        "date_range": [args.start, args.end],
        "files": records,
        "runtime_s": round(time.time() - t0, 1),
        "peak_rss_mb": round(log.peak_rss_mb, 1),
        "memory_limit_mb": args.memory_limit_mb,
        "_fingerprint_cache": fp_cache,
    }
    ps.write_manifest(out, manifest)
    print(f"[base-check] 核心层读通校验完成 -> {ps.MANIFEST_NAME}")
    for name, rec in records.items():
        if rec.get("status") == "done":
            print(f"  {name}: rows={rec['rows']} codes={rec['codes']} "
                  f"range={rec['date_min']}..{rec['date_max']} "
                  f"({rec['seconds']}s)")
        else:
            print(f"  {name}: {rec['status']}")
    print(f"  峰值内存 {log.peak_rss_mb:.0f}MB / 红线 {args.memory_limit_mb}MB，"
          f"总耗时 {manifest['runtime_s']}s")

    if args.build_parquet:
        mirror = core.parent / f"{core.name}_parquet"
        print(f"[base-check] 构建分区 Parquet 镜像 -> {mirror}")
        parity_all = {}
        for name, date_col in CORE_FILES:
            src = core / name
            if not src.exists():
                continue
            t1 = time.time()
            sub = mirror / name.replace(".csv", "")
            info = ps.convert_csv_to_parquet_year(src, sub, date_col=date_col)
            log.batch(f"parquet:{name}", info["rows_parquet"], stage="base-check")
            parity_all[name] = info["parity"]
            size_mb = sum(f["bytes"] for f in info["files"].values()) / 1e6
            print(f"  {name}: csv={info['rows_csv']} pq={info['rows_parquet']} "
                  f"parity={info['parity']} {size_mb:.0f}MB ({time.time() - t1:.0f}s)")
        if not all(parity_all.values()):
            print("行数对账失败！", file=sys.stderr)
            return 4
        ps.write_manifest(mirror, {
            "converted_from": str(core),
            "rule_version": args.rule_version,
            "commit": ps.git_commit(Path(__file__).resolve().parents[1]),
            "upstream": fp_cache,
            "parity": parity_all,
            "note": "Parquet(ZSTD, year 分区) 镜像；CSV 原件仍是 source of truth",
        })
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers != 1:
        print("阶段零约束：单进程；并行待独立机器或内存确认后开放",
              file=sys.stderr)
        return 2
    if args.stage == "base-check":
        return stage_base_check(args)
    print(f"阶段 {args.stage} 属于{BATCH_OF_STAGE[args.stage]}，"
          f"阶段零只实现 base-check；按方案顺序到对应批次再实现。",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
