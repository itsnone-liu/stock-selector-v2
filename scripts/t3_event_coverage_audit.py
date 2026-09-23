#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3_event_coverage_audit.py — 任务三 V1 门禁一: 27,422 全事件集覆盖审计(只读).

背景: 首轮审计中筹码/VWAP 只在 e6 13,616 事件子集验证零缺失。
用户条件验收要求: 同一套 coverage audit 对 27,422 全量突破事件跑一次,
不求零缺失, 要求知道真实覆盖率; 同时按四态删失口径(none/sample_end/
security_history_end/data_gap)给出标签可标性分解。

口径复刻 e6(语义层): 滚动VWAP窗口=含T0的最近w个交易日观测, 严格全在,
vol>0; 但量纲用冻结库(amount/volume, 元/股, 不除100——e6为TDX手单位)。

无任何未来收益结果变量计算; 无模型; 只做可计算性/覆盖统计。
输出: output/research/t3_audit_v1/event_coverage_audit.json
"""
import glob
import gzip
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/t3_audit_v1"
OUT.mkdir(parents=True, exist_ok=True)
GLOBAL_END = "2026-09-18"          # 冻结库全局末日(审计#1实测)
HS = (5, 10, 20, 40)


def market_calendar():
    b = Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day").read_bytes()
    out = []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        out.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
    return out


def pct(x, y):
    return round(100.0 * x / y, 4) if y else None


def main():
    mdates = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    last_mpos_global = max(i for i, d in enumerate(mdates) if d <= GLOBAL_END)

    # ---- 事件集(只读 lifecycle 冻结产物) ----
    import pyarrow.parquet as pq
    ev_by_code = defaultdict(list)
    n_ev = 0
    for fp in sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/partitions/**/*.parquet"), recursive=True)):
        t = pq.read_table(fp, columns=["code", "breakout_day"])
        for c, d in zip(t.column("code").to_pylist(), t.column("breakout_day").to_pylist()):
            if d is not None:
                ev_by_code[c].append(d)
                n_ev += 1
        del t
    print(f"events: {n_ev} / stocks: {len(ev_by_code)}", file=sys.stderr)

    # ---- code6 -> per_stock 文件名映射(以存量文件名为准, 不用规则猜) ----
    lib_files = {}
    for fp in (ROOT / "data/adjustment_baostock/per_stock").glob("*.json.gz"):
        code6 = fp.name[:-8].split(".")[1]
        lib_files[code6] = fp

    # ---- 因子覆盖: pass A 计数 ----
    fac_n = Counter()
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv_reader(f):
            fac_n[row["code"]] += 1

    # ---- 因子覆盖: pass B 找缺因子股(只对有事件的股) ----
    bad = {}
    for code6 in ev_by_code:
        fp = lib_files.get(code6)
        if fp is None:
            bad[code6] = "no_library_file"
            continue
        code_pfx = fp.name[:-8]
        j = json.load(gzip.open(fp, "rt"))
        if fac_n.get(code_pfx, 0) != len(j["unadj"]):
            bad[code6] = code_pfx
    bad_factor_codes = {v for v in bad.values() if v != "no_library_file"}
    no_file_codes = {k for k, v in bad.items() if v == "no_library_file"}

    # ---- 因子覆盖: pass C 只为缺因子股取日期集合 ----
    fac_dates_bad = defaultdict(set)
    if bad_factor_codes:
        with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
            for row in csv_reader(f):
                if row["code"] in bad_factor_codes:
                    fac_dates_bad[row["code"]].add(row["date"])

    # ---- 事件级审计 ----
    cnt = Counter()
    gap_days_hist = Counter()
    sec_end_last_date = []          # security_history_end 股的末个有效日
    win_cov_sum = defaultdict(float)
    for code6, days in sorted(ev_by_code.items()):
        fp = lib_files.get(code6)
        if fp is None:
            cnt["stock_no_library_file"] += len(days)
            continue
        code_pfx = fp.name[:-8]
        j = json.load(gzip.open(fp, "rt"))
        rows = j["unadj"]
        dates = [r[0] for r in rows]
        closes = {r[0]: float(r[4]) for r in rows}
        vols = {r[0]: (float(r[5]) if r[5] not in (None, "") else None) for r in rows}
        amts = {r[0]: (float(r[6]) if r[6] not in (None, "") else None) for r in rows}
        turns = {r[0]: (float(r[7]) if r[7] not in (None, "") else None) for r in rows}
        if code_pfx in fac_dates_bad:
            valid = {d for d in dates if d in fac_dates_bad[code_pfx]}
        else:
            valid = set(dates)
        valid_sorted = [d for d in dates if d in valid]
        vpos = {d for d in dates if (vols.get(d) or 0) > 0 and (amts.get(d) or 0) > 0}
        del j, rows

        for t0 in days:
            cnt["n"] += 1
            if t0 not in closes:
                cnt["t0_no_price_row"] += 1
                continue
            i0 = mpos.get(t0)
            if i0 is None:
                cnt["t0_not_in_calendar"] += 1
                continue
            prior_valid = [d for d in valid_sorted if d < t0]
            prior_vpos = [d for d in prior_valid if d in vpos]

            # A1: 前60个有效交易观测(含因子)全部可得
            cnt["a1_ref60_ready" if len(prior_valid) >= 60 else "a1_ref60_short"] += 1
            # A1 变体: 需要连续60个市场日也有效(更严, 仅参考)
            if i0 >= 60 and all(mdates[k] in valid for k in range(i0 - 60, i0)):
                cnt["a1_ref60_contig_ok"] += 1

            # B1: 前20个有效观测的量能基准
            cnt["b1_vol20_ready" if len(prior_vpos) >= 20 else "b1_vol20_short"] += 1

            # T0 字段
            if t0 in valid and closes.get(t0, 0) > 0:
                cnt["t0_close_ok"] += 1
            else:
                cnt["t0_close_bad"] += 1
            cnt["t0_vol_pos" if t0 in vpos else "t0_vol_bad"] += 1
            cnt["t0_turn_ok" if (turns.get(t0) or 0) > 0 else "t0_turn_bad"] += 1

            # 筹码: 滚动VWAP w∈{5,10,20} 含T0严格窗口(镜像e6语义)
            incl = [t0] + prior_valid[::-1]     # T0 起往前
            for w in (5, 10, 20):
                win = incl[:w]
                if len(win) == w and all(d in vpos for d in win) and t0 in valid:
                    cnt[f"chip_vwap{w}_strict_ok"] += 1
                else:
                    cnt[f"chip_vwap{w}_strict_miss"] += 1

            # 标签窗口四态
            for h in HS:
                ih = i0 + h
                if ih >= len(mdates) or mdates[ih] > GLOBAL_END:
                    cnt[f"h{h}_sample_end"] += 1
                    continue
                win_days = mdates[i0:ih + 1]
                n_valid = sum(1 for d in win_days if d in valid)
                win_cov_sum[h] += n_valid / (h + 1)
                if n_valid == h + 1:
                    cnt[f"h{h}_none"] += 1
                else:
                    last_valid = valid_sorted[-1] if valid_sorted else None
                    if last_valid is None or last_valid < mdates[ih]:
                        cnt[f"h{h}_security_history_end"] += 1
                        sec_end_last_date.append(last_valid)
                        # 末有效日早于全局末-10市场日 → 退市候选(待外部核实)
                        if last_valid is not None and mpos.get(last_valid, 10**9) <= last_mpos_global - 10:
                            cnt[f"h{h}_sec_end_likely_delist"] += 1
                        else:
                            cnt[f"h{h}_sec_end_recent_unknown"] += 1
                    else:
                        cnt[f"h{h}_data_gap"] += 1
                        gap_days_hist[h + 1 - n_valid] += 1

            # turn 累计(未来20日, 仅可标性统计, 不算值)
            ih20 = i0 + 20
            if ih20 < len(mdates) and mdates[ih20] <= GLOBAL_END:
                fut = [d for d in mdates[i0 + 1:ih20 + 1]]
                n_turn = sum(1 for d in fut if (turns.get(d) or 0) > 0)
                cnt["turn20_all" if n_turn == 20 else "turn20_partial"] += 1
                cnt["turn20_missing_days_total"] += (20 - n_turn)

    n = cnt["n"]
    res = {
        "events_total": n,
        "a1": {"ref60_ready": [cnt["a1_ref60_ready"], pct(cnt["a1_ref60_ready"], n)],
               "ref60_short": [cnt["a1_ref60_short"], pct(cnt["a1_ref60_short"], n)],
               "ref60_contig_market60_ok": [cnt["a1_ref60_contig_ok"], pct(cnt["a1_ref60_contig_ok"], n)]},
        "b1": {"vol20_ready": [cnt["b1_vol20_ready"], pct(cnt["b1_vol20_ready"], n)],
               "vol20_short": [cnt["b1_vol20_short"], pct(cnt["b1_vol20_short"], n)]},
        "t0": {"close_ok": [cnt["t0_close_ok"], pct(cnt["t0_close_ok"], n)],
               "vol_pos": [cnt["t0_vol_pos"], pct(cnt["t0_vol_pos"], n)],
               "turn_ok": [cnt["t0_turn_ok"], pct(cnt["t0_turn_ok"], n)],
               "no_price_row": cnt["t0_no_price_row"], "not_in_calendar": cnt["t0_not_in_calendar"]},
        "chip": {f"vwap{w}_strict_ok": [cnt[f"chip_vwap{w}_strict_ok"], pct(cnt[f"chip_vwap{w}_strict_ok"], n)] for w in (5, 10, 20)},
        "labels_four_state": {h: {
            "none": [cnt[f"h{h}_none"], pct(cnt[f"h{h}_none"], n)],
            "sample_end": [cnt[f"h{h}_sample_end"], pct(cnt[f"h{h}_sample_end"], n)],
            "security_history_end": [cnt[f"h{h}_security_history_end"], pct(cnt[f"h{h}_security_history_end"], n)],
            "  of_which_likely_delist(末有效日≤全局末-10市场日,待核实)": [cnt[f"h{h}_sec_end_likely_delist"]],
            "  of_which_recent_unknown": [cnt[f"h{h}_sec_end_recent_unknown"]],
            "data_gap": [cnt[f"h{h}_data_gap"], pct(cnt[f"h{h}_data_gap"], n)],
            "mean_win_coverage": round(win_cov_sum[h] / max(n - cnt[f"h{h}_sample_end"], 1), 5),
        } for h in HS},
        "turn_next20": {"all": [cnt["turn20_all"], pct(cnt["turn20_all"], n)],
                        "partial": [cnt["turn20_partial"], pct(cnt["turn20_partial"], n)],
                        "missing_days_total": cnt["turn20_missing_days_total"]},
        "data_gap_missing_days_hist": {str(k): v for k, v in sorted(gap_days_hist.items())},
        "stock_no_library_file_events": cnt["stock_no_library_file"],
        "notes": [
            "VWAP语义镜像e6: 含T0严格w日窗口+vol>0; 量纲=冻结库元/股(不除100)",
            "四态判定顺序: sample_end(窗口越界) > 全有效(none) > 个股历史终(sec) > 窗口内缺口(gap)",
            "likely_delist仅为末有效日 heuristic, 退市终态须V2用外部名单核实",
            "无未来收益数值计算",
        ],
    }
    with open(OUT / "event_coverage_audit.json", "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("written:", OUT / "event_coverage_audit.json", file=sys.stderr)


def csv_reader(f):
    import csv
    return csv.DictReader(f)


if __name__ == "__main__":
    main()
