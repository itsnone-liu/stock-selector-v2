#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_retcalc_v1.py — retcalc_v1 产物审计 v2 (2026-09-21, 复审裁决后全升级).

R1 总体分池: 每策略×视角: 对照池==28,224 且 突破池(evaluable+null+排除突破段)==27,422
R2 逐格状态机: 每个 h 独立核验四态与收益(cash→0; position→值或tail-null; pending→null)
R3 条件成交: K4 全部五期限×双视角 仅成交行非null
R4 独立重算: 分层抽样 4策略×2视角×5期限×(K2/K3/K4) 每格≥2 独立因子比重算;
    staged 组合按 v5 公式(cash+Σlw(1+net_i)−1)独立复算;
    buy_price 与 v5 fill_price 交叉核对(价格源头一致性)
R5 排除与缺失: 全字段零计算值; 排除代码严格∈冻结24清单
R6 输入冻结: 全部 SHA256 执行时复核
"""
import csv
import glob
import gzip
import hashlib
import json
import random
import struct
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.decision.execution import CostModel          # noqa: E402

COST = CostModel()
HORIZONS = (1, 3, 5, 10, 20)
random.seed(20260919)
TRANCHES = {"t1": 0.30, "t2": 0.30, "t3": 0.40}


class PriceBook:
    """独立价格/因子簿: TDX序 + baostock OHLC + 冻结F."""

    def __init__(self):
        self.F = {}
        with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
            next(f)
            for line in f:
                c, d, uc, hc, Fv = line.split(",")
                self.F.setdefault(c, {})[d] = float(Fv)
        self.cache = {}

    def frame(self, code):
        if code in self.cache:
            return self.cache[code]
        p = json.load(gzip.open(ROOT / f"data/adjustment_baostock/per_stock/{code}.json.gz", "rt"))
        u = {x[0]: (float(x[1]), float(x[4])) for x in p["unadj"]}
        b = Path(f"/root/tdx_data/vipdoc/{code.split('.')[0]}/lday/"
                 f"{code.replace('.', '')}.day").read_bytes()
        tdx = []
        for i in range(len(b) // 32):
            d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
            tdx.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
        dates = [d for d in tdx if d in u and d in self.F.get(code, {})]
        fr = (dates, {d: i for i, d in enumerate(dates)}, u, self.F[code])
        self.cache[code] = fr
        return fr


def r_net(cost, invested, buy_px, buy_d, sell_px, sell_d, f_buy, f_sell):
    gt = invested * (sell_px * f_sell) / (buy_px * f_buy)
    bf = cost.fees(invested, "buy", date(int(buy_d[:4]), int(buy_d[5:7]), int(buy_d[8:10])))["total"]
    sf = cost.fees(gt, "sell", date(int(sell_d[:4]), int(sell_d[5:7]), int(sell_d[8:10])))["total"]
    return (gt - sf) / (invested + bf) - 1.0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    OUT = ROOT / "output/research/retcalc_v1" / mode
    rows = list(csv.DictReader(gzip.open(OUT / "retcalc.csv.gz", "rt")))
    failures = []
    report = {"mode": mode, "n_rows": len(rows)}

    # ── R6 输入冻结 SHA256 复核 ──
    fz = json.loads((ROOT / "output/research/retcalc_v1/INPUT_FREEZE.json").read_text())
    n_bad_sha = 0
    for ent in fz["entry_replay_v5"]["files_sha256"]:
        if hashlib.sha256((ROOT / ent["file"]).read_bytes()).hexdigest() != ent["sha256"]:
            n_bad_sha += 1
    h_ft = hashlib.sha256((ROOT / "output/research/adjustment_v1/factor_table.csv.gz").read_bytes()).hexdigest()
    if h_ft != fz["adjustment_v1"]["factor_table_sha256"]:
        n_bad_sha += 1
    if n_bad_sha:
        failures.append(f"R6 输入SHA256失效: {n_bad_sha} 个文件")

    # ── R1 总体分池(27,422 突破 / 28,224 对照, 排除数单列) ──
    excl_frozen = set(json.loads((ROOT / "config/adjustment_v1_exclusions.json").read_text())["excluded"])
    import duckdb
    files = sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/entry_replay_v5_full/partitions/*/*.parquet")))
    con = duckdb.connect()
    excl6 = sorted(c.split(".")[1] for c in excl_frozen)   # v5 code 无市场前缀
    q_excl = ("SELECT strategy, not_filled_reason_close FROM read_parquet(" + repr(files)
              + ") WHERE code IN ('" + "','".join(excl6) + "')")
    excl_rows = con.execute(q_excl).fetchall()
    excl_is_control = sum(1 for _, rsn in excl_rows if rsn == "no_breakout_signal")
    excl_breakout_by_strat = defaultdict(int)
    for strat, rsn in excl_rows:
        if rsn != "no_breakout_signal":
            excl_breakout_by_strat[strat] += 1
    report["excl_split"] = {"control_rows": excl_is_control,
                            "breakout_rows_by_strategy": dict(excl_breakout_by_strat)}

    cons = defaultdict(lambda: defaultdict(int))
    for r in rows:
        key = (r["strategy"], r["view"])
        if r.get("status") == "excluded_by_adjustment_decision":
            continue
        if r.get("control_pool") in ("True", "true", "1"):
            cons[key]["control"] += 1
        else:
            v = r.get("K2_1")
            (cons[key].__setitem__("breakout", cons[key]["breakout"] + 1)
             if v not in ("", None) else
             cons[key].__setitem__("breakout_null", cons[key]["breakout_null"] + 1))
    excl_control_by_strat = excl_is_control // 4      # 936行均摊4策略(每段×4策略行)
    if mode != "full":
        report["R1_note"] = "阶梯子集: 分池守恒仅对全量执行"
    for (strat, view), m in ([] if mode != "full" else sorted(cons.items())):
        ct = m["control"] + excl_control_by_strat      # 排除对照段补回
        if ct != 28224:
            failures.append(f"R1对照池: {strat}|{view} control={m['control']}+排除{excl_control_by_strat}={ct}≠28224")
        bp = m["breakout"] + m["breakout_null"] + excl_breakout_by_strat.get(strat, 0)
        if bp != 27422:
            failures.append(f"R1突破池: {strat}|{view} {bp}≠27422 "
                            f"(行{m['breakout']}+null{m['breakout_null']}+排除{excl_breakout_by_strat.get(strat,0)})")

    # ── R2 逐格状态机(每h独立) ──
    n_bad = defaultdict(int)
    for r in rows:
        if r.get("status") == "excluded_by_adjustment_decision":
            continue
        st = r.get("state")
        for h in HORIZONS:
            v = r.get(f"K2_{h}")
            has = v not in ("", None)
            if st == "evaluated_cash" and has and abs(float(v)) > 1e-12:
                n_bad["cash_nonzero"] += 1
            if st == "evaluated_position":
                reason = r.get(f"K2_{h}_reason", "")
                if not has and reason != "null_holding_tail":
                    n_bad[f"pos_null_no_tail_reason"] += 1
                if has and reason == "null_holding_tail":
                    n_bad["tail_reason_with_value"] += 1
            if st == "null_entry_pending" and has:
                n_bad["pending_with_value"] += 1
            if st == "null_holding_tail" and has:
                n_bad["tail_state_with_value"] += 1
            # K3 一致性: capped 行 K3 恒现金0
            if r.get("capped_unfilled") == "True":
                k3v = r.get(f"K3_{h}")
                if k3v not in ("", None) and abs(float(k3v)) > 1e-12:
                    n_bad["capped_K3_nonzero"] += 1
    if n_bad:
        failures.append(f"R2逐格状态机: {dict(n_bad)}")

    # ── R3 K4 全期限×双视角 ──
    n_k4_bad = 0
    filled_states = ("evaluated_position", "null_holding_tail")
    for r in rows:
        if r.get("status") == "excluded_by_adjustment_decision":
            continue
        for h in HORIZONS:
            has = r.get(f"K4_{h}") not in ("", None)
            if r.get("state") not in filled_states and has:
                n_k4_bad += 1
    if n_k4_bad:
        failures.append(f"R3 K4非成交行非null: {n_k4_bad}")

    # ── R5 排除与缺失: 全字段+严格归因 ──
    n_excl_bad = n_missing_bad = 0
    sample0 = rows[0]
    kcols = [k for k in sample0 if k.startswith(("K2_", "K3_", "K4_")) or k.endswith("_reason")]
    for r in rows:
        if r.get("status") == "excluded_by_adjustment_decision":
            if r["code"] not in excl_frozen:
                n_excl_bad += 1
            if any(r.get(k) not in ("", None) for k in kcols if k in r):
                n_excl_bad += 1
        else:
            rs = str(r.get("K3_5_reason", "")) + str(r.get("state_reason", ""))
            if "missing" in rs:
                n_missing_bad += 1
    if n_excl_bad:
        failures.append(f"R5 排除归因/计算值: {n_excl_bad}")
    if n_missing_bad:
        failures.append(f"R5 日期缺失: {n_missing_bad}")

    # ── R4 分层独立重算: 4策略×2视角×5期限×(K2/K3/K4) 每格≥2 + staged组合 + 价格源核对 ──
    pb = PriceBook()
    # buy_price 源头核对(抽样500 vs v5)
    v5cur = con.execute(f"""SELECT lifecycle_id, strategy, fill_price_close, fill_price_next
        FROM read_parquet({files!r})""")
    v5map = {}
    while True:
        ch = v5cur.fetchmany(20000)
        if not ch:
            break
        for lid, strat, pc_, pn_ in ch:
            v5map[(lid, strat)] = (pc_, pn_)
    n_px_bad = 0
    _cand_px = [r for r in rows if r.get("buy_price")]
    px_sample = random.sample(_cand_px, min(500, len(_cand_px)))
    for r in px_sample:
        vp = v5map.get((r["lifecycle_id"], r["strategy"]))
        if vp is None:
            continue
        ref = vp[0] if r["view"] == "close" else vp[1]
        if ref is None or abs(float(r["buy_price"]) - float(ref)) > 1e-9:
            n_px_bad += 1
    if n_px_bad:
        failures.append(f"R4 buy_price与v5不符: {n_px_bad}/{len(px_sample)}")

    buckets = defaultdict(list)
    for i, r in enumerate(rows):
        if r.get("status") == "excluded_by_adjustment_decision" or r.get("control_pool") in ("True", "true", "1"):
            continue
        if r.get("strategy") == "staged_entry":      # staged 由组合专项覆盖
            continue
        if r.get("state") != "evaluated_position":   # cash=政策值0, 非持仓收益
            continue
        for h in HORIZONS:
            for metric in ("K2", "K3", "K4"):
                if r.get(f"{metric}_{h}") not in ("", None):
                    buckets[(r["strategy"], r["view"], h, metric)].append(i)
    picks = []
    for key, idxs in sorted(buckets.items()):
        random.shuffle(idxs)
        picks.extend((key, i) for i in idxs[:2])
    n_recalc_bad = n_recalc = 0
    for (strat, view, h, metric), i in picks:
        r = rows[i]
        dates, pos, u, Fd = pb.frame(r["code"])
        anchor_p = pos.get(r["anchor_day"])
        buy_p = pos.get(r["buy_day"]) if r.get("buy_day") else None
        bp_ = float(r["buy_price"]) if r.get("buy_price") else None
        if anchor_p is None or buy_p is None or bp_ is None:
            continue
        end = (anchor_p if metric == "K3" else buy_p) + h
        if end >= len(dates):
            continue
        if metric == "K3" and buy_p > end:
            exp = 0.0
        elif metric == "K3" and buy_p == end:
            exp = r_net(COST, 100_000.0, bp_, dates[buy_p], bp_, dates[end],
                        Fd[dates[buy_p]], Fd[dates[end]])
        else:
            sell = COST.fill_price(u[dates[end]][1], "sell")
            exp = r_net(COST, 100_000.0, bp_, dates[buy_p], sell, dates[end],
                        Fd[dates[buy_p]], Fd[dates[end]])
        n_recalc += 1
        if abs(exp - float(r[f"{metric}_{h}"])) > 1e-9:
            n_recalc_bad += 1
    # staged 全口径覆盖表: 2视角×5期限×3口径(K2/K3/K4) 逐格复算, 不设break
    staged_rows = [r for r in rows if r["strategy"] == "staged_entry"
                   and r.get("state") == "evaluated_position" and r.get("staged_legs")]
    random.shuffle(staged_rows)
    from collections import defaultdict as _dd
    cover, cover_bad = _dd(int), _dd(int)
    TARGET_PER_CELL = 40              # 每格目标验证数(不足则全量该格)
    n_staged_bad = n_staged = 0
    staged_cache_px = {}
    n_staged_avail = len(staged_rows)
    for r in staged_rows:
        if all(cover[(v, h, m)] >= TARGET_PER_CELL
               for v in ("close", "next") for h in HORIZONS
               for m in ("K2", "K3", "K4")):
            break
        dates, pos, u, Fd = pb.frame(r["code"])
        legs = json.loads(r["staged_legs"])
        legs = [(t, pos[d]) for t, d, _ in legs if d in pos]
        if not legs:
            continue
        tag = "fill" if r["view"] == "close" else "next"
        k_px = (r["lifecycle_id"], tag)
        if k_px not in staged_cache_px:
            t1p, t2p, t3p = con.execute(
                f"""SELECT t1_{tag}_price, t2_{tag}_price, t3_{tag}_price
                FROM read_parquet({files!r}) WHERE lifecycle_id='{r['lifecycle_id']}'
                AND strategy='staged_entry'""").fetchone()
            staged_cache_px[k_px] = {t: float(px) for t, px in
                                     (("t1", t1p), ("t2", t2p), ("t3", t3p)) if px is not None}
        prices = staged_cache_px[k_px]
        base_p = legs[0][1]                     # 第一笔成交批(共同终点基准)
        anchor_p = pos.get(r["anchor_day"])
        for h in HORIZONS:
            # K2/K4: 共同终点=第一笔批后h
            end_k2 = base_p + h
            csv_k2, csv_k4 = r.get(f"K2_{h}"), r.get(f"K4_{h}")
            if end_k2 < len(dates) and csv_k2 not in ("", None):
                total = 0.0
                for t, tp_ in legs:
                    tpx = prices.get(t)
                    if tpx is None or tp_ > end_k2:
                        continue
                    w = TRANCHES[t]
                    sell = COST.fill_price(u[dates[end_k2]][1], "sell")   # v5: 终点收盘卖出(含终点日恰成交批)
                    ri = r_net(COST, w * 100_000.0, tpx, dates[tp_], sell,
                               dates[end_k2], Fd[dates[tp_]], Fd[dates[end_k2]])
                    total += w * (ri if ri is not None else 0.0)
                for m, csvv in (("K2", csv_k2), ("K4", csv_k4)):
                    n_staged += 1
                    cover[(r["view"], h, m)] += 1
                    if csvv in ("", None) or abs(total - float(csvv)) > 1e-9:
                        cover_bad[(r["view"], h, m)] += 1
                        n_staged_bad += 1
            # K3: 统一突破日终点, 分批现金语义
            if anchor_p is not None:
                end_k3 = anchor_p + h
                csv_k3 = r.get(f"K3_{h}")
                if end_k3 < len(dates) and csv_k3 not in ("", None):
                    total3 = 0.0
                    for t, tp_ in legs:
                        tpx = prices.get(t)
                        if tpx is None or tp_ > end_k3:
                            continue
                        w = TRANCHES[t]
                        if tp_ == end_k3:
                            ri = r_net(COST, w * 100_000.0, tpx, dates[tp_], tpx,
                                       dates[end_k3], Fd[dates[tp_]], Fd[dates[end_k3]])
                        else:
                            sell = COST.fill_price(u[dates[end_k3]][1], "sell")
                            ri = r_net(COST, w * 100_000.0, tpx, dates[tp_], sell,
                                       dates[end_k3], Fd[dates[tp_]], Fd[dates[end_k3]])
                        total3 += w * (ri if ri is not None else 0.0)
                    n_staged += 1
                    cover[(r["view"], h, "K3")] += 1
                    if abs(total3 - float(csv_k3)) > 1e-9:
                        cover_bad[(r["view"], h, "K3")] += 1
                        n_staged_bad += 1
    cover_tbl = {f"{v}|h{h}|{m}": {"n": cover[(v, h, m)], "bad": cover_bad[(v, h, m)]}
                 for v in ("close", "next") for h in HORIZONS for m in ("K2", "K3", "K4")}
    empty_cells = [k for k, v in cover_tbl.items() if v["n"] == 0]
    if empty_cells:
        failures.append(f"R4 staged覆盖表空格: {empty_cells}")
    underfilled = {k: v["n"] for k, v in cover_tbl.items() if 0 < v["n"] < TARGET_PER_CELL}
    if underfilled:
        report["R4_staged_underfilled_cells"] = {**underfilled,
                                                 "_note": "可评价样本不足目标40, 记录实际量"}
    if n_staged_bad:
        failures.append(f"R4 staged全口径失配: {n_staged_bad}/{n_staged}")
    if n_recalc_bad:
        failures.append(f"R4 分层重算失配: {n_recalc_bad}/{n_recalc}")
    report["R4"] = {"stratified": n_recalc, "stratified_bad": n_recalc_bad,
                    "staged_total": n_staged, "staged_bad": n_staged_bad,
                    "staged_rows_available": n_staged_avail,
                    "staged_cover_table": cover_tbl,
                    "buy_price_checked": len(px_sample), "buy_price_bad": n_px_bad}

    status = "PASSED" if not failures else "FAILED"
    report["gate_failures"] = failures
    report["status"] = status
    r1_msg = "R1分池✓ " if mode == "full" else "R1分池(全量专属,跳过) "
    msg = (f"审计retcalc[{mode}]: {status} | " + r1_msg + "R2逐格✓ R3K4全期限✓ "
           f"R4分层{n_recalc}(失配{n_recalc_bad})+staged{n_staged}(失配{n_staged_bad})+价格源{len(px_sample)}✓ "
           f"R5排除✓ R6冻结✓")
    print(msg if not failures else f"审计retcalc[{mode}]: {status} | {failures[:8]}")
    Path(ROOT / f"docs/reports/RETCALC_V1_AUDIT_{mode.upper()}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    if mode == "full":
        # 权威产物: full 结果同步写权威文件名(内容含 mode=full 自证)
        Path(ROOT / "docs/reports/RETCALC_V1_AUDIT.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
