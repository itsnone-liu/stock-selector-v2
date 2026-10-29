#!/usr/bin/env python3
"""CF-IS Phase 2 (IS-1) — 周频图集: 组合频次 / 分化检测 / 规则分段 / 案例窗.

输入: data/cfis/weekly_full_202201_202610.csv (is0_weekly_sample.py 产物)
原则: 只做描述性并列轴与轻量标签(供叙述), 不做加权合成指数
      (遵守 capital_weather aggregation=FORBIDDEN); 标签阈值先验固定, 不回搜.

轻量标签定义(先验固定):
  L1 支持:  STRENGTHEN(家族周均 delta>=+0.5%) / STEADY(其余, 含 INSUFFICIENT 单列)
  M 杠杆:   ADD(周净流入>0 且 state 非 DELEVERAGING*) / REDUCE(DELEVERAGING*) / FLAT(其余)
  L4 情绪:  RISK_ON(EUPHORIA/FOMO/RECOVERY) / RISK_OFF(PANIC/APATHY/CAPITULATION)
  L3 承接:  BROAD(breadth>=0.5) / MIXED(0.35-0.5) / WEAK(<0.35)
用法: python3 scripts/cfis/is1_weekly_atlas.py --csv data/cfis/weekly_full_202201_202610.csv
"""
import argparse
import csv
import os
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def l1_label(state, delta):
    if state == "INSUFFICIENT_SUPPORT":
        return "NO_DATA"
    if delta is not None and delta >= 0.005:
        return "STRENGTHEN"
    return "STEADY"


def m_label(state, flow):
    if state and state.startswith("DELEVERAGING"):
        return "REDUCE"
    if flow is not None and flow > 0:
        return "ADD"
    return "FLAT"


def l4_label(state):
    if state in ("EUPHORIA", "FOMO", "RECOVERY"):
        return "RISK_ON"
    if state in ("PANIC", "APATHY", "CAPITULATION"):
        return "RISK_OFF"
    return state or "?"


def fwd_paths(rows, idxs, k=4):
    """给定周下标, 返回其后 k 周累计 EW 收益列表(描述性路径, 非验证)."""
    out = []
    for i in idxs:
        seg = [fnum(r["ax_eq_ret_w"]) or 0.0 for r in rows[i + 1:i + 1 + k]]
        acc = 1.0
        for x in seg:
            acc *= 1.0 + x
        out.append(acc - 1.0)
    return out


def l3_label(breadth):
    if breadth is None:
        return "NO_AX"
    if breadth >= 0.5:
        return "BROAD"
    if breadth >= 0.35:
        return "MIXED"
    return "WEAK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(ROOT, "data", "cfis",
                                                  "weekly_full_202201_202610.csv"))
    args = ap.parse_args()
    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))

    for r in rows:
        r["l1_lab"] = l1_label(r["l1_state"], fnum(r["l1_fam_delta_w"]))
        r["m_lab"] = m_label(r["m_state"], fnum(r["m_fin_flow_w"]))
        r["l4_lab"] = l4_label(r.get("l4_state_mode") or r["l4_state"])
        r["l3_lab"] = l3_label(fnum(r["ax_breadth"]))
        r["combo"] = f"{r['l1_lab']}×{r['m_lab']}×{r['l4_lab']}×{r['l3_lab']}"

    n = len(rows)

    # ---- 1) 组合频次 ----
    combo = Counter(r["combo"] for r in rows)
    print(f"== 组合频次 (top 15 / {len(combo)} 种, n={n} 周) ==")
    for c, k in combo.most_common(15):
        print(f"{k:3d} ({k/n:5.1%})  {c}")

    # ---- 2) 分层方向频次 ----
    for layer in ("l1_lab", "m_lab", "l4_lab", "l3_lab"):
        print(f"-- {layer}: {dict(Counter(r[layer] for r in rows))}")

    # ---- 3) 关键分化形态: 支持偏强 × 杠杆收缩 ----
    diverge = [r for r in rows if r["l1_lab"] == "STRENGTHEN" and r["m_lab"] == "REDUCE"]
    print(f"\n== 分化形态: L1_STRENGTHEN × M_REDUCE = {len(diverge)} 周 ({len(diverge)/n:.1%}) ==")
    if diverge:
        print("   周:", " ".join(r["week"] for r in diverge))
        # 这些周里 L3/L4 承接表现
        cc = Counter((r["l4_lab"], r["l3_lab"]) for r in diverge)
        print("   其中 L4×L3:", dict(cc))
        fwd = [fnum(r["ax_eq_ret_w"]) for r in diverge]
        fwd = [x for x in fwd if x is not None]
        if fwd:
            fwd.sort()
            print(f"   当周市场收益: 中位 {fwd[len(fwd)//2]:+.2%}, "
                  f"min {fwd[0]:+.2%}, max {fwd[-1]:+.2%}, 负周占比 "
                  f"{sum(1 for x in fwd if x<0)/len(fwd):.0%}")
        idxs = [i for i, r in enumerate(rows)
                if r["l1_lab"] == "STRENGTHEN" and r["m_lab"] == "REDUCE"]
        paths = sorted(fwd_paths(rows, idxs))
        if paths:
            print(f"   [路径速览,描述性非验证] 后4周累计EW收益: 中位 "
                  f"{paths[len(paths)//2]:+.1%}, 四分位 {paths[len(paths)//4]:+.1%} ~ "
                  f"{paths[3*len(paths)//4]:+.1%}, min {paths[0]:+.1%}, max {paths[-1]:+.1%}")

    # ---- 4) 同向共振形态: L1_STRENGTHEN × M_ADD × L4_RISK_ON ----
    resonate = [r for r in rows if r["l1_lab"] == "STRENGTHEN" and r["m_lab"] == "ADD"
                and r["l4_lab"] == "RISK_ON"]
    print(f"\n== 共振形态: L1_STRENGTHEN × M_ADD × L4_RISK_ON = "
          f"{len(resonate)} 周 ({len(resonate)/n:.1%}) ==")
    if resonate:
        print("   周:", " ".join(r["week"] for r in resonate))
        idxs = [i for i, r in enumerate(rows)
                if r["l1_lab"] == "STRENGTHEN" and r["m_lab"] == "ADD"
                and r["l4_lab"] == "RISK_ON"]
        paths = sorted(fwd_paths(rows, idxs))
        if paths:
            print(f"   [路径速览,描述性非验证] 后4周累计EW收益: 中位 "
                  f"{paths[len(paths)//2]:+.1%}, 四分位 {paths[len(paths)//4]:+.1%} ~ "
                  f"{paths[3*len(paths)//4]:+.1%}, min {paths[0]:+.1%}, max {paths[-1]:+.1%}")

    # ---- 5) 规则分段(8 周滚动累计收益, 阈值先验) ----
    rets = [fnum(r["ax_eq_ret_w"]) or 0.0 for r in rows]
    roll8 = []
    for i in range(n):
        seg = rets[max(0, i - 7):i + 1]
        acc = 1.0
        for x in seg:
            acc *= (1.0 + x)
        roll8.append(acc - 1.0)
    def phase(x):
        if x >= 0.10:
            return "SURGE8"
        if x <= -0.10:
            return "DECLINE8"
        if x >= 0.03:
            return "UPTREND8"
        if x <= -0.03:
            return "DOWNTREND8"
        return "CHOP8"
    for i, r in enumerate(rows):
        r["phase8"] = phase(roll8[i])
    print("\n== 8 周滚动分段占比 ==")
    print(dict(Counter(r["phase8"] for r in rows)))

    # 各分段下的组合分布摘要(每段 top3 组合)
    print("\n== 各分段 top3 周组合 ==")
    for ph in ("SURGE8", "UPTREND8", "CHOP8", "DOWNTREND8", "DECLINE8"):
        sub = [r for r in rows if r["phase8"] == ph]
        if not sub:
            continue
        top = Counter(r["combo"] for r in sub).most_common(3)
        print(f"  {ph:9s} n={len(sub):3d}: " + " | ".join(f"{c}×{k}" for c, k in top))

    # ---- 6) 案例窗提取(规则固定, 非人工挑) ----
    def window(name, i0, i1):
        print(f"\n== 案例窗 {name} ({rows[i0]['week']}..{rows[i1]['week']}) ==")
        print(f"{'week':9s} {'L1':<6s}{'M':<7s}{'L4':<8s}{'L3':<6s}"
              f"{'eq_ret':>8s}{'breadth':>8s}{'epnew':>7s}{'fin_flow亿':>10s}")
        for i in range(i0, i1 + 1):
            r = rows[i]
            fl = fnum(r["m_fin_flow_w"])
            fl = f"{fl/1e8:+9.0f}" if fl is not None else "        -"
            er = fnum(r["ax_eq_ret_w"])
            er = f"{er:+7.2%}" if er is not None else "      -"
            br = fnum(r["ax_breadth"])
            br = f"{br:8.2f}" if br is not None else "       -"
            print(f"{r['week']:9s} {r['l1_lab']:<6s}{r['m_lab']:<7s}{r['l4_lab']:<8s}"
                  f"{r['l3_lab']:<6s}{er}{br}{int(float(r['ep_new_w'])):7d}{fl}")

    # 自动: 最大 8 周滚动涨幅窗 / 最大跌幅窗 / 最长 STRENGTHEN×REDUCE 连段
    i_max = max(range(n), key=lambda i: roll8[i])
    i_min = min(range(n), key=lambda i: roll8[i])
    window(f"最大8周上行(峰值 {roll8[i_max]:+.1%})", max(0, i_max - 5), min(n - 1, i_max))
    window(f"最大8周下行(谷值 {roll8[i_min]:+.1%})", max(0, i_min - 5), min(n - 1, i_min))

    # 最长连段: STRENGTHEN 且 REDUCE
    best = (0, 0, 0)
    run = 0
    for i, r in enumerate(rows):
        if r["l1_lab"] == "STRENGTHEN" and r["m_lab"] == "REDUCE":
            run += 1
            if run > best[0]:
                best = (run, i - run + 1, i)
        else:
            run = 0
    if best[0]:
        window(f"最长 支持增强×杠杆收缩 连段({best[0]}周)", best[1], best[2])

    # ---- 7) 连续性检查 ----
    gaps = [rows[i]["week"] for i in range(1, n)
            if _week_gap(rows[i - 1]["week"], rows[i]["week"]) != 1]
    print(f"\n== 连续性: {n} 周序列断点 {len(gaps)} 个 {gaps if gaps else ''} ==")


def _week_gap(a, b):
    ya, wa = int(a[:4]), int(a[6:])
    yb, wb = int(b[:4]), int(b[6:])
    return (yb - ya) * 52 + (wb - wa)


if __name__ == "__main__":
    main()
