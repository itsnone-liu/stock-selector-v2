#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multiperiod_lib.py — 多周期背景增量研究共享库(设计 MULTIPERIOD_INCREMENT_DESIGN_V1, b42fe58).

A1 纯周线价格特征: **从日线复权 close 独立重算**(2026-09-22 二轮口径),
不从 weekly_features.py 混合输出取列; 零量能审计=函数源审计(inspect 本函数体
无 volume/amount 引用)+运行时输入白名单(加载 per_stock 时仅取 date/close 两列)。

冻结定义(只用 close 序列; ISO 周; 完整周=观察日所在周之前已完结的周):
  W1 = 前一完整周最后交易日复权收盘; W2 = 前二; W3 = 前三
  prev_week_cc_pct  = (W1/W2 − 1) × 100
  prev2_week_cc_pct = (W2/W3 − 1) × 100
  week_realized_pct = (obs_close/W1 − 1) × 100   (当周已实现)
  momentum_context_positive = prev>0 and prev2>0 (任一 None → None)
  l_eff_redef = |prev_week_cc_pct|
不足 3 个完整周 → 全部 None(按缺失处理, 折内中位数插补)。
"""
from __future__ import annotations

import gzip
import inspect
import json
from datetime import date
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")

PRICE_FEATS = ["mc_pos", "week_realized_pct", "prev_week_cc_pct",
               "prev2_week_cc_pct", "l_eff_redef"]


def _iso_week_key(d: str) -> tuple[int, int]:
    y, m, dd = map(int, d.split("-"))
    iy, iw, _ = date(y, m, dd).isocalendar()
    return (iy, iw)


def weekly_price_feats(closes: dict[str, float], obs_day: str) -> dict:
    """closes: {date: adj_close} 仅价格; 返回 5 特征(不足→None)。

    零量能审计①: 本函数体不含任何量能类标识符(由
    assert_price_only_source 做源断言, 检查词表见该函数)。
    """
    if obs_day not in closes:
        return {k: None for k in PRICE_FEATS}
    obs_week = _iso_week_key(obs_day)
    weeks: dict[tuple[int, int], tuple[str, float]] = {}   # 周末最后交易日收盘
    for d, c in closes.items():
        wk = _iso_week_key(d)
        cur = weeks.get(wk)
        if cur is None or d > cur[0]:
            weeks[wk] = (d, c)
    done = sorted(((wk, v) for wk, v in weeks.items() if wk < obs_week))
    if len(done) < 3:
        return {k: None for k in PRICE_FEATS}
    W1, W2, W3 = done[-1][1][1], done[-2][1][1], done[-3][1][1]
    prev1 = (W1 / W2 - 1.0) * 100.0 if W2 > 0 else None
    prev2 = (W2 / W3 - 1.0) * 100.0 if W3 > 0 else None
    mc = None if (prev1 is None or prev2 is None) else bool(prev1 > 0 and prev2 > 0)
    return {
        "mc_pos": mc,
        "week_realized_pct": (closes[obs_day] / W1 - 1.0) * 100.0 if W1 > 0 else None,
        "prev_week_cc_pct": prev1,
        "prev2_week_cc_pct": prev2,
        "l_eff_redef": abs(prev1) if prev1 is not None else None,
    }


def assert_price_only_source() -> None:
    """零量能审计②: 源审计——weekly_price_feats 函数体无量能标识符。"""
    src = inspect.getsource(weekly_price_feats)
    for bad in ("volume", "amount", "vol", "turnover", "amt"):
        assert bad not in src, f"A1 特征函数体含疑似量能标识符: {bad}"


_FT_CACHE = None
_FACTOR_SKIP_COUNT = 0    # 因子缺失被跳过的价格行数(应=0, 见断言)


def _factor_by_code():
    """factor_table 一次性加载为 {code:{date:F}}(模块级缓存, 避免逐股全表扫描)。"""
    global _FT_CACHE
    if _FT_CACHE is None:
        import csv
        from collections import defaultdict as _dd
        ft = _dd(dict)
        with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
            for row in csv.DictReader(f):
                ft[row["code"]][row["date"]] = float(row["F"])
        _FT_CACHE = dict(ft)
    return _FT_CACHE


def load_price_series(code: str) -> dict[str, float]:
    """加载单股复权 close 序列。运行时输入白名单: 仅取 per_stock 行的
    date(第0列)与未复权收盘(第4列)×F——不触碰 volume/amount 列。"""
    j = json.load(gzip.open(ROOT / f"data/adjustment_baostock/per_stock/{code}.json.gz", "rt"))
    ft = _factor_by_code().get(code, {})
    out = {}
    skipped = 0
    for row in j["unadj"]:
        d, c = row[0], float(row[4])          # 白名单: 仅 date/close
        F = ft.get(d)
        if F is None:                          # 复权因子缺失→不生成该日价格(不默认1)
            skipped += 1
            continue
        if c > 0 and F > 0:
            out[d] = c * F
    global _FACTOR_SKIP_COUNT
    _FACTOR_SKIP_COUNT += skipped
    return out


def build_a1_features(events: list[dict]) -> dict[tuple[str, str], dict]:
    """对主样本事件批量计算 A1 特征。返回 {(code, obs_day): feats}。"""
    by_code: dict[str, set[str]] = {}
    for e in events:
        by_code.setdefault(e["code"], set()).add(e["obs_day"])
    table: dict[tuple[str, str], dict] = {}
    for code, days in by_code.items():
        try:
            closes = load_price_series(code)
        except FileNotFoundError:
            for d in days:
                table[(code, d)] = {k: None for k in PRICE_FEATS}
            continue
        for d in days:
            table[(code, d)] = weekly_price_feats(closes, d)
    # 覆盖计数断言: 因子缺失跳过数必须为 0(否则 A1 特征可能基于错缺价格)
    assert _FACTOR_SKIP_COUNT == 0, (
        f"复权因子缺失 { _FACTOR_SKIP_COUNT } 行被跳过——A1 特征覆盖受损, 须先对账")
    return table
