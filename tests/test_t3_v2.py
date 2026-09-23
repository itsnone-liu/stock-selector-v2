#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_t3_v2.py — T3 V2 核心数学单元测试（合成数据，确定性）。

覆盖：四态删失分类、收益公式镜像、MDD/恢复/回调、周线未满周排除、
chip 严格全窗缺失传播、ref60 定义。
"""
import sys
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from stock_selector.research import t3_v2 as tv


def make_sd(dates, closes, F=None, vols=None, amts=None, turns=None):
    F = F or {d: 1.0 for d in dates}
    vols = vols or {d: 100.0 for d in dates}
    amts = amts or {d: 100.0 * c for d, c in zip(dates, closes)}
    turns = turns or {d: 1.0 for d in dates}
    valid = [d for d in dates if d in F]
    vpos = {d for d in dates if (vols.get(d) or 0) > 0 and (amts.get(d) or 0) > 0}
    return tv.StockData(
        code_pfx="sz.000001", dates=dates, o=None,
        h={d: c * 1.02 for d, c in zip(dates, closes)},
        l={d: c * 0.98 for d, c in zip(dates, closes)},
        c={d: c for d, c in zip(dates, closes)},
        vol=vols, amt=amts, turn=turns,
        hfq_h={}, hfq_c={}, F=F, valid=valid, vpos=vpos)


def mdates_fixture(n, start="2026-01-05"):
    import pandas as pd
    idx = pd.bdate_range(start, periods=n)
    return [ts.strftime("%Y-%m-%d") for ts in idx]


def test_censor_four_states():
    md = mdates_fixture(60)
    # 全窗有效 → none
    sd = make_sd(md[:50], [10.0] * 50)
    mpos = {d: i for i, d in enumerate(md)}
    r, ih, nv, fl = tv.classify_censor(sd, md, mpos, md[5], 10, 55)
    assert r == "none" and nv == 11
    assert not fl["is_data_gap"] and fl["data_gap_reason"] is None
    # T0+H 越过 dataset_end → sample_end（构造 mdates 尾部越过 2026-09-18）
    md2 = ["2026-09-%02d" % (i + 1) for i in range(18)]  # 至 09-18
    sd2 = make_sd(md2, [10.0] * 18)
    mp2 = {d: i for i, d in enumerate(md2)}
    r2, *_ = tv.classify_censor(sd2, md2, mp2, "2026-09-15", 5, 17)
    assert r2 == "sample_end"
    # 个股库行历史先于窗口末终止 → security_history_end
    sd3 = make_sd(md[:20], [10.0] * 20)          # 最后库行 = md[19]
    r3, _, _, fl3 = tv.classify_censor(sd3, md, mpos, md[5], 30, 55)
    assert r3 == "security_history_end"
    assert fl3["is_security_history_end"]
    # 中途缺行（行不在）但历史延伸 → data_gap / row_missing
    dates = [d for i, d in enumerate(md[:50]) if i != 10]
    sd4 = make_sd(dates, [10.0] * len(dates))
    r4, _, _, fl4 = tv.classify_censor(sd4, md, mpos, md[5], 10, 55)
    assert r4 == "data_gap" and fl4["is_data_gap"]
    assert fl4["data_gap_reason"] == "row_missing"
    # 行在而因子缺（裁定：adj_factor_missing → data_gap，不记 sec_end）
    F5 = {d: 1.0 for d in md[:50] if d != md[8]}
    sd5 = make_sd(md[:50], [10.0] * 50, F=F5)
    r5, _, _, fl5 = tv.classify_censor(sd5, md, mpos, md[5], 10, 55)
    assert r5 == "data_gap" and fl5["is_data_gap"]
    assert fl5["data_gap_reason"] == "adj_factor_missing"
    assert not fl5["is_security_history_end"]


def test_y_formula_mirror():
    md = mdates_fixture(50)
    closes = [10.0 * (1.01 ** i) for i in range(50)]
    F = {d: 1.5 for d in md}
    sd = make_sd(md, closes, F=F)
    mpos = {d: i for i, d in enumerate(md)}
    mclose = np.array([100.0 + i for i in range(50)])
    lab = tv.compute_labels(sd, md[5], md, mclose, mpos, 49)
    i0, ih = 5, 45
    p0, ph = closes[i0] * 1.5, closes[ih] * 1.5
    want_raw = np.log(ph / p0)
    want_ex = np.log(ph / p0) - np.log(mclose[ih] / mclose[i0])
    assert abs(lab["y40_raw_log"] - want_raw) < 1e-14
    assert abs(lab["y40_mkt_excess_log"] - want_ex) < 1e-14


def test_mdd_and_pullback():
    md = mdates_fixture(46)                      # T0 + 40 + 余量
    closes = [10.0] * 6                          # T0=10
    closes += [11.0] * 2 + [9.0] + [10.5]        # 冲高回落 11→9 (dd=2/11)
    closes += [10.8] * 36                        # 恢复段
    sd = make_sd(md[:46], closes)
    mpos = {d: i for i, d in enumerate(md)}
    lab = tv.compute_labels(sd, md[0], md, np.ones(60), mpos, 59)
    # close-MDD: peak=11(offs 6/7), trough=9(offs 8) → 1-9/11
    assert abs(lab["mdd_close_h40"] - (1 - 9.0 / 11.0)) < 1e-12
    assert lab["dd_peak_day_h40"] == 6 and lab["dd_trough_day_h40"] == 8
    assert lab["recover_days_h40"] is None or lab["recover_days_h40"] >= 1
    # 回调深度 >=5% → pullback_depth = mdd
    assert abs(lab["pullback_depth_h40"] - (1 - 9.0 / 11.0)) < 1e-12


def test_weekly_incomplete_week_excluded():
    # 2026-01-05 是周一；T0=周三 01-07 → 当周不合成
    md = mdates_fixture(20)
    closes = [10.0 + i for i in range(20)]
    sd = make_sd(md, closes)
    wk = tv.weekly_close_series(sd, "2026-01-07")
    # 最后已完成周 = 01-05 那一周之前的周——但序列从 01-05 开始，
    # 即当周本身被排除 → 无已完成周
    assert wk == []
    wk2 = tv.weekly_close_series(sd, "2026-01-12")   # 下周一
    # 当周(01-12周)排除；01-05 周已完成: 周收盘 = 01-09 的 close
    assert len(wk2) == 1
    assert wk2[0][1] == closes[4]                    # 01-09 = index 4


def test_chip_field_level_window():
    # 字段级口径（2026-09 裁定）：窗口 = T0 + 前置量有效日（行+vpos），
    # 量缺失日不在骨架内（近 w 个量有效观测的成交成本）。
    md = mdates_fixture(30)
    closes = [10.0] * 30
    vols = {d: 100.0 for d in md}
    vols[md[28]] = 0.0                               # 量缺失日
    amts = {d: 1000.0 for d in md}
    sd = make_sd(md, closes, vols=vols, amts=amts)
    out = tv.compute_features_chip(sd, md[29])
    # 5 日窗 = T0(29) + 27,26,25,24 —— 28 被骨架跳过，仍可算
    assert out["chip_price_to_vwap_5d"] is not None
    # vwap = Σamt/Σvol over {24..27,29} = 1000/100
    assert abs(out["chip_vwap_day"] - 10.0) < 1e-12
    # 短历史：上市不足 w 个量有效日 → 缺失
    md_short = md[:3]
    sd2 = make_sd(md_short, [10.0] * 3)
    out2 = tv.compute_features_chip(sd2, md_short[2])
    assert out2["chip_price_to_vwap_5d"] is None
    assert out2["chip_vwap5_obs_n"] == 3


def test_ref60_definition():
    md = mdates_fixture(80)
    closes = [10.0] * 80
    closes[50] = 20.0                                # 前史高点在 50
    closes[79] = 15.0                                # T0
    sd = make_sd(md, closes)
    a1 = tv.compute_features_a1(sd, md[79])
    obs = [d for d in md if d < md[79]][-60:]        # 前 60 有效观测
    assert a1["a1_ref60"] == max(closes[md.index(d)] for d in obs)
    assert a1["a1_ref60"] == 20.0
    assert a1["a1_breakout_margin"] == 15.0 / 20.0 - 1.0  # 未过 60 日高 → 负


if __name__ == "__main__":
    for fn in (test_censor_four_states, test_y_formula_mirror,
               test_mdd_and_pullback, test_weekly_incomplete_week_excluded,
               test_chip_field_level_window, test_ref60_definition):
        fn()
        print(f"PASS {fn.__name__}")
    print("ALL PASS")
