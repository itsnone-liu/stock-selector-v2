#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3_gate_b_ref60.py — Gate B：ref60 冻结口径 vs lifecycle 既有突破规则。

B0  基线复现：以冻结配置(breakout_lookback=20)在当前 TDX 上重跑冻结
    classify_lifecycle，与 lifecycle_stage4_v1_full 全表逐列比对。
    任何漂移 ⇒ 数据变动影响结果，B2 的 diff 无法归因于规则 ⇒ Gate B FAIL。
B1  事件内检查（V1 冻结 ref60：复权、前60个有效观测、严格>）：27,422 全量。
B1b 事件内检查（lifecycle 原生：TDX 未复权、前20日、严格>）：应全过
    （数据读取与冻结管线一致的校验）。
B2  全域重构：同一冻结锚定机制、breakout_lookback=60（TDX 未复权，
    管线原生价格约定），重构 breakout 事件集，与 27,422 做
    intersection / old_only / new_only + 同生命周期日偏移。
差异只报告，不修改事件宇宙；Gate B 判 FAIL 时等待人工裁定。
"""
from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402

from stock_selector.research import panel_store as ps  # noqa: E402
from stock_selector.data.tdx import TdxStore  # noqa: E402
import stock_selector.research.lifecycle as lc  # noqa: E402
from stock_selector.research import t3_v2 as tv  # noqa: E402

OUT = ROOT / "output/research/t3_v2"
LIFE_DIR = ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full"
WEEKLY_DIR = ROOT / "output/research/lifecycle_v1/weekly_state_v1"
PB_DIR = ROOT / "output/research/lifecycle_v1/pullback_v2"
UNIVERSE_SRC = ROOT / "output/research/momentum_panel_v3_parquet/universe_state_panel"
R0, R1 = "2024-01-02", "2026-09-01"
WARMUP = 150


def run_variants() -> tuple[pd.DataFrame, pd.DataFrame]:
    """单批输入同时跑 lookback=20 与 lookback=60 两个变体。"""
    store = TdxStore("/root/tdx_data")
    cal_all = store.market_calendar()
    result_start = pd.Timestamp(R0)
    cal_pre = cal_all[cal_all < result_start]
    compute_start = cal_pre[-WARMUP] if len(cal_pre) >= WARMUP else cal_pre[0]
    compute_end = cal_all[cal_all <= pd.Timestamp(R1)][-1]

    cfg20 = lc.LifecycleConfig(breakout_lookback=20, max_observation_days=120,
                               pool_gap_tolerance=5)
    cfg60 = lc.LifecycleConfig(breakout_lookback=60, max_observation_days=120,
                               pool_gap_tolerance=5)
    codes = sorted(store.list_codes())
    print(f"[GateB] codes={len(codes)} compute={compute_start.date()}"
          f"..{compute_end.date()}")

    rows20, rows60 = [], []
    t0 = time.time()
    for bstart in range(0, len(codes), 200):
        batch = codes[bstart:bstart + 200]
        upool = ps.read_table(UNIVERSE_SRC,
                              columns=["code", "date", "monthly_pool_state"],
                              codes=batch)
        wax = ps.read_table(WEEKLY_DIR / "partitions",
                            columns=["code", "date", "trend_structure",
                                     "current_momentum"], codes=batch)
        pev = ps.read_table(PB_DIR / "events" / "partitions",
                            columns=["code", "event_id", "first_day", "end_day"],
                            codes=batch)
        pool_by_code: dict = {}
        for rec in upool.drop_duplicates(subset=["code", "date"]).itertuples(
                index=False):
            v = rec.monthly_pool_state
            pool_by_code.setdefault(rec.code, {})[rec.date] = (
                "in" if v == "in" else "out" if v == "out" else None)
        week_by_code: dict = {}
        for rec in (wax.drop_duplicates(subset=["code", "date"])
                .sort_values(["code", "date"]).itertuples(index=False)):
            week_by_code.setdefault(rec.code, []).append(
                (pd.Timestamp(rec.date), rec.trend_structure,
                 rec.current_momentum))
        pb_by_code: dict = {}
        for rec in (pev.drop_duplicates(subset=["event_id"])
                .sort_values(["first_day"]).itertuples(index=False)):
            pb_by_code.setdefault(rec.code, []).append(
                {"event_id": rec.event_id, "first_day": rec.first_day,
                 "end_day": rec.end_day})
        for code in batch:
            daily = store.daily(code)
            if daily is None or daily.empty:
                continue
            daily = daily[(daily.index >= compute_start)
                          & (daily.index <= compute_end)]
            if daily.empty:
                continue
            for cfg, sink in ((cfg20, rows20), (cfg60, rows60)):
                lcs = lc.classify_lifecycle(
                    code, daily, week_by_code.get(code, []),
                    pool_by_code.get(code, {}), pb_by_code.get(code, []), cfg)
                if len(lcs):
                    lcs = lcs[(lcs["anchor_day"] >= R0)
                              & (lcs["anchor_day"] <= R1)]
                    if len(lcs):
                        sink.append(lcs)
        done = min(bstart + 200, len(codes))
        print(f"  [{done}/{len(codes)}] {time.time() - t0:.0f}s "
              f"lc20={sum(len(x) for x in rows20)} "
              f"lc60={sum(len(x) for x in rows60)}", flush=True)
    df20 = pd.concat(rows20, ignore_index=True)
    df60 = pd.concat(rows60, ignore_index=True)
    return df20, df60


def load_frozen_table() -> pd.DataFrame:
    import glob
    import pyarrow.parquet as pq
    rows = []
    for fp in sorted(glob.glob(str(LIFE_DIR / "partitions/**/*.parquet"),
                               recursive=True)):
        rows.append(pq.read_table(fp).to_pandas())
    return pd.concat(rows, ignore_index=True)


def b0_baseline(df20: pd.DataFrame, frozen: pd.DataFrame) -> dict:
    print("[GateB/B0] 基线复现比对（lookback=20 全表逐列）")
    res = {"frozen_rows": int(len(frozen)), "rerun_rows": int(len(df20))}
    f = frozen.copy()
    f["code"] = f["code"].astype(str).str.zfill(6)
    fk = set(f["lifecycle_id"])
    rk = set(df20["lifecycle_id"])
    res["lifecycle_id_set_equal"] = fk == rk
    res["frozen_only_ids_n"] = len(fk - rk)
    res["rerun_only_ids_n"] = len(rk - fk)
    common = fk & rk
    f2 = f.set_index("lifecycle_id").sort_index()
    r2 = df20.set_index("lifecycle_id").sort_index()
    cols_diff = {}
    diff_samples = {}
    for col in ("anchor_day", "preparation_start", "breakout_day",
                "confirmation_day", "first_pullback_day", "divergence_day",
                "decay_day", "end_day", "end_reason", "right_censored",
                "days_total", "stage_sequence"):
        # NaN/None 归一（parquet 往返空值表示不同，非数据差异）
        a = f2.loc[sorted(common), col].fillna("<NA>").astype(str)
        b = r2.loc[sorted(common), col].fillna("<NA>").astype(str)
        bad = a != b
        n_bad = int(bad.sum())
        cols_diff[col] = n_bad
        if n_bad:
            diff_samples[col] = [
                {"lifecycle_id": i, "frozen": a[i], "rerun": b[i]}
                for i in a[bad].index[:5]]
    res["column_mismatch_counts"] = cols_diff
    res["column_mismatch_samples"] = diff_samples
    res["breakout_events_frozen"] = int(frozen["breakout_day"].notna().sum())
    res["breakout_events_rerun"] = int(df20["breakout_day"].notna().sum())
    res["verdict"] = "PASS" if (
        fk == rk and all(v == 0 for v in cols_diff.values())) else "FAIL"
    print(json.dumps({k: res[k] for k in (
        "frozen_rows", "rerun_rows", "lifecycle_id_set_equal",
        "breakout_events_frozen", "breakout_events_rerun", "verdict")}))
    return res


def b1_event_checks(events: pd.DataFrame, factors: dict) -> tuple[dict, list]:
    print("[GateB/B1] 事件内检查：ref60(复权,60有效观测) 与 原生20d(TDX)")
    mdates, _ = tv.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}
    tdx_close: dict = {}
    detail = []
    n_pass_adj = n_pass_nat = n_checked = 0
    by_code: dict = {}
    for r in events.itertuples(index=False):
        by_code.setdefault(r.code, []).append(r)
    for code, rs in sorted(by_code.items()):
        pref = "sh." if code.startswith(("6", "9")) else "sz."
        sd = tv.load_stock_data(f"{pref}{code}", factors)
        valid_sorted = sd.valid
        prior = [d for d in valid_sorted if d < rs[0].breakout_day]
        # TDX close 序列（原生口径；目录无点：vipdoc/sz/lday/sz000001.day）
        b = (Path(f"/root/tdx_data/vipdoc/{pref.rstrip('.')}/lday/"
                  f"{pref.replace('.', '')}{code}.day")).read_bytes()
        tdates, tc = [], []
        for i in range(len(b) // 32):
            d = struct.unpack("<I", b[i * 32 + 0:i * 32 + 4])[0]
            tdates.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
            # TDX .day 布局: date/open/high/low/close(+16)/amount/vol
            tc.append(struct.unpack("<i", b[i * 32 + 16:i * 32 + 20])[0] / 100.0)
        tdx_close = dict(zip(tdates, tc))
        for r in rs:
            t0 = r.breakout_day
            prior_now = [d for d in prior if d < t0]
            c0 = sd.adj.get(t0)
            obs60 = prior_now[-60:]
            ref60 = max((sd.adj[d] for d in obs60), default=None)
            ok_adj = bool(c0 is not None and ref60 is not None
                          and c0 > ref60)
            ti = tdates.index(t0) if t0 in tdates else -1
            ok_nat = False
            if ti >= 20:
                prior20 = tc[ti - 20:ti]
                ok_nat = bool(tdx_close[t0] > max(prior20))
            n_checked += 1
            n_pass_adj += ok_adj
            n_pass_nat += ok_nat
            detail.append({
                "breakout_event_id": r.breakout_event_id,
                "adj_close_t0": c0, "ref60_adj": ref60,
                "margin_vs_ref60": (c0 / ref60 - 1.0
                                    if c0 and ref60 else None),
                "ref60_obs_n": len(obs60),
                "pass_ref60_adj": ok_adj,
                "pass_native20_tdx": ok_nat})
        del sd
    res = {"checked": n_checked,
           "pass_ref60_adj": n_pass_adj,
           "fail_ref60_adj": n_checked - n_pass_adj,
           "pass_native20_tdx": n_pass_nat,
           "fail_native20_tdx": n_checked - n_pass_nat}
    print(json.dumps(res))
    return res, detail


def b2_rebuild(df60: pd.DataFrame, frozen: pd.DataFrame,
               df20: pd.DataFrame) -> dict:
    print("[GateB/B2] lookback=60 重构事件集 diff")
    f = frozen.copy()
    f["code"] = f["code"].astype(str).str.zfill(6)
    old = {(r.code, r.breakout_day) for r in
           f[f.breakout_day.notna()].itertuples(index=False)}
    new = {(r.code, r.breakout_day) for r in
           df60[df60.breakout_day.notna()].itertuples(index=False)}
    inter = old & new
    old_only = old - new
    new_only = new - old
    # 生命周期级：同 id 的 breakout_day 变化（NaN/None 归一）
    f2 = f.set_index("lifecycle_id")["breakout_day"].fillna("<NA>").astype(str)
    r2 = df60.set_index("lifecycle_id")["breakout_day"].fillna("<NA>").astype(str)
    common = f2.index.intersection(r2.index)
    changed = []
    for lid in common:
        a, b = f2[lid], r2[lid]
        if a != b:
            changed.append({"lifecycle_id": lid, "old": a, "new": b})
    res = {
        "old_breakout_events": len(old),
        "new_breakout_events": len(new),
        "intersection": len(inter),
        "old_only_n": len(old_only),
        "new_only_n": len(new_only),
        "old_only_sample": sorted(f"{c}_{d}" for c, d in
                                  list(old_only)[:200]),
        "new_only_sample": sorted(f"{c}_{d}" for c, d in
                                  list(new_only)[:200]),
        "lifecycle_breakout_day_changed_n": len(changed),
        "changed_sample": changed[:200],
        "verdict": "PASS" if (old == new) else "FAIL",
    }
    print(json.dumps({k: res[k] for k in (
        "old_breakout_events", "new_breakout_events", "intersection",
        "old_only_n", "new_only_n", "verdict")}))
    return res


def main() -> int:
    reuse = all((OUT / f).exists() for f in (
        "_gateB_rerun_lb20.parquet", "_gateB_rebuild_lb60.parquet"))
    if reuse and "--force" not in sys.argv:
        print("[GateB] 复用已存变体 parquet（--force 重算）")
        df20 = pd.read_parquet(OUT / "_gateB_rerun_lb20.parquet")
        df60 = pd.read_parquet(OUT / "_gateB_rebuild_lb60.parquet")
    else:
        df20, df60 = run_variants()
        df20.to_parquet(OUT / "_gateB_rerun_lb20.parquet", index=False)
        df60.to_parquet(OUT / "_gateB_rebuild_lb60.parquet", index=False)
    frozen = load_frozen_table()
    b0 = b0_baseline(df20, frozen)
    b2 = b2_rebuild(df60, frozen, df20)

    events = tv.load_events()
    factors = tv.load_factor_cache(OUT)
    b1, detail = b1_event_checks(events, factors)
    pd.DataFrame(detail).to_parquet(OUT / "ref60_event_diff.parquet",
                                    index=False)
    verdict = ("PASS" if (b0["verdict"] == "PASS"
                          and b2["verdict"] == "PASS"
                          and b1["fail_ref60_adj"] == 0
                          and b1["fail_native20_tdx"] == 0) else "FAIL")
    summary = {
        "gate": "B", "verdict": verdict,
        "b0_baseline_reproduction": b0,
        "b1_per_event": b1,
        "b2_rebuild_lb60": b2,
        "note": ("B1 冻结 ref60 与 lifecycle 原生 20 日规则口径不同；"
                 "任何不一致只报告，不改事件宇宙，等待人工裁定"),
    }
    (OUT / "ref60_event_diff.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    print(f"[GateB] verdict={verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
