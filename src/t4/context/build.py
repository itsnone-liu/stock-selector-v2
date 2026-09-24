"""T4.1 Context 层：市场/板块日表、行业映射、事件背景（as-of T0）。

不可变约束（开工令 §一）：
- 事件集合与冻结字段完全继承 T3 V6（28f7aed），不重生成、不筛除；
  外部数据缺失留空并报告覆盖率，不填 neutral。
- 行业归属为 baostock 证监会分类快照（2026-09-21），非历史时点数据：
  is_point_in_time=false，正式结论使用须按开工令 §四 披露该限制。
- 全部 context 特征只用截至 T0 的数据（T0 收盘特征供收盘后决策）。
"""
from __future__ import annotations

import gzip
import json
import struct
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")


# ---------------------------------------------------------------- 行业映射
def build_sector_map(snapshot_path: Path) -> pd.DataFrame:
    """baostock 证监会行业快照 → 带生效日期的映射表（非时点，如实标注）。

    快照不含历史变更；effective_from=快照更新日，effective_to=null，
    is_point_in_time=false —— 空行业保留空值。
    """
    rows = json.loads(Path(snapshot_path).read_text())
    rec = []
    for update_date, code, name, industry, classification in rows:
        gate = industry[:1] if industry else None
        klass = industry[:3] if len(industry or "") >= 3 else None
        rec.append({
            "code": code, "code_name": name,
            "industry_full": industry or None,
            "industry_gate": gate,          # 证监会门类（19 类）
            "industry_class": klass,        # 门类+大类（如 J66）
            "classification": classification,
            "effective_from": update_date,  # 快照更新日（非上市日起）
            "effective_to": None,
            "is_point_in_time": False,      # 快照，非历史时点
            "source": "baostock_csrc_snapshot",
        })
    return pd.DataFrame(rec)


# ---------------------------------------------------------------- 个股日读
def iter_stock_daily(per_stock_dir: Path):
    """逐股 yield (code, dates, adj_close, pctchg, amount, turn)。

    adj_close = unadj_close × 复权因子（factor_table），用于创新高等
    跨除权判定；pctChg 沿用 baostock 字段（复权口径涨跌幅）。
    """
    ft = pd.read_csv(ROOT / "output/research/adjustment_v1/factor_table.csv.gz")
    fmap = {}                      # code -> {date: F}
    for row in ft.itertuples(index=False):
        fmap.setdefault(row.code, {})[str(row.date)] = float(row.F)
    for p in sorted(Path(per_stock_dir).glob("*.json.gz")):
        code = p.name.replace(".json.gz", "")
        with gzip.open(p, "rt") as f:
            j = json.load(f)
        un = j["unadj"]
        dates, adj, pch, amt, turn = [], [], [], [], []
        m = fmap.get(code, {})
        prev = None
        for r in un:
            d = r[0]
            try:
                c = float(r[4])
            except (TypeError, ValueError):
                continue
            f_ = m.get(d)
            adj.append(c * f_ if f_ is not None else None)
            dates.append(d)
            try:
                pch.append(float(r[8]) if r[8] else None)
            except (TypeError, ValueError):
                pch.append(None)
            try:
                amt.append(float(r[6]) if r[6] else None)
            except (TypeError, ValueError):
                amt.append(None)
            try:
                turn.append(float(r[7]) if r[7] else None)
            except (TypeError, ValueError):
                turn.append(None)
        yield code, dates, adj, pch, amt, turn


def build_daily_frames(per_stock_dir: Path, sector_map: pd.DataFrame,
                       min_members: int = 20):
    """聚合市场/板块日表（全本地冻结数据，可复现）。"""
    all_dates = sorted({d for _, dates, *_ in iter_stock_daily_cached()
                        for d in dates})
    dpos = {d: i for i, d in enumerate(all_dates)}
    n = len(all_dates)
    # 累加器：市场层
    mkt_amt = np.zeros(n)
    mkt_up = np.zeros(n)
    mkt_down = np.zeros(n)
    mkt_flat = np.zeros(n)
    mkt_pch_lists = [[] for _ in range(n)]
    mkt_nh20 = np.zeros(n)
    # 板块层（门类）
    gates = sorted(sector_map["industry_gate"].dropna().unique())
    gate_of = {c: g for c, g in zip(sector_map["code"],
                                    sector_map["industry_gate"])
               if pd.notna(g) and g}
    s_amt = {g: np.zeros(n) for g in gates}
    s_up = {g: np.zeros(n) for g in gates}
    s_dn = {g: np.zeros(n) for g in gates}
    s_ct = {g: np.zeros(n) for g in gates}
    s_pch = {g: [[] for _ in range(n)] for g in gates}

    for code, dates, adj, pch, amt, turn in iter_stock_daily_cached():  # noqa
        g = gate_of.get(code)
        highs = []
        for i, d in enumerate(dates):
            p = dpos[d]
            pc = pch[i]
            valid = pc is not None and np.isfinite(pc)
            if valid:
                mkt_pch_lists[p].append(pc)
                if pc > 0:
                    mkt_up[p] += 1
                elif pc < 0:
                    mkt_down[p] += 1
                else:
                    mkt_flat[p] += 1
            if amt[i]:
                mkt_amt[p] += amt[i]
                if g:
                    s_amt[g][p] += amt[i]
                    s_ct[g][p] += 1
            if g and valid:
                s_pch[g][p].append(pc)
                if pc > 0:
                    s_up[g][p] += 1
                elif pc < 0:
                    s_dn[g][p] += 1
            # 20 日新高（复权 close 口径：high 用 close 序列近似——
            # 保守选择：以复权收盘创新高计数，避免 high 未复权假跳）
            if adj[i] is not None:
                if len(highs) >= 20 and adj[i] >= max(highs[-20:]):
                    mkt_nh20[p] += 1
                highs.append(adj[i])

    mkt = pd.DataFrame({
        "date": all_dates,
        "mkt_amount_yi": mkt_amt / 1e8,
        "advancers": mkt_up,
        "decliners": mkt_down,
        "unchanged": mkt_flat,
        "pct_up": mkt_up / np.maximum(mkt_up + mkt_down + mkt_flat, 1),
        "eq_ret_median": [float(np.median(v)) if v else None
                          for v in mkt_pch_lists],
        "new_high_20d_count": mkt_nh20,
    })
    rows = []
    for g in gates:
        for i, d in enumerate(all_dates):
            if s_ct[g][i] >= min_members:
                rows.append({
                    "date": d, "industry_gate": g,
                    "members_traded": int(s_ct[g][i]),
                    "amount_yi": s_amt[g][i] / 1e8,
                    "pct_up": (s_up[g][i] /
                               max(s_up[g][i] + s_dn[g][i], 1)),
                    "eq_ret_median": (float(np.median(s_pch[g][i]))
                                      if s_pch[g][i] else None),
                })
    sec = pd.DataFrame(rows)
    return mkt, sec


_CACHE = None


def iter_stock_daily_cached():
    global _CACHE
    if _CACHE is None:
        raise RuntimeError("call set_stock_cache() first")
    return _CACHE


def set_stock_cache(per_stock_dir: Path):
    """一次性读入全部个股日数据并缓存（双跑复用）。"""
    global _CACHE
    _CACHE = list(iter_stock_daily(per_stock_dir))


def index_calendar_and_close(day_file: Path):
    b = Path(day_file).read_bytes()
    dates, close = [], []
    for i in range(len(b) // 32):
        u = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        dates.append(f"{u // 10000}-{u // 100 % 100:02d}-{u % 100:02d}")
        close.append(struct.unpack(
            "<i", b[i * 32 + 16:i * 32 + 20])[0] / 100.0)
    return dates, np.array(close)


# ---------------------------------------------------------------- 事件背景
def build_event_context(events: pd.DataFrame, mkt: pd.DataFrame,
                        sec: pd.DataFrame, sector_map: pd.DataFrame,
                        lookback: int = 20, pct_win: int = 60,
                        breadth_days: int = 5):
    """每事件一行：T0 as-of 市场/板块背景与相对强弱（不含 T0 后数据）。

    相对强弱 = 个股/板块/市场 的截至 T0 回看窗收益（复权口径）。
    """
    idates, iclose = index_calendar_and_close(
        Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day"))
    ipos = {d: i for i, d in enumerate(idates)}
    mpos = {d: i for i, d in enumerate(mkt["date"])}
    mkt = mkt.set_index("date")
    sec_g = {}                      # gate -> date-indexed frame
    for g, sub in sec.groupby("industry_gate"):
        sec_g[g] = sub.set_index("date")
    gate_of = {c: g for c, g in zip(sector_map["code"],
                                    sector_map["industry_gate"])
               if pd.notna(g) and g}

    # 个股复权收盘（相对强弱用）：从缓存取
    stock_adj = {}
    stock_close_date = {}
    for code, dates, adj, *_ in iter_stock_daily_cached():
        stock_adj[code] = (dates, adj)

    rows = []
    for r in events.itertuples(index=False):
        t0 = r.breakout_day
        eid = r.breakout_event_id
        code = r.code
        pfx = ("sh." if str(code).zfill(6).startswith(("6", "9")) else
               "sz.") + str(code).zfill(6)
        rec = {"breakout_event_id": eid, "code": code,
               "breakout_day": t0, "end_day": r.end_day,
               "industry_gate": gate_of.get(pfx)}
        ip = ipos.get(t0)
        mp = mpos.get(t0)
        # 市场背景（截至 T0 的 lookback 窗，含 T0）
        if ip is not None and ip >= lookback:
            c0, c1 = iclose[ip], iclose[ip - lookback]
            rec["mkt_ret_20d"] = (c0 / c1 - 1.0) * 100 if c1 else None
        else:
            rec["mkt_ret_20d"] = None
        if mp is not None:
            try:
                hist = mkt.loc[mkt.index[:mp + 1]]
                rec["mkt_amount_pctile_60d"] = float(
                    (hist["mkt_amount_yi"].iloc[-pct_win:]
                     .rank(pct=True).iloc[-1]))
                rec["mkt_breadth_5d"] = float(
                    hist["pct_up"].iloc[-breadth_days:].mean())
            except Exception:
                rec["mkt_amount_pctile_60d"] = None
                rec["mkt_breadth_5d"] = None
        # 板块背景与相对强弱
        g = rec["industry_gate"]
        dates, adj = stock_adj.get(pfx, ([], []))
        j = bisect_right(dates, t0) - 1
        j20 = j - lookback
        stock_ok = j20 >= 0 and adj[j] and adj[j20]
        if g and g in sec_g:
            sf = sec_g[g]
            if t0 in sf.index and mp is not None and mp >= lookback:
                try:
                    # 板块等权收益中位（窗内逐日中位复合）
                    med = sf["eq_ret_median"].loc[
                        mkt.index[mp - lookback + 1:mp + 1]]
                    med = med.dropna() / 100.0
                    rec["sector_ret_20d"] = float(
                        (1.0 + med).prod() - 1.0) * 100 if len(med) else None
                    sm = mkt["eq_ret_median"].loc[
                        mkt.index[mp - lookback + 1:mp + 1]].dropna() / 100.0
                    mret = float((1.0 + sm).prod() - 1.0) * 100 if len(sm) \
                        else None
                    rec["sector_vs_mkt_20d"] = (
                        rec["sector_ret_20d"] - mret
                        if rec.get("sector_ret_20d") is not None
                        and mret is not None else None)
                except Exception:
                    rec["sector_ret_20d"] = None
                    rec["sector_vs_mkt_20d"] = None
            else:
                rec["sector_ret_20d"] = None
                rec["sector_vs_mkt_20d"] = None
        else:
            rec["sector_ret_20d"] = None
            rec["sector_vs_mkt_20d"] = None
        # 个股相对板块
        if stock_ok and rec.get("sector_ret_20d") is not None:
            rec["stock_ret_20d"] = (adj[j] / adj[j20] - 1.0) * 100
            rec["stock_vs_sector_20d"] = (rec["stock_ret_20d"]
                                          - rec["sector_ret_20d"])
        else:
            rec["stock_ret_20d"] = None
            rec["stock_vs_sector_20d"] = None
        rows.append(rec)
    return pd.DataFrame(rows)
