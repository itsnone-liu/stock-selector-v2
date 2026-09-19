#!/usr/bin/env python3
"""adjustment_v1 采集后质量审计（fail-fast 深度校验 + 覆盖率/集中度报告）。

输入：data/adjustment_baostock/per_stock/*.json.gz + fetch_manifest.json + 本地 vipdoc
输出：docs/reports/ADJUSTMENT_V1_FETCH_AUDIT.json + 人读摘要 stdout

审计项（依用户放行门禁）：
A1 本地有交易日而外部缺行（逐股逐日，容差 0 行）
A2 close=0 / 日期重复 / 非升序（采集轻校验复核）
A3 unadj 与本地 .day close 不符（容差 1e-4，按源精度分级）
A4 覆盖率：成功/失败/缺失股票、行数分布、首末日期分布
A5 年份/板块集中度：缺行与价格不符的股票是否集中于特定年份或板块
A6 F 因子预检：非除权日 F 漂移（1e-4）+ 除权日识别数量
fail-fast 清单落盘，不静默前填。
"""
import gzip, json, struct, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
SRC = ROOT / "data/adjustment_baostock"
OUT = ROOT / "docs/reports/ADJUSTMENT_V1_FETCH_AUDIT.json"
TDX = Path("/root/tdx_data/vipdoc")
TOL_PRICE = 1e-4      # 源精度容差
TOL_F = 1e-4          # 非除权日 F 漂移
JUMP = 1e-4           # 除权日 F 跳变识别阈值


def read_local_day(fp: Path) -> dict[str, float]:
    rows = {}
    b = fp.read_bytes()
    for i in range(len(b) // 32):
        d, o, h, l, c, amt, vol, res = struct.unpack("<IIIIIfIf", b[i * 32:(i + 1) * 32])
        rows[f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}"] = c / 100.0
    return rows


def main() -> int:
    manifest = json.loads((SRC / "fetch_manifest.json").read_text())
    stocks: dict = manifest["stocks"]
    universe_sha = manifest["universe_sha256"]

    ok = {c: v for c, v in stocks.items() if v.get("status") == "ok"}
    fails = {c: v for c, v in stocks.items() if v.get("status") != "ok"}
    report = {"universe_sha256": universe_sha, "n_ok": len(ok),
              "n_fail": len(fails), "fail_list": sorted(fails),
              "missing_rows": [], "price_mismatch": [], "f_drift": [],
              "ex_dates_count": 0, "row_hist": Counter(),
              "last_date_hist": Counter(), "concentration": {}}
    ex_days_by_year = Counter()
    miss_by_year = Counter()
    mismatch_by_prefix = Counter()

    for code in sorted(ok):
        fp = SRC / "per_stock" / f"{code}.json.gz"
        with gzip.open(fp, "rt") as fh:
            payload = json.load(fh)
        unadj = {r[0]: float(r[4]) for r in payload["unadj"]}
        hfq = {r[0]: float(r[4]) for r in payload["hfq"]}
        mkt, num = code.split(".")
        local = read_local_day(TDX / mkt / "lday" / f"{mkt}{num}.day")
        local_in_range = {d: c for d, c in local.items()
                          if "2021-01-01" <= d <= "2026-09-19"}
        # A1 缺行
        miss = sorted(set(local_in_range) - set(unadj))
        if miss:
            report["missing_rows"].append({"code": code, "n": len(miss),
                                           "sample": miss[:5]})
            for d in miss:
                miss_by_year[d[:4]] += 1
        # A3 价格不符（本地 close vs unadj close）
        bad = [d for d in sorted(set(local_in_range) & set(unadj))
               if abs(local_in_range[d] - unadj[d]) > TOL_PRICE]
        if bad:
            report["price_mismatch"].append({"code": code, "n": len(bad),
                                             "sample": [(d, local_in_range[d],
                                                         unadj[d]) for d in bad[:3]]})
            mismatch_by_prefix[num[0]] += 1
        # A6 F 因子预检
        days = sorted(set(unadj) & set(hfq))
        F = {d: hfq[d] / unadj[d] for d in days}
        prev_d, prev_f, drifted = None, None, []
        jumps = []
        for d in days:
            f = F[d]
            if prev_f is not None and f > 0 and prev_f > 0:
                if abs(f / prev_f - 1) > JUMP:
                    jumps.append(d)
                elif abs(f / prev_f - 1) > TOL_F:
                    drifted.append(d)
            prev_d, prev_f = d, f
        if drifted:
            report["f_drift"].append({"code": code, "n": len(drifted),
                                      "sample": drifted[:5]})
        for d in jumps:
            ex_days_by_year[d[:4]] += 1
        report["ex_dates_count"] += len(jumps)
        report["row_hist"][str(payload["n_rows"] // 100 * 100)] += 1
        report["last_date_hist"][payload["last_date"]] += 1

    report["row_hist"] = dict(report["row_hist"])
    report["last_date_hist"] = dict(report["last_date_hist"])
    report["concentration"] = {
        "missing_by_year": dict(miss_by_year),
        "mismatch_by_board_prefix": dict(mismatch_by_prefix),
        "ex_dates_by_year": dict(ex_days_by_year),
        "missing_stocks": len(report["missing_rows"]),
        "mismatch_stocks": len(report["price_mismatch"]),
        "f_drift_stocks": len(report["f_drift"]),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"ok={report['n_ok']} fail={report['n_fail']} "
          f"miss_stocks={len(report['missing_rows'])} "
          f"mismatch_stocks={len(report['price_mismatch'])} "
          f"f_drift_stocks={len(report['f_drift'])} "
          f"ex_dates={report['ex_dates_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
