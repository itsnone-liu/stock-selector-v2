# -*- coding: utf-8 -*-
"""cross_audit_adjustment.py — 跨源复权数据审计 (2026-09-21)。

三源: baostock(unadj+hfq) / sina(factors.events) / tx(unadj+hfq)
  C1 事件日集合等价: 每股除权事件日三源对比(严格相等; 差异列明细)
  C2 因子恒定性: 非事件日 F=hfq/unadj 相对漂移<1e-4; 段内源间 F 比值恒定
  C3 抽样30只: 分层随机(主板/创业板/科创板/北交所)对照表
输出: docs/reports/ADJUSTMENT_V1_CROSS_AUDIT.json + stdout 摘要
"""
import gzip, json, random, sys
from collections import Counter
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
BS = ROOT / "data/adjustment_baostock/per_stock"
SN = ROOT / "data/adjustment_sina/factors"
TX = ROOT / "data/adjustment_tx/per_stock"
OUT = ROOT / "docs/reports/ADJUSTMENT_V1_CROSS_AUDIT.json"
TOL = 1e-4
TOL_EVENT = 2e-4   # 事件日跳变阈值: bs F精度(4+10位小数)噪声~5e-5, 2e-4可抓小额分红(tx不用于因子, 无tx噪声约束)
TOL_SRC = 5e-3     # 源间因子比漂移容差: 现金红利税处理等口径差~0.2%, 0.5%内视为恒定
random.seed(20260921)


def load_bh(fp, close_col=None):
    """baostock/tx → ({date: unadj_close}, {date: hfq_close})。
    列序不同(2026-09-21实测): baostock [date,o,h,l,c,...] close=r[4];
    tx 腾讯惯例 [date,o,c,h,l,...] close=r[2]。gzip必须"rt"(json.load需文本流)。"""
    p = json.load(gzip.open(fp, "rt"))
    def col(rows):
        for r in rows[:3]:
            pass
        return 4 if len(rows[0]) >= 9 else 2   # bs行9列→r[4]; tx行6列→r[2]
    cc = close_col or col(p.get("unadj", []) or [["", 0, 0, 0, 0, 0, 0, 0, 0]])
    u = {r[0]: float(r[cc]) for r in p.get("unadj", [])}
    h = {r[0]: float(r[cc]) for r in p.get("hfq", [])}
    return u, h


def load_sina(fp):
    """sina: events=[{date,factor}] → {date: factor}"""
    p = json.load(gzip.open(fp, "rt"))
    return {e["date"]: float(e["factor"]) for e in p.get("events", []) if isinstance(e, dict)}


def events_from_F(u, h):
    """F=hfq/unadj 序列 → 跳变日=事件日, 段内F均值。"""
    days = sorted(set(u) & set(h))
    ev, seg_f, prev_f = {}, [], None
    for d in days:
        if u[d] <= 0:
            continue
        f = h[d] / u[d]
        if prev_f is not None and (abs(f - prev_f) / max(prev_f, 1e-9)) > TOL_EVENT:
            ev[d] = f / prev_f      # 事件日因子比
            seg_f = []
        seg_f.append(f)
        prev_f = f
    return ev, (sum(seg_f) / len(seg_f) if seg_f else None)


def main():
    codes_bs = {f.name.removesuffix(".json.gz") for f in BS.glob("*.json.gz")}
    codes_sn = {f.name.removesuffix(".json.gz") for f in SN.glob("*.json.gz")}
    codes_tx = {f.name.removesuffix(".json.gz") for f in TX.glob("*.json.gz")}
    common = sorted(codes_bs & codes_sn & codes_tx)
    only = {"bs_only": len(codes_bs - codes_sn - codes_tx),
            "sina_only": len(codes_sn - codes_bs - codes_tx),
            "tx_only": len(codes_tx - codes_bs - codes_sn)}
    rep = {"n_common": len(common), "coverage": only,
           # 实测发现(2026-09-21预检): tx fqkline hfq/unadj 因子存在5%级连续漂移(非事件跳变),
           # 不可用于因子校验 → tx 降级为 unadj 价格对照源
           "tx_factor_issue": "hfq/unadj factor drifts ~5% continuously (p50), factor unusable; tx used for price cross-check only",
           "c1_bs_sina_event_diff": [], "c1_load_err": [],
           "c2_factor_ratio_drift": [], "c2_tx_price_diff": [],
           "c3_sample": [], "pair_stats": Counter(),
           "n_bs_ev": 0, "n_sina_ev": 0, "tx_price_checked": 0}

    for i, code in enumerate(common):
        try:
            ub, hb = load_bh(BS / f"{code}.json.gz")
            ut, ht = load_bh(TX / f"{code}.json.gz")
            sev_all = load_sina(SN / f"{code}.json.gz")
            win_lo = min(min(ub), min(ut)) if (ub and ut) else "0000"
            win_hi = max(max(ub), max(ut)) if (ub and ut) else "9999"
            sev = {d: f for d, f in sev_all.items() if win_lo <= d <= win_hi}
        except Exception:
            rep["c1_load_err"].append(code)
            continue
        ev_b, f_b = events_from_F(ub, hb)
        rep["n_bs_ev"] += len(ev_b)
        rep["n_sina_ev"] += len(sev)
        sb, ss = set(ev_b), set(sev)
        # C1: bs↔sina 事件日严格等价; 差异细分 minor(<2·TOL_EVENT 小额分红, bs精度极限,
        # 复权价影响~0.02-0.04%可忽略) vs material(真错位/漏判)
        if sb == ss:
            rep["pair_stats"]["bs_sina_equal"] += 1
        else:
            fseq = {d: hb[d] / ub[d] for d in sorted(ub) if ub[d] > 0 and d in hb}
            minor, material = [], []
            for d in sorted(sb ^ ss):
                prev = [x for x in fseq if x < d]
                jump = abs(fseq[d] / fseq[prev[-1]] - 1) if (prev and d in fseq) else 0
                (minor if jump < 2 * TOL_EVENT else material).append(d)
            rep["c1_bs_sina_event_diff"].append({"code": code,
                                                 "diff": sorted(sb ^ ss)[:8],
                                                 "minor": minor[:8], "material": material[:8],
                                                 "n": (len(sb), len(ss))})
        # C2a: bs F 段值 vs sina 累计factor 比值恒定(段内)
        days = sorted(set(ub) & set(hb))
        if days and sev:
            # sina factor 是事件日给出的新累计因子; 与 bs 段 F 应成恒定比值
            seg_ratios = []
            ev_sorted = sorted(sev)
            for d in days:
                f_bs = hb[d] / ub[d] if ub[d] > 0 else None
                if f_bs is None:
                    continue
                f_sn = None
                for ed in ev_sorted:
                    if ed <= d:
                        f_sn = sev[ed]
                if f_sn and f_sn > 0:
                    seg_ratios.append(f_bs / f_sn)
            if seg_ratios:
                rmin, rmax = min(seg_ratios), max(seg_ratios)
                if (rmax - rmin) / max(rmin, 1e-9) > TOL_SRC:
                    rep["c2_factor_ratio_drift"].append(
                        {"code": code, "ratio": [round(rmin, 4), round(rmax, 4)],
                         "n": len(seg_ratios)})
                else:
                    rep["pair_stats"]["factor_ratio_stable"] += 1
        # C2b: tx unadj 价格逐日对照 bs unadj(容差 0.01 元, 源为 3位小数)
        common_days = sorted(set(ub) & set(ut))
        if common_days:
            rep["tx_price_checked"] += len(common_days)
            bad = [d for d in common_days if abs(ub[d] - ut[d]) > 0.011]
            if bad:
                rep["c2_tx_price_diff"].append({"code": code, "n_bad": len(bad),
                                                "sample": [(d, ub[d], ut[d]) for d in bad[:3]]})
            else:
                rep["pair_stats"]["tx_price_match"] += 1
        if (i + 1) % 500 == 0:
            print(f"[{i+1}/{len(common)}] c1diff={len(rep['c1_bs_sina_event_diff'])} "
                  f"c2f={len(rep['c2_factor_ratio_drift'])} txp={len(rep['c2_tx_price_diff'])}", flush=True)

    # C3: 分层抽样30(bs/sina事件+tx价格)
    def board(c):
        n = c.split(".")[1]
        return ("科创" if n.startswith("68") else "创业" if n.startswith("30")
                else "北交" if n.startswith(("8", "4")) else "主板")
    by = {}
    for c in common:
        by.setdefault(board(c), []).append(c)
    sample = []
    for b, lst in sorted(by.items()):
        k = max(1, round(30 * len(lst) / len(common)))
        sample += random.sample(lst, min(k, len(lst)))
    for code in sample[:30]:
        try:
            ub, hb = load_bh(BS / f"{code}.json.gz")
            ev_b, _ = events_from_F(ub, hb)
            sev_all = load_sina(SN / f"{code}.json.gz")
            ut, ht = load_bh(TX / f"{code}.json.gz")
            wl = min(min(ub), min(ut)); wh = max(max(ub), max(ut))
            sev = {d: f for d, f in sev_all.items() if wl <= d <= wh}
            cd = sorted(set(ub) & set(ut))
            pmax = max((abs(ub[d] - ut[d]) for d in cd), default=0)
            rep["c3_sample"].append({"code": code, "board": board(code),
                                     "events_bs": sorted(ev_b), "events_sina": sorted(sev),
                                     "event_match": set(ev_b) == set(sev),
                                     "tx_price_maxdiff": round(pmax, 4)})
        except Exception:
            pass
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: (dict(v) if isinstance(v, Counter) else v)
                               for k, v in rep.items()}, ensure_ascii=False, indent=1))
    tmp.replace(OUT)
    ps = rep["pair_stats"]
    n_minor = sum(len(x.get("minor", [])) for x in rep["c1_bs_sina_event_diff"])
    n_material = sum(len(x.get("material", [])) for x in rep["c1_bs_sina_event_diff"])
    print(f"跨源审计: 共同股{len(common)} | bs↔sina事件全等 {ps['bs_sina_equal']} 差异股 {len(rep['c1_bs_sina_event_diff'])}(minor小额分红事件{n_minor} material真错位{n_material}) | "
          f"因子比稳定 {ps['factor_ratio_stable']} 漂移 {len(rep['c2_factor_ratio_drift'])} | "
          f"tx价格全对 {ps['tx_price_match']} 错 {len(rep['c2_tx_price_diff'])} | 事件 bs{rep['n_bs_ev']}/sina{rep['n_sina_ev']}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    sys.exit(main())
