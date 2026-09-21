#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_forward_outcome_audit.py — forward_outcome_v1 标签可行性审计 (2026-09-21 放行).

冻结(详见 FORWARD_OUTCOME_V1_SPEC.md):
- 主指标 Y40 = ln(P[t+40]/P[t]) − ln(I[t+40]/I[t])
  P=股票复权收盘(raw×F, hfq 总收益口径), I=基准指数(上证 sh999999, 价格收益口径)
  t+40=市场日历(上证日历)自观察日起第 40 个交易日
- 辅助: 持有期最大回撤(窗内复权收盘相对此前最高收盘最大跌幅, 连续值);
  趋势持续性(8×5 日区间相对基准收益为正的区间占比)
- 窗口缺失处理(冻结): t+40 市场日股票无价但窗内有价→用窗内最后可得收盘
  (imputed_flag, 持仓市值近似); 窗内全无价→missing(单列计数不静默删);
  t+40 市场日不存在→data_end_censored(数据末端)
产出: FORWARD_OUTCOME_V1_AUDIT.json
"""
import csv
import gzip
import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "output/research/posneg_v1"
from stock_selector.research.identify_features import eligibility_forward_v1  # noqa: E402
from build_identify_features import load_stock                              # noqa: E402

H = 40


def market_calendar():
    b = Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day").read_bytes()
    # TDX day 记录 32 字节: date(4) open(4) high(4) low(4) close(4) ...
    dates, close = [], []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        dates.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
        close.append(struct.unpack("<f", b[i * 32 + 16:i * 32 + 20])[0])
    return dates, np.array(close)


def main():
    t0 = time.time()
    mdates, mclose = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            F.setdefault(row["code"], {})[row["date"]] = float(row["F"])
    cache = {}
    audit = {"spec": "FORWARD_OUTCOME_V1_SPEC.md", "horizon_trading_days": H,
             "market_calendar": {"first": mdates[0], "last": mdates[-1], "n": len(mdates)},
             "benchmark": {"code": "sh999999(TDX 上证指数)", "price": "close(TDX float)",
                           "return_basis": "价格收益(无分红); 股票侧=hfq 总收益 → 已知口径偏差(见 SPEC §1.3)"},
             "datasets": {}, "caveats": []}
    for ds in ("breakout", "shrink", "stabilization"):
        rows = [r for r in csv.DictReader(gzip.open(OUT / f"identify_{ds}.csv.gz", "rt"))]
        elig = [r for r in rows if eligibility_forward_v1(r)]
        stat = Counter()
        y40s, mdds, trends = [], [], []
        for r in elig:
            code = r["code"]
            if code not in cache:
                dates = load_stock(code, F)[0]
                j = json.load(gzip.open(ROOT / f"data/adjustment_baostock/per_stock/{code}.json.gz", "rt"))
                padj = {row[0]: float(row[4]) * F[code].get(row[0], 1.0) for row in j["unadj"]}
                pos = {d: i for i, d in enumerate(dates)}
                cache[code] = (dates, pos, padj)
            dates, pos, padj = cache[code]
            t = r["obs_day"]
            mi = mpos.get(t)
            if mi is None or mi + H >= len(mdates):
                stat["data_end_censored"] += 1
                continue
            t40 = mdates[mi + H]
            p0 = padj.get(t)
            if p0 is None:
                stat["obs_day_no_price"] += 1
                continue
            p40 = padj.get(t40)
            imputed = False
            if p40 is None:
                # 窗内最后可得收盘(停牌持仓市值近似)
                back = None
                for k in range(mi + H, mi, -1):
                    if mdates[k] in padj:
                        back = mdates[k]
                        break
                if back is None:
                    stat["window_all_missing"] += 1
                    continue
                p40 = padj[back]
                imputed = True
                stat["imputed_last_available"] += 1
            rel = np.log(p40 / p0) - np.log(mclose[mi + H] / mclose[mi])
            y40s.append(rel)
            # 辅助: 回撤 + 趋势持续性(仅完整窗样本)
            closes = [padj.get(mdates[k]) for k in range(mi, mi + H + 1)]
            cc = [c for c in closes if c is not None]
            if len(cc) >= 2:
                run_max, mdd = cc[0], 0.0
                for c in cc:
                    run_max = max(run_max, c)
                    mdd = min(mdd, c / run_max - 1)
                mdds.append(mdd)
            seg_pos = 0
            seg_n = 0
            for si in range(8):
                a, bidx = mi + si * 5, mi + si * 5 + 5
                pa, pb = padj.get(mdates[a]), padj.get(mdates[bidx])
                if pa and pb:
                    seg_n += 1
                    if np.log(pb / pa) - np.log(mclose[bidx] / mclose[a]) > 0:
                        seg_pos += 1
            if seg_n:
                trends.append(seg_pos / seg_n)
            if not imputed:
                stat["complete_window"] += 1
        def q(v):
            v = np.array(v)
            return {"n": len(v), "mean": round(float(v.mean()), 5),
                    "p5": round(float(np.percentile(v, 5)), 4),
                    "p25": round(float(np.percentile(v, 25)), 4),
                    "p50": round(float(np.percentile(v, 50)), 4),
                    "p75": round(float(np.percentile(v, 75)), 4),
                    "p95": round(float(np.percentile(v, 95)), 4),
                    "pos_rate": round(float((v > 0).mean()), 4)}
        audit["datasets"][ds] = {
            "n_rows": len(rows), "n_eligible": len(elig),
            "excl_after_obs": len(rows) - len(elig),
            "outcome_window": dict(stat),
            "Y40_logrel": q(y40s), "max_drawdown": q(mdds),
            "trend_persistence_pos_share": q(trends)}
        print(f"{ds}: 行 {len(rows)} 资格 {len(elig)} | " +
              " ".join(f"{k}={v}" for k, v in stat.items()) +
              f" | Y40 p50={audit['datasets'][ds]['Y40_logrel']['p50']} | {time.time()-t0:.0f}s", flush=True)
    audit["caveats"] = [
        "存活偏差(重大): 数据源 5240 股仅 6 股末端早于 2026-06——退市股基本不在数据中, "
        "Y40 分布系统性偏乐观, 结果仅代表存活到数据末端的股票",
        "口径偏差: 股票=hfq 总收益 vs 基准=上证价格收益(无分红), A股年均股息~2%→40日~0.3% 系统性低配基准方向, 已知且同向",
        "imputed(停牌近似)与 data_end_censored 计数单列, 未静默删除",
    ]
    (OUT / "FORWARD_OUTCOME_V1_AUDIT.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=1))
    print(f"→ FORWARD_OUTCOME_V1_AUDIT.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
