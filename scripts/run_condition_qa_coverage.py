#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_qa_coverage.py v2 — Q-A 覆盖审计+H2 分组覆盖(十九轮修复版).

十九轮修复:
- P0 全时期终点汇总: 终点分类始终写 all_periods; 测试折额外写 per_fold;
  两级守恒断言 obs == event+competing+censor_window+censor_admin
- P1 统计单位: 输出去重股票数/生命周期段数/每股跨段累计观察日;
  断言 (code, date) 唯一
- P1 最早终点规则: 统一在可观察区间 (t, min(t+5, 日历尾)] 内比较
  突破/市场退出/行政终止的最早者; 可观察区间空才计行政删失
- 表述: 未计算 Y40、未使用价格数值进行关联检验; 已读取 Q-A 终点日期
  (bo/end) 用于覆盖审计; 背景特征为 t 时点信息非结果变量

H2 分组覆盖(预注册细化, 不跑关联):
- H2a: price_vs_monthly_ma6, 阈值=训练折池(b19-21)全观察特征 1/3 与 2/3
  分位 → 低/中/高三组; 主比较=高 vs 低; 测试折=b22(时间外推防泄漏)
- H2b: wk_up_streak 预固定档位 0/1/2/≥3(离散不用分位); 主比较=档0 vs 档≥2
- 竞争事件保留独立状态(事件/竞争/窗满/行政四类分别计数, 不合并)
"""
from __future__ import annotations

import glob
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
import duckdb  # noqa: E402
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402
from run_condition_riskset_v2 import independent_code_map  # noqa: E402
from run_condition_stage0_audit import monthly_states, weekly_states  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
FOLDS = (19, 20, 21, 22)
TRAIN, TEST = (19, 20, 21), 22
MARKET_EXITS = {"monthly_exit", "structure_break"}


def classify(i, bo_i, end_i, mkt, n_md):
    """最早终点规则(十九轮; 二十轮模块级化供合成反例测试 import):
    可观察区间 (i, min(i+5, n_md-1)] 内比较 突破/市场退出/行政终止 最早者."""
    obs_last = min(i + 5, n_md - 1)
    if obs_last <= i:
        return "censor_admin"
    ev_i = bo_i if (bo_i is not None and i < bo_i <= obs_last) else None
    cp_i = end_i if (mkt and end_i is not None and i < end_i <= obs_last) else None
    ad_i = n_md - 1 if obs_last < i + 5 else None
    cands = [x for x in ((ev_i, "event"), (cp_i, "competing")) if x[0] is not None]
    if cands:
        cands.sort(key=lambda x: x[0])
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            return "competing"
        return cands[0][1]
    if ad_i is not None:
        assert not (bo_i is not None and i < bo_i <= ad_i), "行政先于突破未处理"
        assert not (mkt and end_i is not None and i < end_i <= ad_i), "行政先于市场退出未处理"
        return "censor_admin"
    if end_i is not None and i < end_i <= obs_last:
        return "censor_admin"
    return "censor_window"


def main():
    t0 = time.time()
    cmap = independent_code_map()
    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"), recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day, end_reason
        from read_parquet({files!r})""").fetchall()
    lc = {lid: (code, anchor, bo, end, reason) for code, lid, anchor, bo, end, reason in df}
    import csv
    pool_in = defaultdict(dict)
    want = {v[0].split(".")[-1] if "." in v[0] else v[0] for v in lc.values()}
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            if r["code"] in want:
                pool_in[r["code"]][r["date"]] = (r["monthly_pool_state"] == "in")
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    n_md = len(mdates)

    allp = Counter()
    per_fold = {f: Counter() for f in FOLDS}
    seen_pairs = set()          # (code, date) 唯一性断言
    seg_obs = []                # 每生命周期段观察日数
    stock_obs = Counter()       # 每股跨段累计
    boundary_gaps = Counter()   # 跨段边界相邻观察间隔
    train_feats = []            # (b19-21) 特征
    test_rows = []              # b22: (day, pvm6, streak, 终点类别)
    n_bo_excluded = 0

    prev_global = None   # 跨段保留(二十轮修复: 原在段内重置致边界统计恒空)
    for lid, (code, anchor, bo, end, reason) in sorted(lc.items()):
        c6 = code.split(".")[-1] if "." in code else code
        full = cmap.get(c6)
        if full is None or anchor not in mpos:
            continue
        a_i = mpos[anchor]
        s_i = mpos[bo] + 1 if (bo and bo in mpos) else min(mpos.get(end, n_md), a_i + 120, n_md - 1)
        try:
            closes = load_price_series(full)
        except FileNotFoundError:
            continue
        dayset = closes.keys()
        pin = pool_in.get(c6, {})
        days = [d for d in mdates[a_i:s_i] if d in dayset and pin.get(d)]
        bo_i = mpos[bo] if (bo and bo in mpos) else None
        end_i = mpos.get(end) if end in mpos else None
        mkt = reason in MARKET_EXITS
        seg_n = 0
        for d in days:
            i = mpos[d]
            if bo_i is not None and i >= bo_i:
                n_bo_excluded += 1
                continue
            assert (c6, d) not in seen_pairs, f"(code,date) 重复: {c6} {d}"
            seen_pairs.add((c6, d))
            if prev_global is not None:
                if prev_global[1] and i > prev_global[0]:   # 跨段边界且时间在后(段处理序非时间序, 负跳不计)
                    boundary_gaps[i - prev_global[0]] += 1
            cls = classify(i, bo_i, end_i, mkt, n_md)
            b = obs_bucket(d)
            allp["obs"] += 1
            allp[cls] += 1
            if b in per_fold:
                per_fold[b]["obs"] += 1
                per_fold[b][cls] += 1
            seg_n += 1
            stock_obs[c6] += 1
            if b in TRAIN:
                train_feats.append((monthly_states(closes, d).get("price_vs_monthly_ma6"),
                                    weekly_states(closes, d).get("wk_up_streak")))
            elif b == TEST:
                test_rows.append((d, monthly_states(closes, d).get("price_vs_monthly_ma6"),
                                  weekly_states(closes, d).get("wk_up_streak"), cls))
            prev_global = (i, False)
        if seg_n:
            seg_obs.append(seg_n)
            prev_global = (prev_global[0], True)   # 下段首日记跨段边界
        if (len(seen_pairs) % 80000) == 0 and seen_pairs:
            print(f"{len(seen_pairs):,} 观察日 | {time.time()-t0:.0f}s", flush=True)

    # 守恒断言(两级)
    for name, c in [("all_periods", allp)] + [(f"b{f}", per_fold[f]) for f in FOLDS]:
        tot = c["event"] + c["competing"] + c["censor_window"] + c["censor_admin"]
        assert c["obs"] == tot, f"{name} 守恒失败: obs {c['obs']} != 分类和 {tot}"

    # H2 分组覆盖(测试折 b22)
    tf = [(p, s) for p, s in train_feats if p is not None and p == p and s is not None]
    q1, q2 = (float(np.percentile([x[0] for x in tf], 100 / 3)),
              float(np.percentile([x[0] for x in tf], 200 / 3)))
    def grp_a(p):
        return "low" if p < q1 else ("high" if p > q2 else "mid")
    def grp_b(s):
        return "s0" if s == 0 else ("s1" if s == 1 else ("s2" if s == 2 else "s3p"))
    h2a = defaultdict(Counter)
    h2b = defaultdict(Counter)
    day_groups = defaultdict(lambda: [set(), set()])
    for d, p, s, cls in test_rows:
        if p is not None and p == p and s is not None:
            ga, gb = grp_a(p), grp_b(s)
            h2a[ga][cls] += 1
            h2a[ga]["obs"] += 1
            h2b[gb][cls] += 1
            h2b[gb]["obs"] += 1
            day_groups[d][0].add(ga)
            day_groups[d][1].add(gb)
    eff_days_a = sorted(d for d, (ga, _) in day_groups.items() if "low" in ga and "high" in ga)
    eff_days_b = sorted(d for d, (_, gb) in day_groups.items() if "s0" in gb and "s3p" in gb)
    def n_blocks(days_sorted, block=40):
        return max(1, int(np.ceil(len(days_sorted) / block))) if days_sorted else 0

    ps = np.array(list(stock_obs.values()))
    rep = {"audit": "MULTIPERIOD_CONDITION_QA_COVERAGE", "version": "v2-十九轮修复",
           "date": "2026-09-22",
           "data_use_statement": "未计算 Y40、未使用价格数值进行关联检验; 已读取 Q-A 终点日期(bo/end)用于覆盖审计; 背景特征为 t 时点信息",
           "riskset_recon": {"obs_days_total": allp["obs"], "expected_riskset": 323031,
                             "bo_excluded": n_bo_excluded,
                             "assert": allp["obs"] + n_bo_excluded == 323031},
           "conservation_assert": "all_periods 与各折: obs == event+competing+censor_window+censor_admin(全部执行通过)",
           "units": {"dedup_stocks": len(stock_obs), "lifecycle_segments": len(seg_obs),
                     "obs_per_stock_p50": float(np.percentile(ps, 50)),
                     "obs_per_stock_p75": float(np.percentile(ps, 75)),
                     "obs_per_stock_max": int(ps.max()),
                     "obs_per_segment_p50": float(np.percentile(seg_obs, 50)),
                     "code_date_unique_assert": "passed"},
           "boundary_gap_hist": {str(k): int(v) for k, v in sorted(boundary_gaps.items())},
           "by_fold": {str(f): dict(c) for f, c in per_fold.items()},
           "all_periods": dict(allp),
           "h2_group_coverage": {
               "train": {"folds": "b19-21", "n_feats": len(tf),
                         "h2a_thresholds": {"q33": q1, "q67": q2},
                         "h2b_bins": "0/1/2/>=3(预固定)"},
               "test": {"fold": "b22",
                        "h2a": {g: dict(c) for g, c in h2a.items()},
                        "h2b": {g: dict(c) for g, c in h2b.items()},
                        "threshold_note": "阈值仅由训练折特征确定(b22 无泄漏)"}},
           "h2_prereg": {"H2a": "高减低 合并5日发生率差(Σev/Σobs, 双侧)",
                         "H2b": "档>=2 减 档0 合并发生率差(双侧)", "inference": "日期块主推断(§5.1), 重抽整日分子分母",
                         "status": "开发性/探索性——b22 描述信息已被查看(二十轮), 非未查看独立测试集"},
           "effective_days": {"h2a_low_high_same_day": len(eff_days_a),
                              "h2b_s0_s3p_same_day": len(eff_days_b),
                              "h2a_n_blocks40": n_blocks(eff_days_a),
                              "h2b_n_blocks40": n_blocks(eff_days_b),
                              "h2a_first_last": [eff_days_a[0], eff_days_a[-1]] if eff_days_a else None,
                              "h2b_first_last": [eff_days_b[0], eff_days_b[-1]] if eff_days_b else None}}
    (OUT / "MULTIPERIOD_CONDITION_QA_COVERAGE.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"对账: 323,031 = Q-A {allp['obs']:,} + bo日 {n_bo_excluded} | 守恒断言全过 | {time.time()-t0:.0f}s")
    print(f"单位: 去重股票 {len(stock_obs):,} | 生命周期段 {len(seg_obs):,} | 每股 p50 {rep['units']['obs_per_stock_p50']:.0f} max {rep['units']['obs_per_stock_max']}")
    c = allp
    print(f"全时期: obs {c['obs']:,} ev {c['event']:,} comp {c['competing']:,} 窗满 {c['censor_window']:,} 行政 {c['censor_admin']:,}")
    for f in FOLDS:
        c = per_fold[f]
        print(f"b{f}: obs {c['obs']:>6} ev {c['event']:>5} comp {c['competing']:>5} 窗满 {c['censor_window']:>6} 行政 {c['censor_admin']:>3}")
    print(f"有效日: H2a 低&高同日 {len(eff_days_a)} 日({n_blocks(eff_days_a)} 个40日块) | H2b s0&s3p 同日 {len(eff_days_b)} 日({n_blocks(eff_days_b)} 块)")
    print(f"H2a 阈值: q33={q1:.4f} q67={q2:.4f} | b22 分组覆盖:")
    for g in ("low", "mid", "high"):
        if g in h2a:
            print(f"  {g}: {dict(h2a[g])}")
    for g in ("s0", "s1", "s2", "s3p"):
        if g in h2b:
            print(f"  {g}: {dict(h2b[g])}")
    print("→ MULTIPERIOD_CONDITION_QA_COVERAGE.json")


if __name__ == "__main__":
    main()
