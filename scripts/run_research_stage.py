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

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_selector.research import panel_store as ps  # noqa: E402
from stock_selector.research import state_axes as sa  # noqa: E402
from stock_selector.data.tdx import TdxStore  # noqa: E402
from stock_selector.config import load_config  # noqa: E402

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
    p.add_argument("--tdx-dir", default="/root/tdx_data", help="TDX日线根目录")
    p.add_argument("--min-history", type=int, default=130)
    p.add_argument("--universe", choices=["pool", "all"], default="pool",
                   help="weekly-state 输出范围：pool=动态月线池内（默认），"
                        "all=全市场事实+池状态标注列")
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
                             start=args.start, end=args.end, date_col=date_col)
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


def _market_days(store: TdxStore, start: str | None, end: str | None):
    cal = store.market_calendar()
    if cal is None:
        raise RuntimeError("缺少指数交易日历；正式阶段禁止用首股回退")
    return cal[(cal >= pd.Timestamp(start or cal.min())) &
               (cal <= pd.Timestamp(end or cal.max()))]


def stage_weekly_state(args: argparse.Namespace) -> int:
    """第二批：按股票流式生成周线双轴旁路表（默认动态月线池内，--universe all 可全市场）。"""
    store = TdxStore(args.tdx_dir)
    # 计算窗口带历史预热；结果窗口仍严格裁剪到 --start/--end。
    full_cal = store.market_calendar()
    if full_cal is None:
        raise RuntimeError("缺少指数交易日历；正式阶段禁止用首股回退")
    result_start = pd.Timestamp(args.start or full_cal.min())
    result_end = pd.Timestamp(args.end or full_cal.max())
    prior = full_cal[full_cal < result_start]
    warmup_days = max(args.min_history + 10, 130)
    compute_start = prior[max(0, len(prior) - warmup_days)] if len(prior) else result_start
    # 日历延伸到截止日所在周的完整计划；价格数据仍严格截到 result_end，
    # 防止周二截止被误判为短周周末完整确认。
    end_iso = result_end.isocalendar()
    same_end_week = full_cal[
        (full_cal.isocalendar().year == end_iso.year) &
        (full_cal.isocalendar().week == end_iso.week)
    ]
    compute_calendar_end = max(result_end, same_end_week.max() if len(same_end_week) else result_end)
    cal = full_cal[(full_cal >= compute_start) & (full_cal <= compute_calendar_end)]
    codes = sorted(store.list_codes())
    if args.codes_limit:
        codes = codes[:args.codes_limit]
    if not codes:
        print("没有可处理股票", file=sys.stderr)
        return 2

    # 月线池 PIT 状态来源：核心层 universe_state_panel（优先 parquet 镜像）
    core = Path(args.core_dir)
    universe_src = core.parent / f"{core.name}_parquet" / "universe_state_panel"
    if not universe_src.exists():
        universe_src = core / "universe_state_panel.csv"
    if not universe_src.exists():
        print(f"月线池状态表缺失：{universe_src}", file=sys.stderr)
        return 2
    pool_only = args.universe == "pool"

    out = Path(args.out or "output/research/lifecycle_v1/weekly_state_v1")
    parts = out / "partitions"
    manifest_path = out / ps.MANIFEST_NAME
    old = ps.read_manifest(out) or {}
    universe_fp = ps.codes_fingerprint(codes)

    # 断点续跑一致性闸门（清单指纹 + 批次划分）；变更需换新版本目录
    if args.resume:
        reason = ps.validate_resume(old, codes, args.batch)
        if reason:
            print(f"断点续跑失败：{reason}", file=sys.stderr)
            return 6
    if not args.resume and parts.exists() and any(parts.rglob("*.parquet")):
        print(f"输出目录已有分区数据：{parts}\n如需续跑加 --resume；"
              "重算请换新版本目录（版本隔离契约）。", file=sys.stderr)
        return 6

    parts.mkdir(parents=True, exist_ok=True)
    done = ps.completed_partitions(old) if args.resume else set()
    log = ps.ResourceLogger(out)
    cfg = sa.AxesConfig.from_config(load_config())
    store_info = {"stage": "weekly-state", "rule_version": sa.RULE_VERSION,
                  "tdx_dir": args.tdx_dir,
                  "compute_date_range": [str(cal.min().date()), str(cal.max().date())],
                  "result_date_range": [str(result_start.date()), str(result_end.date())],
                  "codes": len(codes), "batch_size": args.batch,
                  "universe_fingerprint": universe_fp,
                  "universe_scope": args.universe,
                  "universe_source": str(universe_src),
                  "memory_limit_mb": args.memory_limit_mb,
                  "partitions": old.get("partitions", {})}
    ps.write_manifest(out, store_info)

    r0, r1 = (result_start.strftime("%Y-%m-%d"), result_end.strftime("%Y-%m-%d"))
    for batch_name, batch_codes in ps.iter_code_batches(codes, args.batch, done):
        t0 = time.time()
        rows = []
        missing = 0
        for code in batch_codes:
            daily = store.daily(code)
            if daily is None or daily.empty:
                missing += 1
                continue
            daily = daily[(daily.index >= cal.min()) & (daily.index <= cal.max())]
            df = sa.classify_stock(code, daily, cal, cfg, min_history=args.min_history)
            if len(df):
                df = df[(df["date"] >= r0) & (df["date"] <= r1)]
                if len(df):
                    rows.append(df)
        part = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=sa.AXES_COLUMNS)
        if len(part):
            # 动态月线池 PIT 过滤/标注：join 核心层每日池状态
            upool = ps.read_table(universe_src, columns=["code", "date", "monthly_pool_state"],
                                  start=r0, end=r1, codes=batch_codes)
            part = part.merge(upool.drop_duplicates(subset=["code", "date"]),
                              on=["code", "date"], how="left")
            if pool_only:
                part = part[part["monthly_pool_state"] == "in"].reset_index(drop=True)
        else:
            part["monthly_pool_state"] = []
        target = parts / f"{batch_name}.parquet"
        if len(part):
            info = ps.write_partitioned_parquet(part, target.parent / batch_name,
                                                partition_by="year")
            output_bytes = sum(v["bytes"] for v in info["files"].values())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            output_bytes = 0
        rss_state = log.memory_guard(args.memory_limit_mb)
        log.batch(batch_name, len(part), stage="weekly-state",
                  extra={"missing": missing, "bytes": output_bytes, "guard": rss_state})
        ps.mark_partition(manifest_path, batch_name, status="done", rows=len(part),
                          seconds=time.time() - t0, rss_mb=log.peak_rss_mb,
                          missing=missing, codes=batch_codes)
        print(f"[{batch_name}] codes={len(batch_codes)} rows={len(part)} "
              f"missing={missing} rss={log.peak_rss_mb:.0f}MB")
        if rss_state == "stop":
            print("达到内存红线，停止当前阶段。续跑：相同 --batch 加 --resume；"
                  "改变批量请换新版本目录。", file=sys.stderr)
            return 5

    # 闭合检查：分区覆盖 = 预期股票全集，无重叠；rows_out = 全部 done 分区行之和
    final = ps.read_manifest(out) or store_info
    closure = ps.closure_check(final, codes)
    complete = closure["complete"]
    final.update({
        "rows_out": closure["rows_out"],
        "peak_rss_mb": log.peak_rss_mb,
        "status": "complete" if complete else "incomplete",
        "closure": closure,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    ps.write_manifest(out, final)
    print(f"[weekly-state] {'完成' if complete else '未闭合'}：codes={len(codes)} "
          f"rows={closure['rows_out']} 覆盖={closure['covered_codes']}/{len(codes)} "
          f"peak_rss={log.peak_rss_mb:.0f}MB out={out}")
    return 0 if complete else 7


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers != 1:
        print("阶段零约束：单进程；并行待独立机器或内存确认后开放",
              file=sys.stderr)
        return 2
    if args.stage == "base-check":
        return stage_base_check(args)
    if args.stage == "weekly-state":
        return stage_weekly_state(args)
    print(f"阶段 {args.stage} 属于{BATCH_OF_STAGE[args.stage]}，"
          f"当前只实现 base-check/weekly-state；按方案顺序到对应批次再实现。",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
