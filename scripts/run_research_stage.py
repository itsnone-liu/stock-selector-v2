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
from stock_selector.decision.execution import (  # noqa: E402
    CostModel, EXECUTION_MODEL_VERSION,
)

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
    p.add_argument("--allow-dirty", action="store_true",
                   help="允许工作区有未提交修改（仅冒烟/诊断；正式运行要求干净）")
    p.add_argument("--lifecycle-dir", default="output/research/lifecycle_v1/lifecycle_stage4_v1_full",
                   help="上游生命周期目录（全量已验收）")
    p.add_argument("--pullback-dir", default="output/research/lifecycle_v1/pullback_v2",
                   help="上游回调事件目录（pullback_v2）")
    p.add_argument("--weekly-state-dir", default="output/research/lifecycle_v1/weekly_state_v1",
                   help="pullback 阶段消费的周线双轴表目录")
    return p


def _calendar_md5(tdx_dir: str) -> str | None:
    """交易日历源文件 md5（与 TdxStore.market_calendar 同寻径顺序）。"""
    for m in ("sh", "sz", "bj"):
        cand = Path(tdx_dir) / "vipdoc" / m / "lday" / "sh000001.day"
        if cand.exists():
            return ps.fingerprint(cand)["md5"]
    return None


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
    repo = Path(__file__).resolve().parents[1]
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

    # 月线池 PIT 状态来源：镜像须通过完整性校验（清单+对账+上游指纹一致），
    # 否则回退 CSV 原件（source of truth）
    core = Path(args.core_dir)
    universe_src, universe_mode, universe_reason = ps.resolve_mirror_or_csv(
        core, "universe_state_panel.csv")
    if universe_mode == "csv":
        print(f"[weekly-state] 月线池源回退 CSV：{universe_reason}", file=sys.stderr)
    else:
        print(f"[weekly-state] 月线池源用 Parquet 镜像：{universe_reason}")
    # 正式运行前提：全部受 Git 管理代码无未提交修改（不靠人工默认）。
    # 临时改动 panel_store.py / tdx.py 等也会被此闸门拦下。
    dirty = ps.git_worktree_dirty(repo)
    if dirty and not args.allow_dirty:
        print(f"工作区不干净：{len(dirty)} 处未提交修改（如 {dirty[0][:70]}）。"
              "正式运行要求先提交全部代码；冒烟/诊断可加 --allow-dirty。",
              file=sys.stderr)
        return 2

    pool_only = args.universe == "pool"
    cfg = sa.AxesConfig.from_config(load_config())
    r0, r1 = (result_start.strftime("%Y-%m-%d"), result_end.strftime("%Y-%m-%d"))
    # 交易日历源文件（与 TdxStore.market_calendar 同一寻径顺序）
    cal_file = None
    for market in ("sh", "sz", "bj"):
        cand = Path(args.tdx_dir) / "vipdoc" / market / "lday" / "sh000001.day"
        if cand.exists():
            cal_file = cand
            break
    # 运行口径：影响输出语义的全部要素（参数+代码版本+数据快照）；续跑必须一致
    run_spec = {
        "stage": "weekly-state", "rule_version": sa.RULE_VERSION,
        "result_date_range": [r0, r1],
        "universe_scope": args.universe,
        "min_history": args.min_history,
        "axes_config": {"min_volume_ratio": cfg.min_volume_ratio,
                        "veto_ratio": cfg.veto_ratio},
        "tdx_dir": args.tdx_dir,
        "universe_source": str(universe_src),
        "universe_source_md5": ps.fingerprint(core / "universe_state_panel.csv")["md5"],
        "codes_limit": args.codes_limit,
        # 代码版本：git 提交 + 计算相关文件哈希（未提交改动也会失配 -> 拒绝续跑）
        "git_commit": ps.git_commit(repo),
        "code_md5": {
            "state_axes": ps.fingerprint(repo / "src/stock_selector/research/state_axes.py")["md5"],
            "run_research_stage": ps.fingerprint(Path(__file__))["md5"],
        },
        # 数据快照：行情目录 stat 级指纹 + 全内容 md5（收尾复核基准）
        #          + 交易日历源文件 md5
        "tdx_snapshot": ps.dir_snapshot(args.tdx_dir),
        "tdx_content_md5": ps.dir_content_hash(args.tdx_dir),
        "calendar_md5": ps.fingerprint(cal_file)["md5"] if cal_file else None,
    }
    spec_hash = ps.run_spec_hash(run_spec)
    # 运行期冻结基准：月线池 stat（内容 md5 已在 run_spec.universe_source_md5）
    pool_fp0 = ps.fingerprint(core / "universe_state_panel.csv")

    def _mark_invalid(reason: str) -> int:
        m = ps.read_manifest(out) or {}
        m["status"] = "invalid_data_changed"
        m["invalid_reason"] = reason
        m["closure"] = {"complete": False, "reason": reason}
        ps.write_manifest(out, m)
        print(f"运行期间数据变化，任务作废（invalid_data_changed）：{reason}\n"
              f"禁止宣布闭合；请确认数据稳定后换新版本目录重跑。", file=sys.stderr)
        return 8

    def _assert_data_frozen() -> str | None:
        """stat 级校验：行情目录与月线池原件任一变化即返回原因。"""
        snap_now = ps.dir_snapshot(args.tdx_dir)
        if snap_now != run_spec["tdx_snapshot"]:
            return f"行情目录变化 {run_spec['tdx_snapshot']} -> {snap_now}"
        pool_now = ps.fingerprint(core / "universe_state_panel.csv")
        if (pool_now["size"], pool_now["mtime_ns"]) != (pool_fp0["size"], pool_fp0["mtime_ns"]):
            return (f"月线池原件变化 size/mtime "
                    f"{pool_fp0['size']}/{pool_fp0['mtime_ns']} -> "
                    f"{pool_now['size']}/{pool_now['mtime_ns']}")
        return None

    out = Path(args.out or "output/research/lifecycle_v1/weekly_state_v1")
    parts = out / "partitions"
    manifest_path = out / ps.MANIFEST_NAME
    old = ps.read_manifest(out) or {}
    universe_fp = ps.codes_fingerprint(codes)

    # 断点续跑一致性闸门（运行口径+清单+批次划分）；变更需换新版本目录
    if args.resume:
        reason = ps.validate_resume(old, codes, args.batch, spec_hash=spec_hash)
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
    store_info = {"stage": "weekly-state", "rule_version": sa.RULE_VERSION,
                  "tdx_dir": args.tdx_dir,
                  "compute_date_range": [str(cal.min().date()), str(cal.max().date())],
                  "result_date_range": [str(result_start.date()), str(result_end.date())],
                  "codes": len(codes), "batch_size": args.batch,
                  "universe_fingerprint": universe_fp,
                  "universe_scope": args.universe,
                  "universe_source": str(universe_src),
                  "universe_source_mode": universe_mode,
                  "run_spec": run_spec, "run_spec_hash": spec_hash,
                  "memory_limit_mb": args.memory_limit_mb,
                  "partitions": old.get("partitions", {})}
    ps.write_manifest(out, store_info)

    for batch_name, batch_codes in ps.iter_code_batches(codes, args.batch, done):
        # 运行期数据冻结校验（每批开始，stat 级，<0.5s）：
        # 行情更新程序追加日线或月线池被改写都会立即停批作废
        reason = _assert_data_frozen()
        if reason:
            return _mark_invalid(reason)
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

    # 收尾复核（全量级）：stat 级再查一次 + 行情全内容 md5 + 月线池内容 md5，
    # 抓等长度历史修正；任何变化都不得宣布闭合完成
    reason = _assert_data_frozen()
    if reason:
        return _mark_invalid(reason)
    if ps.dir_content_hash(args.tdx_dir) != run_spec["tdx_content_md5"]:
        return _mark_invalid("行情目录内容哈希变化（等长度修正/写入）")
    if ps.fingerprint(core / "universe_state_panel.csv")["md5"] != run_spec["universe_source_md5"]:
        return _mark_invalid("月线池原件内容 md5 变化")

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


def stage_pullback(args: argparse.Namespace) -> int:
    """第三批：回调特征与事件去重（消费周线双轴表，只在月线池内）。"""
    import stock_selector.research.pullback_features as pb

    cfg = pb.PullbackConfig.from_config(load_config())
    store = TdxStore(args.tdx_dir)
    repo = Path(__file__).resolve().parents[1]
    dirty = ps.git_worktree_dirty(repo)
    if dirty and not args.allow_dirty:
        print(f"工作区不干净：{len(dirty)} 处未提交修改。正式运行要求先提交；"
              "冒烟可加 --allow-dirty。", file=sys.stderr)
        return 2

    cal_all = store.market_calendar()
    r0, r1 = args.start, args.end
    result_start, result_end = pd.Timestamp(r0), pd.Timestamp(r1)
    warmup_days = 70  # platform30+high20+ATR14+缓冲
    cal_pre = cal_all[cal_all < result_start]
    compute_start = cal_pre[-warmup_days] if len(cal_pre) >= warmup_days \
        else cal_pre[0] if len(cal_pre) else result_start
    compute_end = cal_all[cal_all <= result_end][-1]
    codes = sorted(store.list_codes())
    if args.codes_limit:
        codes = codes[:args.codes_limit]
    if not codes:
        print("没有可处理股票", file=sys.stderr)
        return 2

    core = Path(args.core_dir)
    universe_src, universe_mode, universe_reason = ps.resolve_mirror_or_csv(
        core, "universe_state_panel.csv")
    print(f"[pullback] 月线池源：{universe_mode}（{universe_reason}）")

    # 上游双轴表冻结链：上游口径指纹与行数记入本阶段 run_spec，
    # 上游重跑/变更 -> 本阶段目录不可续跑
    weekly_dir = Path(args.weekly_state_dir)
    wman = ps.read_manifest(weekly_dir) or {}
    if not wman.get("run_spec_hash") or wman.get("status") != "complete":
        print(f"上游双轴表未完成或无口径指纹：{weekly_dir}", file=sys.stderr)
        return 2

    run_spec = {
        "stage": "pullback", "rule_version": pb.RULE_VERSION,
        "result_date_range": [r0, r1],
        "min_history": args.min_history,
        "pullback_config": {
            "min_volume_ratio": cfg.min_volume_ratio, "veto_ratio": cfg.veto_ratio,
            "ma_windows": list(cfg.ma_windows),
            "platform_lookback": cfg.platform_lookback,
            "platform_quantile": cfg.platform_quantile,
            "high_lookback": cfg.high_lookback,
            "max_observation_days": cfg.max_observation_days,
            "outcome_horizons": list(cfg.outcome_horizons),
            "breakdown_tolerance": cfg.breakdown_tolerance,
        },
        "tdx_dir": args.tdx_dir,
        "universe_source": str(universe_src),
        "universe_source_md5": ps.fingerprint(core / "universe_state_panel.csv")["md5"],
        "codes_limit": args.codes_limit,
        "upstream_weekly_state": {
            "dir": str(weekly_dir),
            "run_spec_hash": wman["run_spec_hash"],
            "rows_out": wman.get("rows_out"),
            "rule_version": wman.get("run_spec", {}).get("rule_version"),
        },
        "git_commit": ps.git_commit(repo),
        "code_md5": {
            "pullback_features": ps.fingerprint(
                repo / "src/stock_selector/research/pullback_features.py")["md5"],
            "run_research_stage": ps.fingerprint(Path(__file__))["md5"],
        },
        "tdx_snapshot": ps.dir_snapshot(args.tdx_dir),
        "tdx_content_md5": ps.dir_content_hash(args.tdx_dir),
        "calendar_md5": _calendar_md5(args.tdx_dir),
    }
    spec_hash = ps.run_spec_hash(run_spec)
    pool_fp0 = ps.fingerprint(core / "universe_state_panel.csv")

    out = Path(args.out or "output/research/lifecycle_v1/pullback_v1")
    parts_ev = out / "events" / "partitions"
    parts_dly = out / "daily" / "partitions"
    for d in (parts_ev, parts_dly):
        d.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "MANIFEST.json"
    old = ps.read_manifest(out) or {}
    if old.get("partitions"):
        reason = ps.validate_resume(old, codes, args.batch, spec_hash=spec_hash)
        if reason:
            print(f"拒绝续跑：{reason}", file=sys.stderr)
            return 6
    done = ps.completed_partitions(old) if args.resume else set()

    def _mark_invalid(reason_: str) -> int:
        m = ps.read_manifest(out) or {}
        m["status"] = "invalid_data_changed"
        m["invalid_reason"] = reason_
        m["closure"] = {"complete": False, "reason": reason_}
        ps.write_manifest(out, m)
        print(f"运行期间数据变化，任务作废（invalid_data_changed）：{reason_}\n"
              f"禁止宣布闭合；请确认数据稳定后换新版本目录重跑。", file=sys.stderr)
        return 8

    def _assert_data_frozen() -> str | None:
        snap_now = ps.dir_snapshot(args.tdx_dir)
        if snap_now != run_spec["tdx_snapshot"]:
            return f"行情目录变化 {run_spec['tdx_snapshot']} -> {snap_now}"
        pool_now = ps.fingerprint(core / "universe_state_panel.csv")
        if (pool_now["size"], pool_now["mtime_ns"]) != (pool_fp0["size"], pool_fp0["mtime_ns"]):
            return "月线池原件变化 size/mtime"
        wnow = ps.read_manifest(weekly_dir) or {}
        if wnow.get("run_spec_hash") != wman["run_spec_hash"]:
            return "上游双轴表口径指纹变化"
        return None

    log = ps.ResourceLogger(out)
    store_info = {
        "stage": "pullback", "rule_version": pb.RULE_VERSION,
        "tdx_dir": args.tdx_dir,
        "result_date_range": [r0, r1],
        "codes": len(codes), "batch_size": args.batch,
        "universe_source": str(universe_src),
        "run_spec": run_spec, "run_spec_hash": spec_hash,
        "memory_limit_mb": args.memory_limit_mb,
        "upstream_weekly_state": run_spec["upstream_weekly_state"],
        "partitions": old.get("partitions", {}),
    }
    ps.write_manifest(out, store_info)

    weekly_src = weekly_dir / "partitions"
    for batch_name, batch_codes in ps.iter_code_batches(codes, args.batch, done):
        reason = _assert_data_frozen()
        if reason:
            return _mark_invalid(reason)
        t0 = time.time()
        # 池状态与双轴按批读取（一次 join 语义，逐股转映射）
        upool = ps.read_table(universe_src, columns=["code", "date", "monthly_pool_state"],
                              codes=batch_codes)
        wax = ps.read_table(weekly_src, columns=["code", "date", "trend_structure",
                                                 "current_momentum"],
                            codes=batch_codes)
        pool_by_code: dict = {}
        for rec in upool.drop_duplicates(subset=["code", "date"]).itertuples(index=False):
            pool_by_code.setdefault(rec.code, {})[rec.date] = \
                (rec.monthly_pool_state == "in")
        # 双轴行列表（date, trend, momentum）升序：当日收盘状态当日可用（<=）
        week_by_code: dict = {}
        for rec in (wax.drop_duplicates(subset=["code", "date"])
                    .sort_values(["code", "date"]).itertuples(index=False)):
            week_by_code.setdefault(rec.code, []).append(
                (pd.Timestamp(rec.date), rec.trend_structure, rec.current_momentum))

        ev_rows, dly_rows, missing = [], [], 0
        for code in batch_codes:
            daily = store.daily(code)
            if daily is None or daily.empty:
                missing += 1
                continue
            daily = daily[(daily.index >= compute_start) & (daily.index <= compute_end)]
            if daily.empty:
                missing += 1
                continue
            ev, dly = pb.classify_pullback(
                code, daily, week_by_code.get(code, {}), pool_by_code.get(code, {}), cfg)
            if len(ev):
                ev = ev[(ev["first_day"] >= r0) & (ev["first_day"] <= r1)]
                if len(ev):
                    ev_rows.append(ev)
            if len(dly):
                dly = dly[(dly["date"] >= r0) & (dly["date"] <= r1)]
                if len(dly):
                    dly_rows.append(dly)
        part_ev = pd.concat(ev_rows, ignore_index=True) if ev_rows else \
            pd.DataFrame(columns=pb.EVENT_COLUMNS)
        part_dly = pd.concat(dly_rows, ignore_index=True) if dly_rows else \
            pd.DataFrame(columns=pb.DAILY_COLUMNS)
        bytes_out = 0
        if len(part_ev):
            info = ps.write_partitioned_parquet(
                part_ev, parts_ev / batch_name, partition_by="year",
                date_col="first_day")
            bytes_out += sum(v["bytes"] for v in info["files"].values())
        else:
            (parts_ev / batch_name).mkdir(parents=True, exist_ok=True)
        if len(part_dly):
            info = ps.write_partitioned_parquet(
                part_dly, parts_dly / batch_name, partition_by="year")
            bytes_out += sum(v["bytes"] for v in info["files"].values())
        else:
            (parts_dly / batch_name).mkdir(parents=True, exist_ok=True)
        rss_state = log.memory_guard(args.memory_limit_mb)
        log.batch(batch_name, len(part_ev), stage="pullback",
                  extra={"missing": missing, "bytes": bytes_out, "guard": rss_state,
                         "rows_daily": len(part_dly)})
        ps.mark_partition(manifest_path, batch_name, status="done",
                          rows=len(part_ev), seconds=time.time() - t0,
                          rss_mb=log.peak_rss_mb, missing=missing,
                          codes=batch_codes,
                          rows_daily=len(part_dly))
        print(f"[{batch_name}] codes={len(batch_codes)} events={len(part_ev)} "
              f"daily={len(part_dly)} missing={missing} rss={log.peak_rss_mb:.0f}MB")
        if rss_state == "stop":
            print("达到内存红线，停止当前阶段。续跑：相同 --batch 加 --resume；"
                  "改变批量请换新版本目录。", file=sys.stderr)
            return 5

    reason = _assert_data_frozen()
    if reason:
        return _mark_invalid(reason)
    if ps.dir_content_hash(args.tdx_dir) != run_spec["tdx_content_md5"]:
        return _mark_invalid("行情目录内容哈希变化（等长度修正/写入）")
    if ps.fingerprint(core / "universe_state_panel.csv")["md5"] != run_spec["universe_source_md5"]:
        return _mark_invalid("月线池原件内容 md5 变化")
    wnow = ps.read_manifest(weekly_dir) or {}
    if wnow.get("run_spec_hash") != wman["run_spec_hash"]:
        return _mark_invalid("上游双轴表口径指纹变化")

    final = ps.read_manifest(out) or store_info
    closure = ps.closure_check(final, codes)
    complete = closure["complete"]
    total_daily = sum(p.get("rows_daily", 0) for p in final.get("partitions", {}).values())
    final.update({
        "rows_out": closure["rows_out"],
        "rows_daily": total_daily,
        "peak_rss_mb": log.peak_rss_mb,
        "status": "complete" if complete else "incomplete",
        "closure": closure,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    ps.write_manifest(out, final)
    print(f"[pullback] {'完成' if complete else '未闭合'}：codes={len(codes)} "
          f"events={closure['rows_out']} daily={total_daily} "
          f"覆盖={closure['covered_codes']}/{len(codes)} peak_rss={log.peak_rss_mb:.0f}MB "
          f"out={out}")
    return 0 if complete else 7


def stage_lifecycle(args: argparse.Namespace) -> int:
    """第四批(上)：行情生命周期事实（消费周线双轴 + pullback_v2 事件）。

    只生成生命周期事实表，不做入场回放（entry-replay 独立提交）。
    池状态保持三态（in/out/None），pool_gap 依赖 None 与 out 的区分。
    """
    import stock_selector.research.lifecycle as lc

    cfg = lc.LifecycleConfig.from_config(load_config())
    store = TdxStore(args.tdx_dir)
    repo = Path(__file__).resolve().parents[1]
    dirty = ps.git_worktree_dirty(repo)
    if dirty and not args.allow_dirty:
        print(f"工作区不干净：{len(dirty)} 处未提交修改。正式运行要求先提交；"
              "冒烟可加 --allow-dirty。", file=sys.stderr)
        return 2

    cal_all = store.market_calendar()
    r0, r1 = args.start, args.end
    result_start, result_end = pd.Timestamp(r0), pd.Timestamp(r1)
    # warmup >= max_observation_days(120) + breakout_lookback(20)，加缓冲 150：
    # 窗口前已启动的生命周期用于恢复状态，但 anchor_day 在窗口前的不进样本
    warmup_days = 150
    cal_pre = cal_all[cal_all < result_start]
    compute_start = cal_pre[-warmup_days] if len(cal_pre) >= warmup_days \
        else cal_pre[0] if len(cal_pre) else result_start
    compute_end = cal_all[cal_all <= result_end][-1]
    codes = sorted(store.list_codes())
    if args.codes_limit:
        codes = codes[:args.codes_limit]
    if not codes:
        print("没有可处理股票", file=sys.stderr)
        return 2

    core = Path(args.core_dir)
    universe_src, universe_mode, universe_reason = ps.resolve_mirror_or_csv(
        core, "universe_state_panel.csv")
    print(f"[lifecycle] 月线池源：{universe_mode}（{universe_reason}）")

    # 上游冻结链：双轴表 + 回调事件（版本三元组）
    weekly_dir = Path(args.weekly_state_dir)
    wman = ps.read_manifest(weekly_dir) or {}
    pb_dir = Path(args.pullback_dir)
    pman = ps.read_manifest(pb_dir) or {}
    # 上游冻结三元组：完整且指纹精确匹配（防换目录跑错口径）
    expected_upstream = {
        "weekly_state": ("e2cf0918238fc95c",
                         wman.get("run_spec_hash")),
        "pullback": ("68cad4022bec6a8b",
                     pman.get("run_spec_hash")),
    }
    for tag, man, d in (("weekly_state", wman, weekly_dir),
                        ("pullback", pman, pb_dir)):
        if not man.get("run_spec_hash") or man.get("status") != "complete":
            print(f"上游{tag}未完成或无口径指纹：{d}", file=sys.stderr)
            return 2
        want, got = expected_upstream[tag]
        if got != want:
            print(f"上游{tag}口径指纹不符：期望 {want}，实际 {got}；"
                  f"拒绝运行（{d}）", file=sys.stderr)
            return 2

    run_spec = {
        "stage": "lifecycle", "rule_version": lc.RULE_VERSION,
        "result_date_range": [r0, r1],
        "lifecycle_config": {
            "breakout_lookback": cfg.breakout_lookback,
            "max_observation_days": cfg.max_observation_days,
            "pool_gap_tolerance": cfg.pool_gap_tolerance,
            "week_trend_ok": list(lc.WEEK_TREND_OK),
        },
        "tdx_dir": args.tdx_dir,
        "universe_source": str(universe_src),
        "universe_source_md5": ps.fingerprint(core / "universe_state_panel.csv")["md5"],
        "codes_limit": args.codes_limit,
        "upstream_weekly_state": {
            "dir": str(weekly_dir),
            "run_spec_hash": wman["run_spec_hash"],
            "rows_out": wman.get("rows_out"),
            "rule_version": wman.get("run_spec", {}).get("rule_version"),
        },
        "upstream_pullback": {
            "dir": str(pb_dir),
            "run_spec_hash": pman["run_spec_hash"],
            "rows_out": pman.get("rows_out"),
            "rule_version": pman.get("run_spec", {}).get("rule_version"),
            "event_rule_version": "pullback_stage2_v1",
            "outcome_contract_version": "right_censored_v2",
        },
        "git_commit": ps.git_commit(repo),
        "code_md5": {
            "lifecycle": ps.fingerprint(
                repo / "src/stock_selector/research/lifecycle.py")["md5"],
            "run_research_stage": ps.fingerprint(Path(__file__))["md5"],
        },
        "tdx_snapshot": ps.dir_snapshot(args.tdx_dir),
        "tdx_content_md5": ps.dir_content_hash(args.tdx_dir),
        "calendar_md5": _calendar_md5(args.tdx_dir),
    }
    spec_hash = ps.run_spec_hash(run_spec)
    pool_fp0 = ps.fingerprint(core / "universe_state_panel.csv")

    out = Path(args.out or "output/research/lifecycle_v1/lifecycle_v1")
    parts = out / "partitions"
    parts.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "MANIFEST.json"
    old = ps.read_manifest(out) or {}
    if old.get("partitions"):
        reason = ps.validate_resume(old, codes, args.batch, spec_hash=spec_hash)
        if reason:
            print(f"拒绝续跑：{reason}", file=sys.stderr)
            return 6
    done = ps.completed_partitions(old) if args.resume else set()

    def _mark_invalid(reason_: str) -> int:
        m = ps.read_manifest(out) or {}
        m["status"] = "invalid_data_changed"
        m["invalid_reason"] = reason_
        m["closure"] = {"complete": False, "reason": reason_}
        ps.write_manifest(out, m)
        print(f"运行期间数据变化，任务作废（invalid_data_changed）：{reason_}\n"
              f"禁止宣布闭合；请确认数据稳定后换新版本目录重跑。", file=sys.stderr)
        return 8

    def _assert_data_frozen() -> str | None:
        snap_now = ps.dir_snapshot(args.tdx_dir)
        if snap_now != run_spec["tdx_snapshot"]:
            return f"行情目录变化 {run_spec['tdx_snapshot']} -> {snap_now}"
        pool_now = ps.fingerprint(core / "universe_state_panel.csv")
        if (pool_now["size"], pool_now["mtime_ns"]) != (pool_fp0["size"], pool_fp0["mtime_ns"]):
            return "月线池原件变化 size/mtime"
        wnow = ps.read_manifest(weekly_dir) or {}
        if wnow.get("run_spec_hash") != wman["run_spec_hash"]:
            return "上游双轴表口径指纹变化"
        pnow = ps.read_manifest(pb_dir) or {}
        if pnow.get("run_spec_hash") != pman["run_spec_hash"]:
            return "上游回调事件口径指纹变化"
        return None

    log = ps.ResourceLogger(out)
    store_info = {
        "stage": "lifecycle", "rule_version": lc.RULE_VERSION,
        "tdx_dir": args.tdx_dir,
        "result_date_range": [r0, r1],
        "codes": len(codes), "batch_size": args.batch,
        "universe_source": str(universe_src),
        "run_spec": run_spec, "run_spec_hash": spec_hash,
        "memory_limit_mb": args.memory_limit_mb,
        "upstream_weekly_state": run_spec["upstream_weekly_state"],
        "upstream_pullback": run_spec["upstream_pullback"],
        "partitions": old.get("partitions", {}),
    }
    ps.write_manifest(out, store_info)

    weekly_src = weekly_dir / "partitions"
    pb_ev_src = pb_dir / "events" / "partitions"
    for batch_name, batch_codes in ps.iter_code_batches(codes, args.batch, done):
        reason = _assert_data_frozen()
        if reason:
            return _mark_invalid(reason)
        t0 = time.time()
        upool = ps.read_table(universe_src, columns=["code", "date", "monthly_pool_state"],
                              codes=batch_codes)
        wax = ps.read_table(weekly_src, columns=["code", "date", "trend_structure",
                                                 "current_momentum"],
                            codes=batch_codes)
        pev = ps.read_table(pb_ev_src, columns=["code", "event_id", "first_day", "end_day"],
                            codes=batch_codes)
        # 池状态保持三态：in / out / None（pool_gap 依赖 None 与 out 区分）
        pool_by_code: dict = {}
        for rec in upool.drop_duplicates(subset=["code", "date"]).itertuples(index=False):
            v = rec.monthly_pool_state
            pool_by_code.setdefault(rec.code, {})[rec.date] = (
                "in" if v == "in" else "out" if v == "out" else None)
        week_by_code: dict = {}
        for rec in (wax.drop_duplicates(subset=["code", "date"])
                    .sort_values(["code", "date"]).itertuples(index=False)):
            week_by_code.setdefault(rec.code, []).append(
                (pd.Timestamp(rec.date), rec.trend_structure, rec.current_momentum))
        pb_by_code: dict = {}
        for rec in (pev.drop_duplicates(subset=["event_id"])
                    .sort_values(["first_day"]).itertuples(index=False)):
            pb_by_code.setdefault(rec.code, []).append(
                {"event_id": rec.event_id,
                 "first_day": rec.first_day, "end_day": rec.end_day})

        rows, missing = [], 0
        for code in batch_codes:
            daily = store.daily(code)
            if daily is None or daily.empty:
                missing += 1
                continue
            daily = daily[(daily.index >= compute_start) & (daily.index <= compute_end)]
            if daily.empty:
                missing += 1
                continue
            lcs = lc.classify_lifecycle(
                code, daily, week_by_code.get(code, []),
                pool_by_code.get(code, {}), pb_by_code.get(code, []), cfg)
            if len(lcs):
                lcs = lcs[(lcs["anchor_day"] >= r0) & (lcs["anchor_day"] <= r1)]
                if len(lcs):
                    rows.append(lcs)
        part = pd.concat(rows, ignore_index=True) if rows else \
            pd.DataFrame(columns=lc.LIFECYCLE_COLUMNS)
        bytes_out = 0
        if len(part):
            info = ps.write_partitioned_parquet(
                part, parts / batch_name, partition_by="year",
                date_col="anchor_day")
            bytes_out = sum(v["bytes"] for v in info["files"].values())
        else:
            (parts / batch_name).mkdir(parents=True, exist_ok=True)
        rss_state = log.memory_guard(args.memory_limit_mb)
        log.batch(batch_name, len(part), stage="lifecycle",
                  extra={"missing": missing, "bytes": bytes_out, "guard": rss_state})
        ps.mark_partition(manifest_path, batch_name, status="done",
                          rows=len(part), seconds=time.time() - t0,
                          rss_mb=log.peak_rss_mb, missing=missing,
                          codes=batch_codes)
        print(f"[{batch_name}] codes={len(batch_codes)} lifecycles={len(part)} "
              f"missing={missing} rss={log.peak_rss_mb:.0f}MB")
        if rss_state == "stop":
            print("达到内存红线，停止当前阶段。续跑：相同 --batch 加 --resume；"
                  "改变批量请换新版本目录。", file=sys.stderr)
            return 5

    reason = _assert_data_frozen()
    if reason:
        return _mark_invalid(reason)
    if ps.dir_content_hash(args.tdx_dir) != run_spec["tdx_content_md5"]:
        return _mark_invalid("行情目录内容哈希变化（等长度修正/写入）")
    if ps.fingerprint(core / "universe_state_panel.csv")["md5"] != run_spec["universe_source_md5"]:
        return _mark_invalid("月线池原件内容 md5 变化")

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
    print(f"[lifecycle] {'完成' if complete else '未闭合'}：codes={len(codes)} "
          f"lifecycles={closure['rows_out']} "
          f"覆盖={closure['covered_codes']}/{len(codes)} peak_rss={log.peak_rss_mb:.0f}MB "
          f"out={out}")
    return 0 if complete else 7


def stage_entry_replay(args: argparse.Namespace) -> int:
    """第四批(下)：四种入场策略回放（消费 lifecycle，不重建生命周期）。

    双价格口径：raw_price 信号/成交/涨跌停；收益层当前为未复权工程口径
    （return_quality=unadjusted_exploratory），仅限工程验证，禁止据此
    比较策略优劣或调整 3.5% 上限；全量需复权口径确认后另行放行。
    """
    import stock_selector.research.entry_replay as er

    cfg = er.ReplayConfig.from_config(load_config())
    cost = CostModel()
    store = TdxStore(args.tdx_dir)
    repo = Path(__file__).resolve().parents[1]
    dirty = ps.git_worktree_dirty(repo)
    if dirty and not args.allow_dirty:
        print(f"工作区不干净：{len(dirty)} 处未提交修改。正式运行要求先提交；"
              "冒烟可加 --allow-dirty。", file=sys.stderr)
        return 2

    r0, r1 = args.start, args.end
    result_end = pd.Timestamp(r1)
    codes = sorted(store.list_codes())
    if args.codes_limit:
        codes = codes[:args.codes_limit]
    if not codes:
        print("没有可处理股票", file=sys.stderr)
        return 2

    core = Path(args.core_dir)
    weekly_dir = Path(args.weekly_state_dir)
    pb_dir = Path(args.pullback_dir)
    lc_dir = Path(args.lifecycle_dir)
    lman = ps.read_manifest(lc_dir) or {}
    pman = ps.read_manifest(pb_dir) or {}
    EXPECTED_LIFECYCLE = "7f2c8dda08801d27"
    if (not lman.get("run_spec_hash") or lman.get("status") != "complete"
            or lman.get("run_spec_hash") != EXPECTED_LIFECYCLE):
        print(f"上游 lifecycle 指纹不符：期望 {EXPECTED_LIFECYCLE}，"
              f"实际 {lman.get('run_spec_hash')}（{lc_dir}）", file=sys.stderr)
        return 2
    if not pman.get("run_spec_hash") or pman.get("status") != "complete":
        print(f"上游 pullback 未完成：{pb_dir}", file=sys.stderr)
        return 2

    cal_all = store.market_calendar()
    compute_end = cal_all[cal_all <= result_end][-1]
    run_spec = {
        "stage": "entry-replay", "rule_version": er.RULE_VERSION,
        "result_date_range": [r0, r1],
        "replay_config": {"chase_gain_cap_pct": cfg.chase_gain_cap_pct,
                          "staged_tranches": [list(t) for t in cfg.staged_tranches]},
        "capital": er.CAPITAL,
        "horizons": list(er.HORIZONS),
        "execution_model_version": EXECUTION_MODEL_VERSION,
        "return_quality": er.RETURN_QUALITY,
        "limitation": er.LIMITATION,
        "tdx_dir": args.tdx_dir,
        "codes_limit": args.codes_limit,
        "upstream_lifecycle": {
            "dir": str(lc_dir), "run_spec_hash": lman["run_spec_hash"],
            "rows_out": lman.get("rows_out"),
        },
        "upstream_pullback": {
            "dir": str(pb_dir), "run_spec_hash": pman["run_spec_hash"],
            "event_rule_version": "pullback_stage2_v1",
            "outcome_contract_version": "right_censored_v2",
        },
        "git_commit": ps.git_commit(repo),
        "code_md5": {
            "entry_replay": ps.fingerprint(
                repo / "src/stock_selector/research/entry_replay.py")["md5"],
            "run_research_stage": ps.fingerprint(Path(__file__))["md5"],
        },
        "tdx_snapshot": ps.dir_snapshot(args.tdx_dir),
        "tdx_content_md5": ps.dir_content_hash(args.tdx_dir),
        "calendar_md5": _calendar_md5(args.tdx_dir),
    }
    spec_hash = ps.run_spec_hash(run_spec)

    out = Path(args.out or "output/research/lifecycle_v1/entry_replay_v1")
    parts = out / "partitions"
    parts.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "MANIFEST.json"
    old = ps.read_manifest(out) or {}
    if old.get("partitions"):
        reason = ps.validate_resume(old, codes, args.batch, spec_hash=spec_hash)
        if reason:
            print(f"拒绝续跑：{reason}", file=sys.stderr)
            return 6
    done = ps.completed_partitions(old) if args.resume else set()

    def _mark_invalid(reason_: str) -> int:
        m = ps.read_manifest(out) or {}
        m["status"] = "invalid_data_changed"
        m["invalid_reason"] = reason_
        m["closure"] = {"complete": False, "reason": reason_}
        ps.write_manifest(out, m)
        print(f"运行期间数据变化，任务作废（invalid_data_changed）：{reason_}",
              file=sys.stderr)
        return 8

    def _assert_data_frozen() -> str | None:
        if ps.dir_snapshot(args.tdx_dir) != run_spec["tdx_snapshot"]:
            return "行情目录变化"
        lnow = ps.read_manifest(lc_dir) or {}
        if lnow.get("run_spec_hash") != lman["run_spec_hash"]:
            return "上游 lifecycle 口径指纹变化"
        return None

    log = ps.ResourceLogger(out)
    store_info = {
        "stage": "entry-replay", "rule_version": er.RULE_VERSION,
        "tdx_dir": args.tdx_dir, "result_date_range": [r0, r1],
        "codes": len(codes), "batch_size": args.batch,
        "run_spec": run_spec, "run_spec_hash": spec_hash,
        "memory_limit_mb": args.memory_limit_mb,
        "return_quality": er.RETURN_QUALITY,
        "partitions": old.get("partitions", {}),
    }
    ps.write_manifest(out, store_info)

    lc_src = lc_dir / "partitions"
    pb_ev_src = pb_dir / "events" / "partitions"
    pb_dly_src = pb_dir / "daily" / "partitions"
    for batch_name, batch_codes in ps.iter_code_batches(codes, args.batch, done):
        reason = _assert_data_frozen()
        if reason:
            return _mark_invalid(reason)
        t0 = time.time()
        lcs = ps.read_table(lc_src, columns=["code", "lifecycle_id",
                                             "anchor_day", "breakout_day",
                                             "reattack_days", "end_day",
                                             "end_reason", "right_censored"],
                            codes=batch_codes)
        pev = ps.read_table(pb_ev_src, columns=["code", "event_id", "first_day",
                                                "end_day", "stabilization_day"],
                            codes=batch_codes)
        pdly = ps.read_table(pb_dly_src, columns=["code", "event_id", "date",
                                                  "shrink_volume"],
                             codes=batch_codes)
        lc_by: dict = {}
        for rec in lcs.itertuples(index=False):
            lc_by.setdefault(rec.code, []).append({
                "lifecycle_id": rec.lifecycle_id, "anchor_day": rec.anchor_day,
                "breakout_day": rec.breakout_day,
                "reattack_days": rec.reattack_days, "end_day": rec.end_day,
                "end_reason": rec.end_reason,
                "right_censored": bool(rec.right_censored)})
        pev_by: dict = {}
        for rec in pev.itertuples(index=False):
            pev_by.setdefault(rec.code, []).append({
                "event_id": rec.event_id, "first_day": rec.first_day,
                "end_day": rec.end_day,
                "stabilization_day": getattr(rec, "stabilization_day", None)})
        pdly_by: dict = {}
        for rec in pdly.itertuples(index=False):
            pdly_by.setdefault(rec.code, []).append(
                {"event_id": rec.event_id, "date": rec.date,
                 "shrink_volume": bool(rec.shrink_volume)})

        rows, missing = [], 0
        for code in batch_codes:
            daily = store.daily(code)
            if daily is None or daily.empty:
                missing += 1
                continue
            daily = daily[daily.index <= compute_end]
            if daily.empty or code not in lc_by:
                continue
            ldf = pd.DataFrame(lc_by[code])
            ev = er.replay_entries(
                code, ldf, daily, pev_by.get(code, []),
                pd.DataFrame(pdly_by.get(code, [])), cfg, cost)
            if len(ev):
                ev = ev[(ev["signal_day"] >= r0) & (ev["signal_day"] <= r1)]
                if len(ev):
                    rows.append(ev)
        part = pd.concat(rows, ignore_index=True) if rows else \
            pd.DataFrame(columns=er.ENTRY_REPLAY_COLUMNS)
        bytes_out = 0
        if len(part):
            info = ps.write_partitioned_parquet(
                part, parts / batch_name, partition_by="year",
                date_col="signal_day")
            bytes_out = sum(v["bytes"] for v in info["files"].values())
        else:
            (parts / batch_name).mkdir(parents=True, exist_ok=True)
        rss_state = log.memory_guard(args.memory_limit_mb)
        log.batch(batch_name, len(part), stage="entry-replay",
                  extra={"missing": missing, "bytes": bytes_out, "guard": rss_state})
        ps.mark_partition(manifest_path, batch_name, status="done",
                          rows=len(part), seconds=time.time() - t0,
                          rss_mb=log.peak_rss_mb, missing=missing,
                          codes=batch_codes)
        print(f"[{batch_name}] codes={len(batch_codes)} rows={len(part)} "
              f"missing={missing} rss={log.peak_rss_mb:.0f}MB")
        if rss_state == "stop":
            print("达到内存红线，停止当前阶段。", file=sys.stderr)
            return 5

    reason = _assert_data_frozen()
    if reason:
        return _mark_invalid(reason)
    if ps.dir_content_hash(args.tdx_dir) != run_spec["tdx_content_md5"]:
        return _mark_invalid("行情目录内容哈希变化")

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
    print(f"[entry-replay] {'完成' if complete else '未闭合'}：codes={len(codes)} "
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
    if args.stage == "pullback":
        return stage_pullback(args)
    if args.stage == "lifecycle":
        return stage_lifecycle(args)
    if args.stage == "entry-replay":
        return stage_entry_replay(args)
    print(f"阶段 {args.stage} 属于{BATCH_OF_STAGE[args.stage]}，"
          f"当前只实现 base-check/weekly-state；按方案顺序到对应批次再实现。",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
