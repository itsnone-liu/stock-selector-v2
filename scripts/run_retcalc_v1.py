#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_retcalc_v1.py — retcalc_v1 运行入口 (STAGE5 v7.1, 2026-09-21).

阶梯: --smoke 50(50只) → --medium 300 → 全量(默认).
输出 output/research/retcalc_v1/<mode>/retcalc.csv(.gz) + SUMMARY.json
  (四态计数×策略×视角×h + N_master 守恒式 + 排除行/对照池披露 + v5黄金对账抽样)
"""
import argparse
import glob
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

from stock_selector.decision.execution import CostModel          # noqa: E402
from stock_selector.research.retcalc import (                    # noqa: E402
    CAPITAL, HORIZONS, StockFrame, k2_state, k2_view, k3_view)

V5_GLOB = "output/research/lifecycle_v1/entry_replay_v5_full/partitions/*/*.parquet"
FT = ROOT / "output/research/adjustment_v1/factor_table.csv.gz"
SRC = ROOT / "data/adjustment_baostock/per_stock"
COST = CostModel()
# 冻结排除清单(用户裁决 24 只): 加载失败仅当属于此清单才可记为排除, 否则必须终止
EXCL_FROZEN = set(json.loads((ROOT / "config/adjustment_v1_exclusions.json").read_text())["excluded"])


def verify_input_freeze():
    """执行时验证: INPUT_FREEZE 记录的 v5 partitions/factor_table SHA256 逐一重算比对."""
    fp = ROOT / "output/research/retcalc_v1/INPUT_FREEZE.json"
    if not fp.exists():
        raise SystemExit("INPUT_FREEZE.json 缺失: 先跑 retcalc_freeze_and_map.py")
    import hashlib
    fz = json.loads(fp.read_text())
    for ent in fz["entry_replay_v5"]["files_sha256"]:
        h = hashlib.sha256((ROOT / ent["file"]).read_bytes()).hexdigest()
        if h != ent["sha256"]:
            raise SystemExit(f"输入冻结失效: {ent['file']} SHA256 不符")
    h = hashlib.sha256((ROOT / "output/research/adjustment_v1/factor_table.csv.gz").read_bytes()).hexdigest()
    if h != fz["adjustment_v1"]["factor_table_sha256"]:
        raise SystemExit("输入冻结失效: factor_table SHA256 不符")


def to_prefixed(code6):
    s = str(code6)
    if len(s) == 6 and s[0] in "036":
        return ("sh." if s[0] == "6" else "sz.") + s
    return None


def load_factor_index():
    """因子表: 每股 {date: F}. (冻结产物, F 即权威)"""
    F = defaultdict(dict)
    with gzip.open(FT, "rt") as f:
        next(f)
        for line in f:
            code, d, uc, hc, Fv = line.rstrip("\n").split(",")
            F[code][d] = float(Fv)
    return F


def load_stock(code, Fidx):
    """StockFrame: 日期序 = TDX 行情日历(与 v5/Stage4 同序, 保证"第h交易日"语义一致);
    F/open/close 按 date 从 baostock per_stock+冻结因子表查值.
    G4 正向已证 TDX 窗口日 100% 存在于 baostock(价格一致), 故逐日可查; 缺→显式报错."""
    import gzip as gz
    import struct
    p = json.load(gz.open(SRC / f"{code}.json.gz", "rt"))
    u = {r[0]: (float(r[1]), float(r[4])) for r in p["unadj"]}
    Fd = Fidx.get(code, {})
    mkt, num = code.split(".")
    lfp = Path("/root/tdx_data/vipdoc") / mkt / "lday" / f"{mkt}{num}.day"
    b = lfp.read_bytes()
    dates = []
    for i in range(len(b) // 32):
        d = struct.unpack("<IIIIIfIf", b[i * 32:(i + 1) * 32])[0]
        ds = f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}"
        dates.append(ds)
    dates = [d for d in dates if d in u and d in Fd]   # TDX∩baostock(重合=完整窗口)
    if not dates:
        raise ValueError("empty tdx∩baostock calendar")
    return StockFrame(dates=dates, pos={d: i for i, d in enumerate(dates)},
                      open_={d: u[d][0] for d in dates},
                      close={d: u[d][1] for d in dates},
                      F={d: Fd[d] for d in dates})


def dv(x):
    return None if x is None else (x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)[:10])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", type=int, default=0, help="前N只股(阶梯第一级)")
    ap.add_argument("--medium", type=int, default=0)
    ap.add_argument("--start", default="2026-06-01", help="锚日下界(smoke默认近3月)")
    ap.add_argument("--end", default="2026-09-01")
    a = ap.parse_args()
    mode = f"smoke{a.smoke}" if a.smoke else (f"medium{a.medium}" if a.medium else "full")
    OUT = ROOT / "output/research/retcalc_v1" / mode
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    verify_input_freeze()
    print("输入SHA256执行时验证 ✓", flush=True)

    print("加载因子表...", flush=True)
    Fidx = load_factor_index()

    import duckdb
    con = duckdb.connect()
    files = sorted(glob.glob(str(ROOT / V5_GLOB)))
    lim = f"AND anchor_day BETWEEN '{a.start}' AND '{a.end}'" if (a.smoke or a.medium) else ""
    q = f"""
    SELECT * FROM read_parquet({files!r}) WHERE 1=1 {lim}
    """
    # 注意: 同一 duckdb connection 上后一个 execute 会顶掉前一个结果集
    # → 先取阶梯选股清单, 再执行主查询
    sel = None
    if a.smoke or a.medium:
        codes_q = f"""SELECT DISTINCT code FROM read_parquet({files!r})
                      WHERE anchor_day BETWEEN '{a.start}' AND '{a.end}' ORDER BY 1"""
        sel = [r[0] for r in con.execute(codes_q).fetchall()]
        sel = set(sel[: (a.smoke or a.medium)])
        print(f"阶梯 {mode}: {len(sel)} 只 × 锚日 [{a.start},{a.end}]", flush=True)
    cur = con.execute(q)
    cols = {d[0]: i for i, d in enumerate(cur.description)}

    rows_out = []
    stats = {}
    n_control = n_excluded = n_rows = n_factor_adj = 0
    golden = []          # 黄金对账抽样(F恒定行: retcalc K2 vs v5 ret_net)
    cache: dict[str, StockFrame | None] = {}

    while True:
        chunk = cur.fetchmany(5000)
        if not chunk:
            break
        for row in chunk:
            g = lambda k: row[cols[k]]
            code6 = str(g("code"))
            if (a.smoke or a.medium) and code6 not in sel:
                continue
            n_rows += 1
            pc = to_prefixed(code6)
            sf = cache.get(pc, "?") if pc else None
            if sf == "?" or (sf is None and pc not in cache):
                try:
                    sf = load_stock(pc, Fidx) if pc else None
                except Exception as e:
                    if pc in EXCL_FROZEN:
                        sf = None          # 冻结排除股: 无因子表属预期
                    else:
                        raise RuntimeError(f"非排除股 {pc} 加载失败: {e}") from e
                cache[pc] = sf
            strategy = g("strategy")
            is_control = g("not_filled_reason_close") == "no_breakout_signal"
            n_control += is_control
            if sf is None:
                n_excluded += 1
                rows_out.append({"code": pc or code6, "lifecycle_id": g("lifecycle_id"),
                                 "strategy": strategy, "status": "excluded_by_adjustment_decision"})
                continue
            anchor = dv(g("anchor_day"))
            anchor_pos = sf.pos.get(anchor)
            for view in ("close", "next"):
                sfx = view
                # 成交判定统一用 fill_date_*/fill_price_*: 对 staged 该字段=第一笔
                # 实际成交批次(Stage4 v5 冻结; close恒T1, next=T1失败时T2/T3)
                bd = g(f"fill_date_{sfx}")
                bp = g(f"fill_price_{sfx}")
                filled = bd is not None and bp is not None
                buy_pos = sf.pos.get(dv(bd)) if filled else None
                buy_price = float(bp) if bp is not None else None
                staged_legs = None
                if strategy == "staged_entry" and filled:
                    tag = "fill" if view == "close" else "next"
                    staged_legs = []
                    for t in ("t1", "t2", "t3"):
                        td = dv(g(f"{t}_{tag}_date"))
                        tp = g(f"{t}_{tag}_price")
                        if td is not None and tp is not None and td in sf.pos:
                            staged_legs.append((t, sf.pos[td], float(tp)))
                capped = (strategy == "direct_chase" and g("capped_entered") is not None
                          and bool(g("capped_entered")) is False)
                base = {"code": pc, "lifecycle_id": g("lifecycle_id"), "strategy": strategy,
                        "view": view, "anchor_day": anchor, "buy_day": dv(bd),
                        "buy_price": buy_price,
                        "staged_legs": (json.dumps([(t, sf.dates[tp], tp) for t, tp, _ in staged_legs])
                                        if staged_legs else None),
                        "control_pool": is_control, "capped_unfilled": capped}
                if anchor_pos is None:
                    base.update({f"K3_{h}": None for h in HORIZONS},
                                **{f"K3_{h}_reason": "anchor_date_missing" for h in HORIZONS})
                    rows_out.append(base)
                    continue
                base["anchor_pos"] = anchor_pos
                k3 = k3_view(sf, COST, view, anchor_pos,
                             None if is_control else buy_pos,
                             buy_price, capped_cash=capped,
                             legs=(staged_legs if strategy == "staged_entry" else None))
                if is_control:
                    k3 = {k: (None if k.startswith("K3_") and not k.endswith("_reason")
                              else ("no_breakout_control" if k.endswith("_reason") else None))
                          for k in k3}
                base.update(k3)
                if is_control:
                    st = ("evaluated_cash", "no_breakout_signal")
                else:
                    end_probe = (buy_pos + HORIZONS[0]) if buy_pos is not None else None
                    # 逐视角: filled 已是本视角 fill_status; 右删失=生命周期级
                    st = k2_state(filled, capped, False,
                                  bool(g("right_censored")),
                                  end_probe, len(sf.dates) - 1)
                base["state"] = st[0]
                base["state_reason"] = st[1]
                if st[0] == "evaluated_position":
                    if strategy == "staged_entry":
                        k2 = k2_view(sf, COST, view, staged_legs[0][1],
                                     staged_legs[0][2], legs=staged_legs) if staged_legs else {}
                    else:
                        k2 = k2_view(sf, COST, view, buy_pos, buy_price)
                    base.update(k2)
                    # 黄金对账抽样(单笔策略×双视角, 持有窗内F严格恒定): K2_5==v5 ret_net_5
                    # staged 不在此处(组合口径, 由审计R4独立复算); F 变化行计数=复权修正规模
                    if buy_pos is not None and buy_pos + 5 < len(sf.dates) \
                            and abs(sf.F[sf.dates[buy_pos + 5]] / sf.F[sf.dates[buy_pos]] - 1) > 1e-12:
                        n_factor_adj += 1
                    if strategy != "staged_entry" and len(golden) < 400:
                        v5r = g(f"ret_net_5_{view}")
                        if v5r is not None and buy_pos is not None:
                            if abs(sf.F[sf.dates[min(buy_pos + 5, len(sf.dates) - 1)]] / sf.F[sf.dates[buy_pos]] - 1) < 1e-12:
                                golden.append({"code": pc, "view": view,
                                               "K2_5": base.get("K2_5"),
                                               "v5_ret_net_5": float(v5r) / 100.0})
                else:
                    base.update({f"K2_{h}": (0.0 if st[0] == "evaluated_cash" else None)
                                 for h in HORIZONS})
                    base.update({f"K4_{h}": None for h in HORIZONS})
                    base.update({f"K2_{h}_reason": st[0] for h in HORIZONS})
                stats[f"{strategy}|{view}|{st[0]}"] = stats.get(f"{strategy}|{view}|{st[0]}", 0) + 1
                rows_out.append(base)
        if n_rows and n_rows % 20000 < 5000:
            print(f"[{n_rows}行] out={len(rows_out)} excl={n_excluded} {time.time()-t0:.0f}s", flush=True)

    import csv
    fieldnames = sorted({k for r in rows_out for k in r}, key=str)
    with gzip.open(OUT / "retcalc.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)
    # 黄金对账
    g_bad = [x for x in golden if x["K2_5"] is None or abs(x["K2_5"] - x["v5_ret_net_5"]) > 1e-9]
    summary = {"mode": mode, "n_rows_read": n_rows, "n_out": len(rows_out),
               "n_control_pool": n_control, "n_excluded_adjustment": n_excluded,
               "state_counts": stats,
               "n_factor_adjusted_rows_h5_close": n_factor_adj,
               "golden_check": {"n_sampled": len(golden), "n_mismatch": len(golden) - sum(1 for x in golden if x['K2_5'] is not None and abs(x['K2_5'] - x['v5_ret_net_5']) <= 1e-9)},
               "horizons": list(HORIZONS), "elapsed_s": round(time.time() - t0, 1)}
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    print(f"完成 {mode}: 读{n_rows}行 出{len(rows_out)}行(含双视角) 对照{sum(1 for r in rows_out if r.get('control_pool'))} "
          f"排除{n_excluded} 黄金对账{len(golden)}样本 失配{summary['golden_check']['n_mismatch']} | {time.time()-t0:.0f}s")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
