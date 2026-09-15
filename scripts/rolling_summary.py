#!/usr/bin/env python3
"""汇总滚动验证结果：walk-forward 符号复制率 + 各窗口明细表。

输入：output/research/rolling/*.csv（由 rolling_validation.py 产出）
输出：STDOUT 报告 + SUMMARY.md（含裁决结论：stabile / 窗口依赖 / 失效）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def flip_stats(series: pd.Series) -> tuple[int, int, float]:
    """相邻窗口符号复制：sign(i+1)==sign(i) 的比例（0 值算不复制）。"""
    signs = np.sign(series.to_numpy())
    pairs = [(signs[i], signs[i + 1]) for i in range(len(signs) - 1)]
    rep = sum(1 for a, b in pairs if a != 0 and a == b)
    return rep, len(pairs), (rep / len(pairs) if pairs else float("nan"))


def block(title: str, lines: list[str]) -> str:
    out = [f"## {title}", ""]
    out.extend(lines)
    out.append("")
    return "\n".join(out)


def main(d: str = "output/research/rolling") -> None:
    root = Path(d)
    md: list[str] = ["# 滚动窗口验证汇总（walk-forward 符号复制）", ""]

    # R1 regime：weak - bull 的 fwd5 差，按窗口
    rg = pd.read_csv(root / "regime_by_window.csv")
    piv = rg.pivot_table(index="window", columns="tier", values="fwd5_mean")
    if {"weak", "bull"}.issubset(piv.columns):
        diff = (piv["weak"] - piv["bull"]).dropna()
        rep, tot, rate = flip_stats(diff)
        lines = ["| 窗口 | bull | mid | weak | weak-bull |", "|---|---|---|---|---|"]
        for w, row in piv.iterrows():
            lines.append(f"| {w} | {row.get('bull', float('nan')):+.2f} | "
                         f"{row.get('mid', float('nan')):+.2f} | {row.get('weak', float('nan')):+.2f} | "
                         f"{(row.get('weak', np.nan) - row.get('bull', np.nan)):+.2f} |")
        n_weak_best = int((piv["weak"] > piv[["bull", "mid"]].max(axis=1)).sum())
        lines += ["", f"- weak>bull 的窗口：{(diff > 0).sum()}/{len(diff)}",
                  f"- weak 同时优于 bull 和 mid 的窗口：{n_weak_best}/{len(piv)}",
                  f"- 相邻窗口符号复制率：{rep}/{tot} = {rate:.0%}",
                  f"- **裁决**：{'窗口依赖（不具稳定性）' if rate < 0.6 or (diff > 0).sum() < len(diff) * 0.7 else '方向稳定'}"]
        md.append(block("R1 regime 档位前瞻收益（fwd5 均值，%）", lines))

    # R2 特征三分位：顶桶-底桶 fwd5 差
    ft = pd.read_csv(root / "feature_terciles_by_window.csv")
    lines = ["| 特征 | 顶-底差>0窗口 | 复制率 | 均值差(全窗) | 裁决 |", "|---|---|---|---|---|"]
    for feat, g in ft.groupby("feature"):
        pivf = g.pivot_table(index="window", columns="tercile", values="fwd5_mean")
        if {0, 2}.issubset(pivf.columns):
            dlt = (pivf[2] - pivf[0]).dropna()
            rep, tot, rate = flip_stats(dlt)
            verdict = "稳定有效" if (dlt > 0).sum() >= len(dlt) * 0.7 and rate >= 0.6 else \
                      ("反向稳定" if (dlt < 0).sum() >= len(dlt) * 0.7 else "窗口依赖/失效")
            lines.append(f"| {feat} | {(dlt > 0).sum()}/{len(dlt)} | {rep}/{tot}={rate:.0%} | "
                         f"{dlt.mean():+.2f} | {verdict} |")
    md.append(block("R2 base_scores 特征（估计期定边，样本外定桶）", lines))

    # R3 标签组合 vs baseline
    lb = pd.read_csv(root / "labels_by_window.csv")
    base = lb[lb["combo"] == "baseline"].set_index("window")["fwd5_mean"]
    combos = sorted(c for c in lb["combo"].unique() if c != "baseline")
    lines = ["| 组合 | 超额>0窗口 | 复制率 | 全窗均值超额 | 裁决 |", "|---|---|---|---|---|"]
    for combo in combos:
        g = lb[lb["combo"] == combo].set_index("window")["fwd5_mean"]
        ex = (g - base.reindex(g.index)).dropna()
        if len(ex) < 3:
            continue
        rep, tot, rate = flip_stats(ex)
        verdict = "稳定超额" if (ex > 0).sum() >= len(ex) * 0.7 and rate >= 0.6 else "窗口依赖"
        lines.append(f"| {combo} | {(ex > 0).sum()}/{len(ex)} | {rep}/{tot}={rate:.0%} | "
                     f"{ex.mean():+.2f} | {verdict} |")
    md.append(block("R3 标签组合相对无标签基线（fwd5 超额，%）", lines))

    # R4 退出规则
    ex_df = pd.read_csv(root / "exits_by_window.csv")
    pivx = ex_df.pivot_table(index="window", columns="rule", values="ret_mean")
    lines = ["| 对比 | 差>0窗口 | 复制率 | 裁决 |", "|---|---|---|---|"]
    for a, b in (("E3_trail8", "E2_fixed5"), ("E1_close", "E1_intraday"),
                 ("E5_combo", "E3_trail8")):
        if {a, b}.issubset(pivx.columns):
            dlt = (pivx[a] - pivx[b]).dropna()
            rep, tot, rate = flip_stats(dlt)
            verdict = "稳定" if (dlt > 0).sum() >= len(dlt) * 0.7 and rate >= 0.6 else "窗口依赖"
            lines.append(f"| {a} - {b} | {(dlt > 0).sum()}/{len(dlt)} | {rep}/{tot}={rate:.0%} | {verdict} |")
    wp = ex_df.pivot_table(index="window", columns="rule", values="win")
    if "E2_fixed5" in wp.columns:
        lines.append(f"\n- E2_fixed5 胜率区间：{wp['E2_fixed5'].min():.1%} ~ {wp['E2_fixed5'].max():.1%}")
    md.append(block("R4 退出规则（fwd收益均值差，%）", lines))

    report = "\n".join(md)
    (root / "SUMMARY.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main(*sys.argv[1:])
