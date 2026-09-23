"""t3_v2.py — 任务三 V2：事件级特征层 + 路径结果层（冻结实现）。

语义契约：docs/reports/T3_SUSTAIN_COVERAGE_AUDIT_V1.md（path_label_v1 + t3_id_v1
冻结版，commit da933a1）+ T3 V2 开工令。本模块只做物化，不做研究：
- 收益/删失公式逐项继承 forward_y40_lib（任务二冻结实现）；
- 四态删失 none/sample_end/security_history_end/data_gap + terminal_reason；
- primary 资格 breakout_day <= dataset_end - H 交易日；
- imputed 仅进敏感性文件（物理分离）；
- 特征层信息截止 T0 收盘（T0 当日日线允许）；
- 缺失保持缺失（不插补、不当 0）；滚动窗口记录真实观测数；
- chip 量纲 = 冻结库元/股（不除 100）。

确定性：无随机数；全部输出按 breakout_event_id 排序。
"""
from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
DATASET_END = "2026-09-18"          # V1 冻结的全局数据末日（库级实测）
HS = (5, 10, 20, 40)
FLAT_RET_PCT = 0.5                   # 滞涨阈值（V1 §3.2 冻结）
VOL_RATIO_HI = 1.5
VOL_RATIO_LO = 0.8
PULLBACK_MIN_DEPTH = 0.05            # V1 §6.4 冻结


# ---------------------------------------------------------------- 市场层

def market_calendar_and_close(index_file: str = "sh999999"):
    """上证日历 + 收盘(int32/100)。逐项继承 forward_y40_lib.market_calendar。"""
    b = (Path("/root/tdx_data/vipdoc/sh/lday") / f"{index_file}.day").read_bytes()
    dates, close = [], []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        dates.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
        close.append(struct.unpack("<i", b[i * 32 + 16:i * 32 + 20])[0] / 100.0)
    return dates, np.array(close)


# ---------------------------------------------------------------- 个股数据

@dataclass
class StockData:
    """冻结库单股视图（unadj + hfq + 因子切片）。

    有效观测 = 库行存在且因子存在（V1 §5 规则：缺因子即无效，不默认 F=1）。
    量能有效 = volume>0 且 amount>0 且非缺失。
    """
    code_pfx: str                     # sh.600000 形式（库文件主键）
    dates: list                       # 升序库行日期
    o: dict; h: dict; l: dict; c: dict
    vol: dict; amt: dict; turn: dict
    hfq_h: dict; hfq_c: dict
    F: dict                           # date -> float（仅存在键）
    valid: list                       # 有效观测日期（升序）
    vpos: set                         # 量能有效日

    @property
    def adj(self):
        if not hasattr(self, "_adj"):
            self._adj = {d: self.c[d] * self.F[d] for d in self.valid}
        return self._adj

    def adj_h(self, d):
        return self.h[d] * self.F[d] if d in self.F else None

    def adj_l(self, d):
        return self.l[d] * self.F[d] if d in self.F else None


def load_stock_data(code_pfx: str, factor_dates: dict) -> StockData:
    j = json.load(gzip.open(
        ROOT / f"data/adjustment_baostock/per_stock/{code_pfx}.json.gz", "rt"))
    dates = [r[0] for r in j["unadj"]]

    def num(v):
        return None if v in (None, "") else float(v)

    c = {r[0]: float(r[4]) for r in j["unadj"]}
    h = {r[0]: float(r[2]) for r in j["unadj"]}
    l = {r[0]: float(r[3]) for r in j["unadj"]}
    vol = {r[0]: num(r[5]) for r in j["unadj"]}
    amt = {r[0]: num(r[6]) for r in j["unadj"]}
    turn = {r[0]: num(r[7]) for r in j["unadj"]}
    hfq_h = {r[0]: float(r[2]) for r in j["hfq"]}
    hfq_c = {r[0]: float(r[4]) for r in j["hfq"]}
    F = factor_dates.get(code_pfx, {})
    valid = [d for d in dates if d in F]
    vpos = {d for d in dates
            if (vol.get(d) or 0) > 0 and (amt.get(d) or 0) > 0}
    return StockData(code_pfx=code_pfx, dates=dates, o=None, h=h, l=l, c=c,
                     vol=vol, amt=amt, turn=turn, hfq_h=hfq_h, hfq_c=hfq_c,
                     F=F, valid=valid, vpos=vpos)


def build_factor_cache(out_dir: Path) -> dict:
    """因子表 → 每股一个 json.gz 缓存（确定性，供逐股加载）。

    返回 {code_pfx: {date: F}}。缓存文件按 code 排序写入。
    """
    import csv
    cache_dir = out_dir / "_cache" / "factor"
    cache_dir.mkdir(parents=True, exist_ok=True)
    per_code = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            per_code.setdefault(row["code"], {})[row["date"]] = float(row["F"])
    for code in sorted(per_code):
        with gzip.open(cache_dir / f"{code}.json.gz", "wt") as f:
            json.dump(per_code[code], f)
    meta = {"stocks": len(per_code),
            "rows": sum(len(v) for v in per_code.values())}
    (cache_dir / "_meta.json").write_text(json.dumps(meta))
    return per_code


def load_factor_cache(out_dir: Path) -> dict:
    cache_dir = out_dir / "_cache" / "factor"
    per_code = {}
    for fp in sorted(cache_dir.glob("*.json.gz")):
        per_code[fp.name[:-8]] = json.load(gzip.open(fp, "rt"))
    return per_code


# ---------------------------------------------------------------- 事件宇宙

def load_events() -> pd.DataFrame:
    """冻结 lifecycle_stage4_v1_full → event_master 行（映射列原样保留）。"""
    import glob
    import pyarrow.parquet as pq
    rows = []
    for fp in sorted(glob.glob(str(
            ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full"
            "/partitions/**/*.parquet"), recursive=True)):
        t = pq.read_table(fp)
        df = t.to_pandas()
        rows.append(df[df["breakout_day"].notna()])
        del t, df
    ev = pd.concat(rows, ignore_index=True)
    ev["code"] = ev["code"].astype(str).str.zfill(6)
    ev["breakout_event_id"] = ev["code"] + "_" + ev["breakout_day"]
    keep = ["breakout_event_id", "code", "breakout_day", "lifecycle_id",
            "anchor_day", "preparation_start", "confirmation_day",
            "first_pullback_day", "divergence_day", "decay_day", "end_day",
            "end_reason", "right_censored", "days_total",
            "n_pullback_reattack_cycles", "stage_sequence",
            "pullback_event_ids"]
    ev = ev[keep].sort_values("breakout_event_id").reset_index(drop=True)
    return ev


# ---------------------------------------------------------------- 周线工具

def weekly_close_series(sd: StockData, t0: str):
    """截至 T0 的已完成周（ISO 周）合成：周收盘=该周最后一个交易观测收盘。

    未满周不合成：T0 所在周排除（V1 §2.2 冻结）。
    返回 [(iso_week, week_close, week_high, week_low, last_day)]，升序，
    只含 last_day < T0 所在周首日的周。
    """
    t0_year, t0_week, _ = pd.Timestamp(t0).isocalendar()
    out = {}
    for d in sd.valid:
        if d > t0:
            break
        ts = pd.Timestamp(d)
        y, w, _ = ts.isocalendar()
        if (y, w) == (t0_year, t0_week):
            continue                     # T0 所在周（未完成）不合成
        a = sd.adj[d]
        key = f"{y}-W{w:02d}"
        rec = out.get(key)
        if rec is None:
            out[key] = [a, a, a, d]      # close, high, low, last_day
        else:
            rec[0] = a                   # 后见日覆盖周收盘
            rec[1] = max(rec[1], sd.adj_h(d))
            rec[2] = min(rec[2], sd.adj_l(d))
            rec[3] = d
    return [(k, v[0], v[1], v[2], v[3]) for k, v in sorted(out.items())]


# ---------------------------------------------------------------- 标签层

def classify_censor(sd: StockData, mdates, mpos, t0: str, h: int,
                    last_global_pos: int):
    """四态删失分类（V1 §6.5 冻结顺序）。

    返回 (reason, ih, n_valid, terminal_reason)。
    """
    i0 = mpos[t0]
    ih = i0 + h
    if ih >= len(mdates) or mdates[ih] > DATASET_END:
        return "sample_end", ih, 0, None
    win = mdates[i0:ih + 1]
    n_valid = sum(1 for d in win if d in sd.adj)
    if n_valid == h + 1:
        return "none", ih, n_valid, None
    last_valid = sd.valid[-1] if sd.valid else None
    if last_valid is None or last_valid < mdates[ih]:
        # 个股有效历史在窗口内终止（economic endpoint 候选）
        tr = "unknown"          # V2：退市终态核实走外部名单，核实前 unknown
        return "security_history_end", ih, n_valid, tr
    return "data_gap", ih, n_valid, None


def compute_labels(sd: StockData, t0: str, mdates, mclose, mpos,
                   last_global_pos: int) -> dict:
    """§6.1–6.5 全套（主口径；censored 行收益为 null，敏感性文件另算）。"""
    out = {"breakout_day": t0}
    adj = sd.adj
    p0 = adj.get(t0)
    prior = [d for d in sd.valid if d < t0]
    prior_hist_max = max((adj[d] for d in prior), default=None)
    # B1 基准（量能，前 20 个有效观测；供 §6.4 回调量能比）
    prior_vpos = [d for d in prior if d in sd.vpos][-20:]
    vol_base = (float(np.mean([sd.vol[d] for d in prior_vpos]))
                if len(prior_vpos) >= 20 else None)

    for h in HS:
        reason, ih, n_valid, tr = classify_censor(
            sd, mdates, mpos, t0, h, last_global_pos)
        out[f"t{h}_day"] = mdates[ih] if ih < len(mdates) else None
        out[f"primary_eligible_h{h}"] = bool(mpos[t0] + h <= last_global_pos)
        out[f"label_avail_h{h}"] = out[f"t{h}_day"] if reason == "none" else None
        out[f"censored_reason_h{h}"] = reason
        out[f"win_coverage_h{h}"] = round(n_valid / (h + 1), 6) \
            if reason != "sample_end" else None
        out[f"terminal_reason_h{h}"] = tr if reason == "security_history_end" else None

        y_raw = y_ex = None
        if reason == "none":
            i0 = mpos[t0]
            ph = adj[mdates[ih]]
            # 公式逐项镜像 forward_y40_lib（float64 顺序一致）
            y_raw = float(np.log(ph / p0))
            y_ex = float(np.log(ph / p0) - np.log(mclose[ih] / mclose[i0]))
        out[f"y{h}_raw_log"] = y_raw
        out[f"y{h}_mkt_excess_log"] = y_ex

        # §6.2–6.4 路径指标（仅完整窗口）
        if reason == "none":
            i0 = mpos[t0]
            win = mdates[i0:ih + 1]
            cs = np.array([adj[d] for d in win])           # 复权收盘
            hs = np.array([sd.adj_h(d) for d in win])      # 复权 high
            ls = np.array([sd.adj_l(d) for d in win])      # 复权 low

            runmax = np.maximum.accumulate(cs)
            dd = 1.0 - cs / runmax
            mdd_idx = int(np.argmax(dd))
            out[f"mdd_close_h{h}"] = float(dd[mdd_idx])
            peak_pos = int(np.argmax(cs[:mdd_idx + 1]))
            out[f"dd_peak_day_h{h}"] = peak_pos
            out[f"dd_trough_day_h{h}"] = mdd_idx
            # 恢复：峰值日后收盘重新 >= 峰值收盘
            rec = None
            for k in range(mdd_idx + 1, len(win)):
                if cs[k] >= cs[peak_pos]:
                    rec = k - peak_pos
                    break
            out[f"recover_days_h{h}"] = rec
            out[f"recovered_h{h}"] = rec is not None

            # 盘中口径：low_t 相对截至前一日（含 T0）high 的回撤
            mdd_i = 0.0
            peak_h = hs[0]
            for k in range(1, len(win)):
                ddk = 1.0 - ls[k] / peak_h
                if ddk > mdd_i:
                    mdd_i = ddk
                if hs[k] > peak_h:
                    peak_h = hs[k]
            out[f"mdd_intraday_h{h}"] = float(mdd_i)

            # 新高（相对 T0 前历史最高复权收盘；严格 >）
            nh = [k for k in range(1, len(win)) if cs[k] > prior_hist_max] \
                if prior_hist_max is not None else []
            out[f"time_to_new_high_h{h}"] = nh[0] if nh else None
            out[f"n_new_high_h{h}"] = len(nh)

            # 趋势维持：自 T0 起收盘 >= 滚动 MA20（20 个有效观测窗口，含窗前）
            alive = 0
            broke = False
            for k in range(len(win)):
                obs20 = (prior + list(win))[: len(prior) + k + 1][-20:]
                ma20 = float(np.mean([adj[d] for d in obs20]))
                if cs[k] >= ma20:
                    alive += 1
                else:
                    broke = True
                if broke:
                    break
            out[f"trend_alive_days_h{h}"] = alive
            obs20_last = (prior + list(win))[-20:]
            ma_last = float(np.mean([adj[d] for d in obs20_last]))
            out[f"above_ma20_last_h{h}"] = bool(cs[-1] >= ma_last)

            # 路径效率
            lr = np.abs(np.diff(np.log(cs)))
            denom = float(lr.sum())
            out[f"path_efficiency_h{h}"] = (
                float(abs(np.log(cs[-1] / cs[0])) / denom) if denom > 0 else None)

            # §6.4 回调与量能
            if dd[mdd_idx] >= PULLBACK_MIN_DEPTH:
                out[f"pullback_depth_h{h}"] = float(dd[mdd_idx])
                seg = [sd.vol.get(mdates[i0 + k]) for k in
                       range(peak_pos, mdd_idx + 1)]
                ok = all(v is not None and v > 0 for v in seg)
                out[f"pullback_len_h{h}"] = mdd_idx - peak_pos
                out[f"pullback_vol_ratio_h{h}"] = (
                    float(np.mean(seg) / vol_base)
                    if ok and vol_base else None)
            else:
                out[f"pullback_depth_h{h}"] = 0.0
                out[f"pullback_len_h{h}"] = None
                out[f"pullback_vol_ratio_h{h}"] = None

            vrs, misses = [], 0
            for d in win:
                v = sd.vol.get(d)
                if v is None or v <= 0 or vol_base is None:
                    misses += 1
                else:
                    vrs.append(v / vol_base)
            out[f"vol_ratio_mean_h{h}"] = float(np.mean(vrs)) if vrs else None
            out[f"vol_ratio_last_h{h}"] = float(np.mean(vrs[-5:])) \
                if len(vrs) >= 5 else None
            turn_sum, tmiss = 0.0, 0
            for d in win:
                t = sd.turn.get(d)
                if t is None or t <= 0:
                    tmiss += 1
                else:
                    turn_sum += t
            out[f"turn_cum_h{h}"] = turn_sum
            out[f"turn_miss_days_h{h}"] = tmiss
            out[f"vol_miss_days_h{h}"] = misses
        else:
            for suf in ("mdd_close", "dd_peak_day", "dd_trough_day",
                        "recover_days", "recovered", "mdd_intraday",
                        "time_to_new_high", "n_new_high", "trend_alive_days",
                        "above_ma20_last", "path_efficiency", "pullback_depth",
                        "pullback_len", "pullback_vol_ratio", "vol_ratio_mean",
                        "vol_ratio_last", "turn_cum", "turn_miss_days",
                        "vol_miss_days"):
                out[f"{suf}_h{h}"] = None

    return out


def compute_labels_sensitivity(sd: StockData, t0: str, mdates, mclose, mpos,
                               last_global_pos: int) -> dict:
    """敏感性口径：仅 censored 事件，T+H 无价时向前取最近可得日（不进主表）。"""
    out = {"breakout_day": t0}
    adj = sd.adj
    p0 = adj.get(t0)
    for h in HS:
        reason, ih, n_valid, tr = classify_censor(
            sd, mdates, mpos, t0, h, last_global_pos)
        out[f"censored_reason_h{h}"] = reason
        if reason == "none" or p0 is None:
            out[f"y{h}_raw_log"] = None
            out[f"y{h}_mkt_excess_log"] = None
            out[f"imputed_h{h}"] = None
            out[f"imputed_from_day_h{h}"] = None
            continue
        i0 = mpos[t0]
        if ih >= len(mdates):
            out[f"y{h}_raw_log"] = None
            out[f"y{h}_mkt_excess_log"] = None
            out[f"imputed_h{h}"] = None
            out[f"imputed_from_day_h{h}"] = None
            continue
        back = next((mdates[k] for k in range(ih, i0, -1)
                     if mdates[k] in adj), None)
        if back is None:
            out[f"y{h}_raw_log"] = None
            out[f"y{h}_mkt_excess_log"] = None
            out[f"imputed_h{h}"] = None
            out[f"imputed_from_day_h{h}"] = None
            continue
        ph = adj[back]
        out[f"y{h}_raw_log"] = float(np.log(ph / p0))
        out[f"y{h}_mkt_excess_log"] = float(
            np.log(ph / p0) - np.log(mclose[ih] / mclose[i0]))
        out[f"imputed_h{h}"] = back != mdates[ih]
        out[f"imputed_from_day_h{h}"] = back
    return out


# ---------------------------------------------------------------- 特征层

def compute_features_a1(sd: StockData, t0: str) -> dict:
    """§2.2 A1 纯价格结构（信息截止 T0 收盘，T0 当日允许）。"""
    adj = sd.adj
    out = {"breakout_day": t0}
    prior = [d for d in sd.valid if d < t0]           # T0 不入参考窗
    out["a1_prior_valid_obs_n"] = len(prior)

    ref60_obs = prior[-60:]
    out["a1_ref60_obs_n"] = len(ref60_obs)
    out["a1_ref60"] = max((adj[d] for d in ref60_obs), default=None)
    out["a1_ref60_window_first_day"] = ref60_obs[0] if ref60_obs else None
    c0 = adj.get(t0)
    out["a1_breakout_margin"] = (c0 / out["a1_ref60"] - 1.0
                                 if c0 and out["a1_ref60"] else None)

    for w in (60, 120):
        obs = prior[-w:]
        out[f"a1_dist_prior_high_{w}_obs_n"] = len(obs)
        mx = max((adj[d] for d in obs), default=None)
        out[f"a1_dist_prior_high_{w}"] = (c0 / mx - 1.0 if c0 and mx else None)

    for w in (20, 60):
        obs = prior[-(w - 1):] + [t0]                  # MA 含 T0
        out[f"a1_ma{w}_obs_n"] = len(obs)
        ma = float(np.mean([adj[d] for d in obs])) if len(obs) == w else None
        out[f"a1_dist_ma{w}"] = (c0 / ma - 1.0 if c0 and ma else None)

    # TR 波动收缩（复权）
    def tr_series(obs):
        trs = []
        for i in range(1, len(obs)):
            pc, d = adj[obs[i - 1]], obs[i]
            trs.append(max(sd.adj_h(d) - sd.adj_l(d),
                           abs(sd.adj_h(d) - pc), abs(sd.adj_l(d) - pc)))
        return trs

    trs = tr_series(prior[-61:])
    if len(trs) >= 60:
        out["a1_vol_contraction"] = float(np.mean(trs[-20:]) / np.mean(trs[-60:]))
        out["a1_vol_contraction_obs_n"] = len(trs)
    else:
        out["a1_vol_contraction"] = None
        out["a1_vol_contraction_obs_n"] = len(trs)

    # 周线（已完成周；未满周不合成）
    wk = weekly_close_series(sd, t0)
    out["a1_wk_completed_n"] = len(wk)
    closes = [w[1] for w in wk]
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break
    out["a1_wk_up_streak"] = streak if len(closes) >= 2 else None
    if len(wk) >= 2:
        (_, c1, h1, l1, _), (_, c2, h2, l2, _) = wk[-2], wk[-1]
        hh = h2 > h1
        hl = l2 > l1
        out["a1_wk_hl_struct"] = ("HH_HL" if hh and hl else
                                  "HH_LL" if hh else
                                  "LH_HL" if hl else "LH_LL")
    else:
        out["a1_wk_hl_struct"] = None
    for w in (4, 8, 12):
        if len(closes) >= w + 1:
            out[f"a1_wk_cum_ret_{w}w"] = float(np.log(closes[-1] / closes[-1 - w]))
        else:
            out[f"a1_wk_cum_ret_{w}w"] = None
    if len(closes) >= 8:
        yv = np.arange(8, dtype=float)
        xv = np.array(closes[-8:], dtype=float)
        slope = float(np.polyfit(yv, np.log(xv), 1)[0])
        out["a1_wk_slope_8w"] = slope
    else:
        out["a1_wk_slope_8w"] = None
    hist_max = max((adj[d] for d in prior), default=None)
    out["a1_prior_hist_max"] = hist_max
    out["a1_dist_prior_hist_max"] = (c0 / hist_max - 1.0
                                     if c0 and hist_max else None)
    return out


def compute_features_b1(sd: StockData, t0: str) -> dict:
    """§3.2 B1 量价/资金效率（截止 T0 收盘）。缺失保持缺失。"""
    out = {"breakout_day": t0}
    prior = [d for d in sd.valid if d < t0 and d in sd.vpos]
    base = prior[-20:]
    out["b1_vol_base_obs_n"] = len(base)
    vol_base = float(np.mean([sd.vol[d] for d in base])) if len(base) == 20 else None
    v0, a0 = sd.vol.get(t0), sd.amt.get(t0)
    out["b1_vol_valid_t0"] = bool(v0 and v0 > 0 and a0 and a0 > 0)
    t0_turn = sd.turn.get(t0)
    out["b1_turn_valid_t0"] = bool(t0_turn and t0_turn > 0)
    out["b1_vol_ratio_20"] = (v0 / vol_base
                              if out["b1_vol_valid_t0"] and vol_base else None)

    tbase = [d for d in sd.valid if d < t0][-20:]
    tvals = [sd.turn[d] for d in tbase if sd.turn.get(d) is not None
             and sd.turn[d] > 0]
    out["b1_turn_base_obs_n"] = len(tvals)
    out["b1_turn_20_avg"] = float(np.mean(tvals)) if len(tvals) == 20 else None

    # 当日收益（复权 close-to-close）
    prior_any = [d for d in sd.valid if d < t0]
    pc = sd.adj[prior_any[-1]] if prior_any else None
    c0 = sd.adj.get(t0)
    r0 = (c0 / pc - 1.0) if (c0 and pc) else None
    out["b1_ret_t0"] = r0
    vr = out["b1_vol_ratio_20"]
    if vr is None or r0 is None:
        out["b1_day_state"] = None
    else:
        vstate = "high" if vr >= VOL_RATIO_HI else "low" if vr <= VOL_RATIO_LO \
            else "norm"
        rstate = "up" if r0 > 0 else "down" if r0 < 0 else "flat"
        if abs(r0 * 100.0) < FLAT_RET_PCT:
            rstate = "flat"
        out["b1_day_state"] = f"{vstate}_{rstate}"     # 9 态（报告披露六态歧义）

    # 缩量上涨延续（截至 T0 的连续天数）
    run = 0
    obs_all = [d for d in sd.valid if d <= t0]
    for i in range(len(obs_all) - 1, 0, -1):
        d, dp = obs_all[i], obs_all[i - 1]
        vd = sd.vol.get(d)
        if vd is None or vd <= 0:
            break
        pv = [sd.vol[x] for x in obs_all[max(0, i - 21):i]]
        pv = [x for x in pv if x and x > 0]
        if len(pv) < 20:
            break
        ratio = vd / float(np.mean(pv[-20:]))
        ret = sd.adj[d] / sd.adj[dp] - 1.0
        if ratio <= VOL_RATIO_LO and ret > 0:
            run += 1
        else:
            break
    out["b1_shrink_up_run"] = run
    out["b1_vol_miss_prior20_n"] = 20 - len([d for d in
                                             [d for d in sd.valid if d < t0]
                                             [-20:] if d in sd.vpos])
    return out


def compute_features_chip(sd: StockData, t0: str) -> dict:
    """§3.4 chip/VWAP（量纲=元/股，不除 100；窗口含 T0 严格全在）。

    窗口骨架镜像 V1 审计（t3_event_coverage_audit）：T0 + 前 w-1 个
    因子有效观测（有效观测=库行+因子，V1 §5）；全窗 vpos（vol>0 且
    amount>0）才可算，否则缺失（严格全窗，缺失不缩短窗口）。
    价格空间说明（报告披露）：vwap 由原始 amount/volume 构成，与原始
    close 同空间比较；窗口内除权会使 vwap 混合两种价格空间（冻结口径
    接受，见报告）。
    """
    out = {"breakout_day": t0}
    prior_valid = [d for d in sd.valid if d < t0]
    incl = ([t0] if t0 in sd.valid else []) + prior_valid[::-1]

    def vwap_of(win):
        vs = sum(sd.vol[d] for d in win)
        return sum(sd.amt[d] for d in win) / vs if vs > 0 else None

    for w in (5, 10, 20):
        win = incl[:w]
        full = len(win) == w and all(d in sd.vpos for d in win)
        out[f"chip_vwap{w}_obs_n"] = len(win)
        out[f"chip_vwap{w}_volmiss"] = 0 if not full else sum(
            1 for d in win if d not in sd.vpos)
        vw = vwap_of(win) if full else None
        c0 = sd.c.get(t0)
        out[f"chip_price_to_vwap_{w}d"] = (c0 / vw - 1.0
                                           if vw and c0 else None)
    out["chip_vwap_day"] = (sd.amt[t0] / sd.vol[t0]
                            if t0 in sd.vpos else None)

    # 成本带（冻结候选，报告审计）：同一有效观测骨架 + 全窗 vpos
    for w in (60, 120):
        win = incl[:w]
        full = len(win) == w and all(d in sd.vpos for d in win)
        out[f"chip_cost_zone_obs_n_{w}"] = len(win)
        if full:
            c0 = sd.c.get(t0)
            out[f"chip_cost_vwap_{w}"] = float(
                sum(sd.amt[d] for d in win) / sum(sd.vol[d] for d in win))
            out[f"chip_price_to_cost_vwap_{w}"] = (
                c0 / out[f"chip_cost_vwap_{w}"] - 1.0 if c0 else None)
            dv = [sd.amt[d] / sd.vol[d] for d in win]
            out[f"chip_cost_zone_pos_{w}"] = float(
                sum(1 for v in dv if v <= c0) / len(dv)) if c0 else None
        else:
            out[f"chip_cost_vwap_{w}"] = None
            out[f"chip_price_to_cost_vwap_{w}"] = None
            out[f"chip_cost_zone_pos_{w}"] = None
    return out
