#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3_coverage_audit.py — 任务三 V1 数据覆盖审计(只读).

授权范围: 仅覆盖/缺失/PIT 审计, 不计算任何未来收益结果变量, 不训练模型.
输出: output/research/t3_audit_v1/coverage_audit.json (本脚本为唯一产出物).

审计对象(全部只读):
  1. per_stock 冻结库 (A1/B1 原始层: OHLCV/amount/turn/pctChg + hfq)
  2. adjustment_v1 因子表 (复权可用性)
  3. momentum_panel_v3_parquet/signal_panel (特征层缺失率)
  4. lifecycle_v1/weekly_state_v1 (周线双轴覆盖)
  5. lifecycle_v1/lifecycle_stage4_v1_full (ID/事件层)
  6. capobs facts.csv (板块/ETF/市场背景层, available_at 语义)
  7. membership_history.csv (行业映射)
  8. e6_vwap events (筹码/VWAP 层)
"""
import csv
import glob
import gzip
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/t3_audit_v1"
OUT.mkdir(parents=True, exist_ok=True)

FIELDS = ["open", "high", "low", "close", "volume", "amount", "turn", "pctchg"]
IDX = {f: i + 1 for i, f in enumerate(FIELDS)}


def market_calendar():
    b = Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day").read_bytes()
    dates = []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        dates.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
    return dates


def pct(x, y):
    return round(100.0 * x / y, 4) if y else None


def main():
    res = {"generated_note": "只读审计; 无未来收益变量参与; 输入均为现有冻结/运行产物"}

    # ---------- 0. 输入锚 (路径+行数, 供冻结稿引用) ----------
    anchors = {}

    # ---------- 1. per_stock 冻结库 ----------
    print("[1] per_stock frozen library ...", file=sys.stderr)
    lib_dir = ROOT / "data/adjustment_baostock/per_stock"
    files = sorted(lib_dir.glob("*.json.gz"))
    tot = Counter()
    per_year_rows = Counter()
    miss = Counter()          # null/空串
    nonpos = Counter()        # <=0 (close/volume/amount 语义非法)
    turn_zero = 0
    vol_zero = 0
    hfq_mismatch = 0
    first_dates, last_dates = [], []
    rows_per_stock = []
    for fp in files:
        j = json.load(gzip.open(fp, "rt"))
        code = j["code"]
        unadj, hfq = j["unadj"], j.get("hfq", [])
        rows_per_stock.append(len(unadj))
        if len(hfq) != len(unadj):
            hfq_mismatch += 1
        first_dates.append(unadj[0][0])
        last_dates.append(unadj[-1][0])
        for r in unadj:
            d = r[0]
            per_year_rows[d[:4]] += 1
            for f in FIELDS:
                v = r[IDX[f]]
                if v is None or v == "":
                    miss[f] += 1
                    continue
                try:
                    fv = float(v)
                except ValueError:
                    miss[f] += 1
                    continue
                if not np.isfinite(fv):
                    miss[f] += 1
                elif fv <= 0:
                    nonpos[f] += 1
            if r[IDX["volume"]] in (None, "") or float(r[IDX["volume"]]) == 0:
                vol_zero += 1
            if r[IDX["turn"]] not in (None, "") and float(r[IDX["turn"]]) == 0:
                turn_zero += 1
        tot["rows"] += len(unadj)
    first_dates.sort(); last_dates.sort(); rows_per_stock.sort()
    q = lambda a, p: a[int(p * (len(a) - 1))]
    res["per_stock"] = {
        "files": len(files),
        "rows": tot["rows"],
        "range": [first_dates[0], last_dates[-1]],
        "first_date_p5/p50/p95": [q(first_dates, .05), q(first_dates, .5), q(first_dates, .95)],
        "last_date_p5/p50": [q(last_dates, .05), q(last_dates, .5)],
        "rows_per_stock_p5/p50/p95": [q(rows_per_stock, .05), q(rows_per_stock, .5), q(rows_per_stock, .95)],
        "missing": {f: {"n": miss[f], "pct": pct(miss[f], tot["rows"])} for f in FIELDS},
        "nonpositive": {f: {"n": nonpos[f], "pct": pct(nonpos[f], tot["rows"])} for f in FIELDS},
        "turn_zero_rows": {"n": turn_zero, "pct": pct(turn_zero, tot["rows"])},
        "volume_zero_rows": {"n": vol_zero, "pct": pct(vol_zero, tot["rows"])},
        "hfq_rowcount_mismatch_stocks": hfq_mismatch,
        "per_year_rows": dict(sorted(per_year_rows.items())),
    }
    anchors["per_stock_dir"] = {"path": str(lib_dir), "files": len(files)}

    # ---------- 2. 因子表 ----------
    print("[2] adjustment factor table ...", file=sys.stderr)
    fac_stocks = defaultdict(set)
    n_fac = 0
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            fac_stocks[row["code"]].add(row["date"])
            n_fac += 1
    lib_keys = defaultdict(set)
    for fp in files:  # 二次轻扫仅取键
        j = json.load(gzip.open(fp, "rt"))
        lib_keys[j["code"]] = {r[0] for r in j["unadj"]}
    miss_rows = sum(len(lib_keys[c] - fac_stocks.get(c, set())) for c in lib_keys)
    fac_extra = sum(len(fac_stocks.get(c, set()) - lib_keys[c]) for c in lib_keys)
    res["factor_table"] = {
        "rows": n_fac,
        "stocks": len(fac_stocks),
        "library_rows_without_factor": {"n": miss_rows, "pct": pct(miss_rows, tot["rows"])},
        "factor_rows_without_library_row": fac_extra,
        "stocks_with_any_missing": sum(1 for c in lib_keys if lib_keys[c] - fac_stocks.get(c, set())),
    }
    del lib_keys

    # ---------- 3. signal_panel 特征层缺失率 ----------
    print("[3] signal_panel ...", file=sys.stderr)
    sp_files = sorted(glob.glob(str(ROOT / "output/research/momentum_panel_v3_parquet/signal_panel/**/*.parquet"), recursive=True))
    sp_null = Counter(); sp_rows = 0; sp_dates = set(); sp_codes = set()
    numeric_like = set()
    for fp in sp_files:
        t = pq.read_table(fp)
        sp_rows += t.num_rows
        dcol = t.column("date").to_pylist()
        sp_dates.update(dcol)
        sp_codes.update(t.column("code").to_pylist())
        for name in t.column_names:
            if name in ("code", "date"):
                continue
            col = t.column(name)
            nul = col.null_count
            import pyarrow as pa
            try:
                if col.type == pa.string():
                    arr = col.to_pylist()
                    nul += sum(1 for v in arr if v == "")
                elif pa.types.is_floating(col.type) or pa.types.is_integer(col.type):
                    arr = col.to_pylist()
                    nul += sum(1 for v in arr if v is not None and not np.isfinite(float(v)))
            except Exception:
                pass
            sp_null[name] += nul
        del t
    res["signal_panel"] = {
        "files": len(sp_files), "rows": sp_rows,
        "date_range": [min(sp_dates), max(sp_dates)],
        "codes": len(sp_codes),
        "col_missing_pct": {k: pct(v, sp_rows) for k, v in sorted(sp_null.items()) if v > 0},
        "cols_zero_missing": sorted(set(
            pq.read_table(sp_files[0]).column_names) - set(sp_null) - {"code", "date"}) ,
    }

    # ---------- 4. weekly_state_v1 ----------
    print("[4] weekly_state ...", file=sys.stderr)
    ws_files = sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/weekly_state_v1/partitions/**/*.parquet"), recursive=True))
    ws_rows = 0; ws_dates = set(); ws_codes = set()
    ts_cnt, cm_cnt, ev_cnt = Counter(), Counter(), Counter()
    ws_null = Counter()
    for fp in ws_files:
        t = pq.read_table(fp, columns=["code", "date", "trend_structure", "current_momentum", "evidence_completeness"])
        ws_rows += t.num_rows
        ws_dates.update(t.column("date").to_pylist())
        ws_codes.update(t.column("code").to_pylist())
        ts_cnt.update(t.column("trend_structure").to_pylist())
        cm_cnt.update(t.column("current_momentum").to_pylist())
        ev_cnt.update(t.column("evidence_completeness").to_pylist())
        ws_null["trend_structure"] += t.column("trend_structure").null_count
        ws_null["current_momentum"] += t.column("current_momentum").null_count
        del t
    res["weekly_state"] = {
        "files": len(ws_files), "rows": ws_rows,
        "date_range": [min(ws_dates), max(ws_dates)],
        "codes": len(ws_codes),
        "null": dict(ws_null),
        "trend_structure": dict(ts_cnt),
        "current_momentum": dict(cm_cnt),
        "evidence_completeness": dict(ev_cnt),
    }

    # ---------- 5. lifecycle ID/事件层 ----------
    print("[5] lifecycle ...", file=sys.stderr)
    lc_files = sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/partitions/**/*.parquet"), recursive=True))
    ids = set(); lc_rows = 0; bo_days = 0; rc = 0
    end_reason = Counter(); bad_code = 0
    bo_ids = set()
    for fp in lc_files:
        t = pq.read_table(fp, columns=["code", "lifecycle_id", "breakout_day", "end_reason", "right_censored"])
        lc_rows += t.num_rows
        ids.update(t.column("lifecycle_id").to_pylist())
        codes = t.column("code").to_pylist()
        bo = t.column("breakout_day").to_pylist()
        er = t.column("end_reason").to_pylist()
        rcl = t.column("right_censored").to_pylist()
        for c, b, e, r in zip(codes, bo, er, rcl):
            if not (isinstance(c, str) and len(c) == 6 and c.isdigit()):
                bad_code += 1
            if b is not None:
                bo_days += 1
                bo_ids.add(f"{c}_{b}")
            end_reason[e] += 1
            if r:
                rc += 1
        del t
    res["lifecycle"] = {
        "files": len(lc_files), "rows": lc_rows,
        "unique_lifecycle_id": len(ids),
        "dup_lifecycle_rows": lc_rows - len(ids),
        "with_breakout_day": bo_days,
        "unique_breakout_event_id_code_day": len(bo_ids),
        "bad_code_format_rows": bad_code,
        "end_reason": dict(end_reason),
        "right_censored": rc,
    }

    # ---------- 6. capobs facts (板块/ETF/市场) ----------
    print("[6] capobs facts ...", file=sys.stderr)
    fpath = "/root/project/workspace/capital-observer/output/research_context/facts.csv"
    metric_stat = defaultdict(lambda: {"n": 0, "has_avail": 0, "min": None, "max": None,
                                       "keys": set(), "per_key_days": Counter()})
    with open(fpath) as f:
        for row in csv.DictReader(f):
            m = row["metric"]
            s = metric_stat[m]
            s["n"] += 1
            if row["available_at"]:
                s["has_avail"] += 1
            d = row["effective_at"]
            s["min"] = d if s["min"] is None or d < s["min"] else s["min"]
            s["max"] = d if s["max"] is None or d > s["max"] else s["max"]
            k = row["asset_key"] or row["subject_key"]
            s["keys"].add(k)
            s["per_key_days"][k] += 1
    mdates = set(market_calendar())
    fac_summary = {}
    for m, s in metric_stat.items():
        days = sorted(s["per_key_days"].values())
        fac_summary[m] = {
            "n": s["n"], "distinct_keys": len(s["keys"]),
            "effective_range": [s["min"], s["max"]],
            "pit_available_pct": pct(s["has_avail"], s["n"]),
            "days_per_key_p50/min": [days[len(days) // 2], days[0]] if days else None,
        }
    # 申万指数 vs 市场日历缺口
    sw_missing = {}
    for m in ("sw_close", "sw_amount"):
        s = metric_stat[m]
        sw_missing[m] = {k: v for k, v in list(s["per_key_days"].items())[:3]}
    res["capobs_facts"] = {
        "file": fpath,
        "metrics": fac_summary,
        "market_calendar_days_in_2023_08_01__2026_09_09": sum(1 for d in mdates if "2023-08-01" <= d <= "2026-09-09"),
    }
    # ETF 份额逐日缺口(取前5只做样例)
    etf_days = metric_stat["etf_total_shares"]["per_key_days"]
    cal_2024 = [d for d in sorted(mdates) if d >= "2024-01-02" <= "2026-09-15"]
    res["capobs_facts"]["etf_sample_days_vs_calendar"] = {
        "calendar_days": len(cal_2024),
        "sample": {k: etf_days[k] for k in list(etf_days)[:5]},
    }

    # ---------- 7. membership ----------
    print("[7] membership ...", file=sys.stderr)
    mem_rows = list(csv.DictReader(open("/root/project/workspace/capital-observer/output/research_context/membership_history.csv")))
    codes = [r["code"] for r in mem_rows]
    eff_from = Counter(r["effective_from"] for r in mem_rows)
    eff_to_open = sum(1 for r in mem_rows if not r["effective_to"])
    ind_cnt = Counter(r["industry_code"] for r in mem_rows)
    res["membership"] = {
        "rows": len(mem_rows), "unique_codes": len(set(codes)),
        "effective_from_values": dict(eff_from),
        "open_ended_rows": eff_to_open,
        "industries": len(ind_cnt),
        "stocks_per_industry_p50/min/max": [sorted(ind_cnt.values())[len(ind_cnt) // 2],
                                            min(ind_cnt.values()), max(ind_cnt.values())],
        "industry_codes_sample": sorted(ind_cnt)[:8],
    }

    # ---------- 8. e6 vwap ----------
    print("[8] e6 vwap ...", file=sys.stderr)
    ev = list(csv.DictReader(open(ROOT / "output/research/e6_vwap/events.csv")))
    n_ev = len(ev)
    vwap_miss = Counter()
    for r in ev:
        for c in ("price_to_vwap_5d", "price_to_vwap_10d", "price_to_vwap_20d", "volume_ratio_5_vs_prior20"):
            if r.get(c) in (None, "", "NaN"):
                vwap_miss[c] += 1
    res["e6_vwap"] = {"rows": n_ev, "missing": {k: pct(v, n_ev) for k, v in vwap_miss.items()}}

    # ---------- 9. identify 三时点 ----------
    print("[9] identify ...", file=sys.stderr)
    idt = {}
    for ds in ("breakout", "shrink", "stabilization"):
        rows = list(csv.DictReader(gzip.open(ROOT / f"output/research/posneg_v1/identify_{ds}.csv.gz", "rt")))
        cols = [c for c in rows[0] if c.startswith(("bo_", "D", "E")) or "vol" in c.lower()]
        mm = {}
        for c in cols:
            n_bad = sum(1 for r in rows if r.get(c) in (None, "", "NaN"))
            if n_bad:
                mm[c] = pct(n_bad, len(rows))
        idt[ds] = {"rows": len(rows), "missing_pct": mm}
    res["identify"] = idt

    res["_anchors"] = anchors
    with open(OUT / "coverage_audit.json", "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("written:", OUT / "coverage_audit.json", file=sys.stderr)


if __name__ == "__main__":
    main()
