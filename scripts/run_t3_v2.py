#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_t3_v2.py — 任务三 V2 构建器（冻结实现的物化，无研究成分）。

产出（output/research/t3_v2/）：
  event_master.parquet            27,422 事件 + lifecycle 映射列
  event_labels.parquet            §6.1-6.5 主口径（censored 行收益 null）
  event_labels_sensitivity.parquet imputed_last_available（物理分离）
  event_features_a1/b1/chip.parquet  T0 截止特征层
  integrity_report.json           计数/schema/缺失/覆盖/hash + Gate D/E
确定性：无随机数；全部输出按 breakout_event_id 排序；hash 可复现。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402

from stock_selector.research import t3_v2 as tv  # noqa: E402

OUT = ROOT / "output/research/t3_v2"
FROZEN_AUDIT = ROOT / "docs/reports/T3_SUSTAIN_EVENT_COVERAGE_AUDIT.json"
FROZEN_EXPECTED = {
    "events_total": 27422,
    "a1_ref60_ready": 27422,
    "b1_vol20_ready": 27422,
    "t0_close_pos": 27422,
    "t0_vol_pos": 27422,
    "chip_vwap5_miss": 85,
    "chip_vwap10_miss": 137,
    "chip_vwap20_miss": 218,
    "turn20_partial": 279,
    "turn20_missing_days_total": 1202,
    "h5_none": 27422,
    "h10_none": 27422,
    "h20_none": 27289, "h20_sample_end": 133,
    "h40_none": 26237, "h40_sample_end": 1185,
    "h20_security_history_end": 0, "h20_data_gap": 0,
    "h40_security_history_end": 0, "h40_data_gap": 0,
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def truncated_stock(sd: tv.StockData, t0: str) -> tv.StockData:
    """截断到 <=T0 的单股视图（Gate D 用；全部字典逐项过滤）。"""
    keep = [d for d in sd.dates if d <= t0]
    ks = set(keep)
    return tv.StockData(
        code_pfx=sd.code_pfx, dates=keep,
        o=None,
        h={d: v for d, v in sd.h.items() if d in ks},
        l={d: v for d, v in sd.l.items() if d in ks},
        c={d: v for d, v in sd.c.items() if d in ks},
        vol={d: v for d, v in sd.vol.items() if d in ks},
        amt={d: v for d, v in sd.amt.items() if d in ks},
        turn={d: v for d, v in sd.turn.items() if d in ks},
        hfq_h={}, hfq_c={},
        F={d: v for d, v in sd.F.items() if d in ks},
        valid=[d for d in sd.valid if d in ks],
        vpos={d for d in sd.vpos if d in ks},
    )


def main() -> int:
    t_start = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    print("[t3_v2] 1/6 因子缓存")
    cache_dir = OUT / "_cache" / "factor"
    ft_md5 = sha256_file(ROOT / "output/research/adjustment_v1/factor_table.csv.gz")
    meta_fp = cache_dir / "_meta.json"
    if meta_fp.exists() and cache_dir.glob("sh.000001.json.gz"):
        meta = json.loads(meta_fp.read_text())
        if meta.get("factor_table_sha256") == ft_md5:
            factors = tv.load_factor_cache(OUT)
        else:
            factors = tv.build_factor_cache(OUT)
            meta = json.loads(meta_fp.read_text())
            meta["factor_table_sha256"] = ft_md5
            meta_fp.write_text(json.dumps(meta))
    else:
        factors = tv.build_factor_cache(OUT)
        meta = json.loads(meta_fp.read_text())
        meta["factor_table_sha256"] = ft_md5
        meta_fp.write_text(json.dumps(meta))
    print(f"       因子缓存 {meta['stocks']} 股 {meta['rows']} 行")

    print("[t3_v2] 2/6 事件宇宙 + 市场层")
    ev = tv.load_events()
    mdates, mclose = tv.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}
    last_global_pos = max(i for i, d in enumerate(mdates) if d <= tv.DATASET_END)
    print(f"       events={len(ev)} 日历={mdates[0]}..{mdates[-1]} "
          f"dataset_end={tv.DATASET_END}")

    by_code: dict = {}
    for r in ev.itertuples(index=False):
        by_code.setdefault(r.code, []).append(r)

    label_rows, sens_rows, a1_rows, b1_rows, chip_rows = [], [], [], [], []
    gate_d = {"sample_stride": 97, "checked": 0, "mismatched": 0,
              "mismatch_detail": []}
    max_lib_date = "0000-00-00"
    codes = sorted(by_code)

    print("[t3_v2] 3/6 逐股计算标签+特征")
    for ci, code in enumerate(codes):
        code_pfx_map = {}
        for pref in ("sh", "sz"):
            cand = f"{pref}.{code}"
            if (ROOT / f"data/adjustment_baostock/per_stock/"
                       f"{cand}.json.gz").exists():
                code_pfx_map[cand] = True
        if not code_pfx_map:
            print(f"  [WARN] 库缺股票 {code}（{len(by_code[code])} 事件）",
                  file=sys.stderr)
            continue
        sd = tv.load_stock_data(next(iter(code_pfx_map)), factors)
        if sd.dates and sd.dates[-1] > max_lib_date:
            max_lib_date = sd.dates[-1]
        for r in by_code[code]:
            t0 = r.breakout_day
            lab = tv.compute_labels(sd, t0, mdates, mclose, mpos,
                                    last_global_pos)
            lab["breakout_event_id"] = r.breakout_event_id
            label_rows.append(lab)
            if any(lab[f"censored_reason_h{h}"] != "none" for h in tv.HS):
                sens = tv.compute_labels_sensitivity(
                    sd, t0, mdates, mclose, mpos, last_global_pos)
                sens["breakout_event_id"] = r.breakout_event_id
                sens_rows.append(sens)
            a1 = tv.compute_features_a1(sd, t0)
            a1["breakout_event_id"] = r.breakout_event_id
            a1_rows.append(a1)
            b1 = tv.compute_features_b1(sd, t0)
            b1["breakout_event_id"] = r.breakout_event_id
            b1_rows.append(b1)
            chip = tv.compute_features_chip(sd, t0)
            chip["breakout_event_id"] = r.breakout_event_id
            chip_rows.append(chip)
            # Gate D：截断重算（抽样）
            if (len(a1_rows) % gate_d["sample_stride"]) == 1:
                sdt = truncated_stock(sd, t0)
                for name, fn, orig in (("a1", tv.compute_features_a1, a1),
                                       ("b1", tv.compute_features_b1, b1),
                                       ("chip", tv.compute_features_chip, chip)):
                    got = fn(sdt, t0)
                    gate_d["checked"] += 1
                    for k, v in orig.items():
                        if k == "breakout_event_id":
                            continue
                        if got.get(k) != v:
                            gate_d["mismatched"] += 1
                            if len(gate_d["mismatch_detail"]) < 50:
                                gate_d["mismatch_detail"].append(
                                    {"id": r.breakout_event_id, "layer": name,
                                     "field": k, "full": repr(v),
                                     "trunc": repr(got.get(k))})
        del sd
        if ci % 500 == 499:
            print(f"       {ci + 1}/{len(codes)} 股 "
                  f"{time.time() - t_start:.0f}s")

    print("[t3_v2] 4/6 装配 + 排序 + 写盘")
    def build_df(rows):
        df = pd.DataFrame(rows)
        return df.sort_values("breakout_event_id").reset_index(drop=True)

    master = ev
    labels = build_df(label_rows)
    labels = labels[[c for c in labels.columns
                     if c not in ("breakout_day",)]]
    sens = build_df(sens_rows)
    sens = sens[[c for c in sens.columns if c != "breakout_day"]]
    a1 = build_df(a1_rows).drop(columns=["breakout_day"])
    b1 = build_df(b1_rows).drop(columns=["breakout_day"])
    chip = build_df(chip_rows).drop(columns=["breakout_day"])

    products = {}
    for name, df in (("event_master", master), ("event_labels", labels),
                     ("event_labels_sensitivity", sens),
                     ("event_features_a1", a1), ("event_features_b1", b1),
                     ("event_features_chip", chip)):
        p = OUT / f"{name}.parquet"
        df.to_parquet(p, index=False, compression="snappy")
        products[name] = {"rows": len(df), "cols": len(df.columns)}
        print(f"       {name}: {len(df)} 行 × {len(df.columns)} 列")

    print("[t3_v2] 5/6 Gate E 覆盖复现（审计口径镜像）")
    gate_e = {"expected": FROZEN_EXPECTED, "recomputed": {}, "diff": {}}
    gate_e["recomputed"]["events_total"] = len(label_rows)
    for h in tv.HS:
        for st in ("none", "sample_end", "security_history_end", "data_gap"):
            key = f"h{h}_{st}"
            n = sum(1 for r in label_rows
                    if r[f"censored_reason_h{h}"] == st)
            gate_e["recomputed"][key] = n
    gate_e["recomputed"]["a1_ref60_ready"] = sum(
        1 for r in a1_rows if r["a1_ref60_obs_n"] >= 60)
    gate_e["recomputed"]["b1_vol20_ready"] = sum(
        1 for r in b1_rows if r["b1_vol_base_obs_n"] >= 20)
    gate_e["recomputed"]["t0_close_pos"] = sum(
        1 for r in a1_rows if r["a1_breakout_margin"] is not None)
    gate_e["recomputed"]["t0_vol_pos"] = sum(
        1 for r in chip_rows if r["chip_vwap_day"] is not None)
    for w in (5, 10, 20):
        n_miss = sum(1 for r in chip_rows
                     if r[f"chip_price_to_vwap_{w}d"] is None)
        gate_e["recomputed"][f"chip_vwap{w}_miss"] = n_miss
    # turn20（审计口径：T0 后 20 个市场日，不含 T0）——由标签层换算：
    # 标签层 21 日窗含 T0；T0 缺口由 b1_turn_valid_t0 扣除。
    turn_partial, turn_miss = 0, 0
    b1_by_id = {r["breakout_event_id"]: r for r in b1_rows}
    for lab in label_rows:
        h = 20
        if lab[f"censored_reason_h{h}"] != "none":
            continue                       # 审计仅对非 sample_end 统计
        miss21 = lab["turn_miss_days_h20"] or 0
        t0_ok = b1_by_id[lab["breakout_event_id"]]["b1_turn_valid_t0"]
        miss = miss21 - (0 if t0_ok else 1)
        if miss > 0:
            turn_partial += 1
            turn_miss += miss
    gate_e["recomputed"]["turn20_partial"] = turn_partial
    gate_e["recomputed"]["turn20_missing_days_total"] = turn_miss
    for k, want in FROZEN_EXPECTED.items():
        got = gate_e["recomputed"].get(k)
        if got != want:
            gate_e["diff"][k] = {"expected": want, "recomputed": got}
    gate_e["verdict"] = "PASS" if not gate_e["diff"] else "FAIL"

    print("[t3_v2] 6/6 integrity_report")
    report = {
        "task": "T3_V2_implementation",
        "baseline_commit": "da933a1",
        "spec": "docs/reports/T3_SUSTAIN_COVERAGE_AUDIT_V1.md (path_label_v1+t3_id_v1)",
        "dataset_end_frozen": tv.DATASET_END,
        "dataset_end_observed_max_library_date": max_lib_date,
        "calendar_range": [mdates[0], mdates[-1]],
        "events": len(ev),
        "codes_with_events": len(codes),
        "products": products,
        "product_sha256": {n: sha256_file(OUT / f"{n}.parquet")
                           for n in products},
        "inputs_sha256": {
            "factor_table.csv.gz": ft_md5,
            "lifecycle_MANIFEST.json": sha256_file(
                ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full"
                "/MANIFEST.json"),
            "t3_v2.py": hashlib.md5(
                (ROOT / "src/stock_selector/research/t3_v2.py")
                .read_bytes()).hexdigest(),
        },
        "label_stats": {
            f"y{h}_{k}": {
                "n": int(labels[f"y{h}_{k}"].notna().sum()),
                "mean": float(labels[f"y{h}_{k}"].dropna().mean()),
                "min": float(labels[f"y{h}_{k}"].dropna().min()),
                "max": float(labels[f"y{h}_{k}"].dropna().max()),
            } for h in tv.HS for k in ("raw_log", "mkt_excess_log")},
        "gate_d_truncation_pit_audit": gate_d,
        "gate_e_coverage_reproduction": gate_e,
        "elapsed_sec": round(time.time() - t_start, 1),
    }
    (OUT / "integrity_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(f"[t3_v2] 完成 {time.time() - t_start:.0f}s | "
          f"GateD={gate_d['mismatched']}处不一致 "
          f"GateE={gate_e['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
