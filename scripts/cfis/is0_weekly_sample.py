#!/usr/bin/env python3
"""CF-IS Phase 1 (IS-0) — 周频匹配样表构建器.

把已存在的四层日频观察聚合到一个共同周度表上, 验证日期/层级可联表性:
  L1 政策稳定行为代理  cf/derived/atoms/l1_history.jsonl (2012-01→)
  M  杠杆场            cf/derived/atoms/m_history.jsonl  (2018-01→)
  L4 情绪与跟随资本    cf/derived/atoms/l4_history.jsonl (2021-08→)
  L3 市场承接背景      cd/sector_axes/l1_market_axes.json.gz (2022-01→)
  L3 个股承接事件      cd/sector_axes/l4_episodes.json.gz (episode 生命期)

周定义: ISO 周, 以周内最后一个有观测的交易日为锚(week_end). 结果观察(5/20日)
只在此样表中留占位列, 由 Phase 2 决定是否填充. 输出 data/cfis/weekly_sample_*.csv

用法: python3 scripts/cfis/is0_weekly_sample.py --start 2024-01-01 --end 2024-12-31
"""
import argparse
import csv
import gzip
import json
import os
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ATOMS = os.path.join(ROOT, "data", "cf", "derived", "atoms")


def iter_jsonl(path, op=None):
    op = op or open
    with op(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_atom_history(name, start, end):
    """返回 {date: row}; 同日重复以后到者为准并计数."""
    rows, dup = {}, 0
    p = os.path.join(ATOMS, name)
    for r in iter_jsonl(p):
        d = r.get("date", "")
        if start <= d <= end:
            if d in rows:
                dup += 1
            rows[d] = r
    return rows, dup


def load_market_axes(start, end):
    p = os.path.join(ROOT, "data", "cd", "sector_axes", "l1_market_axes.json.gz")
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    rows, dup = {}, 0
    for r in d.get("rows", []):
        dt = r.get("date", "")
        if start <= dt.replace("-", "") <= end:
            k = dt.replace("-", "")
            if k in rows:
                dup += 1
            rows[k] = r
    return rows, dup


def load_episodes(start, end):
    """episode 生命期与周相交计数. 流式, 只要日期字段."""
    p = os.path.join(ROOT, "data", "cd", "sector_axes", "backup_20261028", "l4_episodes.json.gz")
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    eps = d.get("episodes", [])
    return eps


def iso_week(datestr):
    from datetime import date
    y, m, dd = int(datestr[:4]), int(datestr[4:6]), int(datestr[6:8])
    iso = date(y, m, dd).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240101")
    ap.add_argument("--end", default="20241231")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    start, end = args.start, args.end

    l1, l1_dup = load_atom_history("l1_history.jsonl", start, end)
    m, m_dup = load_atom_history("m_history.jsonl", start, end)
    l4, l4_dup = load_atom_history("l4_history.jsonl", start, end)
    ax, ax_dup = load_market_axes(start, end)
    eps = load_episodes(start, end)

    # 周桶: 只按实际观测到的日期分桶(不做日历填充)
    weeks = defaultdict(dict)  # week -> {date: source_flag}
    for src, rows in (("l1", l1), ("m", m), ("l4", l4), ("ax", ax)):
        for d in rows:
            weeks[iso_week(d)][d] = True

    # episode 周相交
    ep_new = Counter()
    ep_active = Counter()
    for e in eps:
        s = (e.get("start") or "").replace("-", "")
        t = (e.get("end") or "").replace("-", "")
        if not s:
            continue
        if start <= s <= end:
            ep_new[iso_week(s)] += 1
        if t:  # 已终结: 与生命期相交的周
            cur = s
            wk = iso_week(s)
            # 用周桶里已有的周界近似: 只统计样表周内相交
            for w in weeks:
                if w >= iso_week(s) and (not t or w <= iso_week(t)):
                    ep_active[w] += 1
        elif s <= end:  # 未终结且起点在窗口内
            for w in weeks:
                if w >= iso_week(s):
                    ep_active[w] += 1

    out_rows = []
    for w in sorted(weeks):
        dates = sorted(weeks[w])
        we = dates[-1]
        week_dates = [d for d in dates]

        def agg(src_rows, field, how="last"):
            vals = [src_rows[d].get(field) for d in week_dates
                    if d in src_rows and isinstance(src_rows[d].get(field), (int, float))]
            if not vals:
                return ""
            if how == "last":
                return round(vals[-1], 4)
            if how == "mean":
                return round(sum(vals) / len(vals), 4)
            if how == "sum":
                return round(sum(vals), 2)

        def state_last(src_rows):
            for d in reversed(week_dates):
                if d in src_rows:
                    return src_rows[d].get("state", "")
            return ""

        def states_count(src_rows):
            c = Counter(src_rows[d].get("state") for d in week_dates if d in src_rows)
            return dict(c)

        ax_regimes = Counter(ax[d].get("regime") for d in week_dates if d in ax)
        out_rows.append({
            "week": w,
            "week_end": we,
            "days_obs": len(week_dates),
            # L1 支持代理
            "l1_state": state_last(l1),
            "l1_fam_delta_w": agg(l1, "family_median_delta", "mean"),
            "l1_days": sum(1 for d in week_dates if d in l1),
            # M 杠杆
            "m_state": state_last(m),
            "m_fin_flow_w": agg(m, "financing_flow", "sum"),
            "m_pressure": agg(m, "financing_balance_pressure", "last"),
            "m_days": sum(1 for d in week_dates if d in m),
            # L4 情绪
            "l4_state": state_last(l4),
            "l4_adv_mean": agg(l4, "advancers", "mean"),
            "l4_limitup_w": agg(l4, "limit_up", "sum"),
            "l4_amt_ratio": agg(l4, "amount_ratio20", "mean"),
            "l4_days": sum(1 for d in week_dates if d in l4),
            # L3 市场承接背景
            "ax_breadth": agg(ax, "breadth", "mean"),
            "ax_part": agg(ax, "part", "mean"),
            "ax_conc50": agg(ax, "conc50", "mean"),
            "ax_regime": (ax_regimes.most_common(1)[0][0] if ax_regimes else ""),
            "ax_days": sum(1 for d in week_dates if d in ax),
            # L3 个股承接事件
            "ep_new_w": ep_new.get(w, 0),
            "ep_active_w": ep_active.get(w, 0),
        })

    out = args.out or os.path.join(
        ROOT, "data", "cfis", f"weekly_sample_{start[:6]}_{end[:6]}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        wr.writeheader()
        wr.writerows(out_rows)
    print(f"wrote {len(out_rows)} weekly rows -> {out}")
    print(f"dup dates: l1={l1_dup} m={m_dup} l4={l4_dup} ax={ax_dup}; episodes={len(eps)}")


if __name__ == "__main__":
    main()
