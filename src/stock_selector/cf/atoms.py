from __future__ import annotations

import csv
import gzip
import json
import math
import statistics
import struct
from collections import defaultdict
from pathlib import Path

INSUFFICIENT = "INSUFFICIENT_SUPPORT"


def _num(value) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def percentile_rank(history: list[float], value: float) -> float:
    return sum(x <= value for x in history) / len(history) if history else 0.5


def rolling_median(values: list[float], end: int, window: int) -> float | None:
    xs = values[max(0, end - window):end]
    return statistics.median(xs) if len(xs) >= max(5, window // 2) else None


def read_tdx_day(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = path.read_bytes(); out = []
    for off in range(0, len(data) - 31, 32):
        d, op, hi, lo, cl, amount, volume, _ = struct.unpack("<IIIIIfII", data[off:off + 32])
        if d < 19900101 or d > 21001231:
            continue
        out.append({"date": str(d), "open": op / 100, "high": hi / 100,
                    "low": lo / 100, "close": cl / 100,
                    "amount": float(amount), "volume": float(volume) * 100})
    return out


def load_margin(raw: Path) -> dict[str, dict]:
    exchanges: dict[str, dict[str, tuple[float, float] | None]] = {"sse": {}, "szse": {}}
    for path in sorted((raw / "sse_margin").glob("summary_*.csv")):
        for row in csv.DictReader(path.open()):
            d = str(row.get("信用交易日期", "")).replace("-", "")
            bal, buy = _num(row.get("融资余额")), _num(row.get("融资买入额"))
            if len(d) == 8 and bal is not None and buy is not None:
                value = (bal, buy); old = exchanges["sse"].get(d)
                exchanges["sse"][d] = value if old is None or old == value else None
    for path in sorted((raw / "szse_margin").glob("*.csv")):
        d = path.stem[:8]; rows = list(csv.DictReader(path.open()))
        if not rows: continue
        bal, buy = _num(rows[0].get("融资余额")), _num(rows[0].get("融资买入额"))
        if bal is not None and buy is not None:
            value = (bal * 1e8, buy * 1e8); old = exchanges["szse"].get(d)
            exchanges["szse"][d] = value if old is None or old == value else None
    combined = {}
    for d in sorted(set(exchanges["sse"]) & set(exchanges["szse"])):
        sse, szse = exchanges["sse"].get(d), exchanges["szse"].get(d)
        if sse is not None and szse is not None:
            combined[d] = {"balance": sse[0] + szse[0], "buy": sse[1] + szse[1],
                           "sources": ["sse_official", "szse_official"]}
    return combined


def overlay_live_margin(data: dict[str, dict], live: Path | None) -> dict[str, dict]:
    if live is None or not live.exists(): return data
    streams = {}
    for exchange in ("sse", "szse"):
        path = live / f"margin_{exchange}.jsonl.gz"; rows = {}
        if path.exists():
            for line in gzip.open(path, "rt"):
                r = json.loads(line); d = str(r.get("date", "")).replace("-", "")
                bal = _num(r.get("rzye", r.get("融资余额"))); buy = _num(r.get("rzmre", r.get("融资买入额")))
                if bal is not None and buy is not None:
                    if exchange == "szse": bal *= 1e8; buy *= 1e8
                    rows[d] = (bal, buy)
        streams[exchange] = rows
    for d in sorted(set(streams["sse"]) & set(streams["szse"])):
        a, b = streams["sse"][d], streams["szse"][d]
        data[d] = {"balance": a[0]+b[0], "buy": a[1]+b[1],
                   "sources": ["sse_official", "szse_official"]}
    return data


def replay_margin(raw: Path, live: Path | None = None) -> list[dict]:
    data = overlay_live_margin(load_margin(raw), live); dates = sorted(data); balances = [data[d]["balance"] for d in dates]; rows = []
    for i, d in enumerate(dates):
        if i < 20 or len(data[d]["sources"]) < 2:
            rows.append({"date": d, "atom": "M", "state": INSUFFICIENT, "reason": "need_20d_and_both_exchanges"}); continue
        bal = balances[i]; flow = bal - balances[i - 1]; prev_flow = balances[i - 1] - balances[i - 2]
        base = statistics.fmean(balances[i - 20:i]); pressure = bal / base - 1 if base else None
        velocity = flow - prev_flow
        recent = [balances[j] - balances[j - 1] for j in range(i - 4, i + 1)]
        if all(x > 0 for x in recent) and pressure is not None and pressure >= 0.01: state = "LEVERAGE_BUILDING"
        elif flow < 0 and velocity < 0 and sum(x < 0 for x in recent) >= 4: state = "DELEVERAGING_ACCELERATING"
        elif flow < 0 and sum(x < 0 for x in recent) >= 3: state = "DELEVERAGING"
        elif pressure is not None and pressure <= -0.03 and flow >= 0: state = "DELEVERAGED"
        else: state = "NEUTRAL"
        rows.append({"date": d, "atom": "M", "state": state,
                     "financing_balance_pressure": pressure, "financing_flow": flow,
                     "deleveraging_velocity": velocity, "balance": bal,
                     "available_at": f"{d}+1 conservative", "source_id": "sse_szse_official_margin_v1"})
    return rows


def replay_l4(tdx_root: Path) -> list[dict]:
    adv = {r["date"]: r for r in read_tdx_day(tdx_root / "vipdoc/sh/lday/sh880005.day")}
    lim = {r["date"]: r for r in read_tdx_day(tdx_root / "vipdoc/sh/lday/sh880006.day")}
    dates = sorted(set(adv) & set(lim)); counts = [adv[d]["close"] for d in dates]; amounts = [adv[d]["amount"] for d in dates]; rows = []
    for i, d in enumerate(dates):
        if i < 60:
            rows.append({"date": d, "atom": "L4", "state": INSUFFICIENT, "reason": "need_60d_history"}); continue
        p = percentile_rank(counts[max(0, i - 250):i], counts[i]); med = rolling_median(amounts, i, 20)
        ar = amounts[i] / med if med else 1.0; up = counts[i]; zt = lim[d]["close"]
        if p <= .1 and ar >= 1.25: state = "CAPITULATION"
        elif p <= .2: state = "PANIC"
        elif p >= .9 and zt >= 80 and ar >= 1.2: state = "EUPHORIA"
        elif p >= .75 and zt >= 50: state = "FOMO"
        elif p >= .5 and counts[i] > statistics.median(counts[i-5:i]): state = "RECOVERY"
        else: state = "APATHY"
        rows.append({"date": d, "atom": "L4", "state": state, "advancers": up,
                     "limit_up": zt, "advancers_percentile": p, "amount_ratio20": ar,
                     "available_at": f"{d} evening", "source_id": "tdx_880005_880006_v1"})
    return rows


def load_etf_snapshots(raw: Path, live: Path | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for path in sorted((raw / "sse_etf_scale").glob("*.csv")):
        for r in csv.DictReader(path.open()):
            d = str(r.get("统计日期", path.stem)).replace("-", "")[:8]
            sh = _num(r.get("基金份额")); code = str(r.get("基金代码", "")).zfill(6)
            if sh is not None: out[d].append({"code": code, "name": r.get("基金简称", ""), "shares": sh})
    for path in sorted((raw / "szse_etf_scale").glob("*.csv")):
        for r in csv.DictReader(path.open()):
            d = str(r.get("日期", "")).replace("-", "")[:8]
            sh = _num(r.get("基金份额", r.get("当日份额"))); code = str(r.get("基金代码", "")).zfill(6)
            if len(d) == 8 and sh is not None: out[d].append({"code": code, "name": r.get("基金简称", ""), "shares": sh})
    if live is not None and live.exists():
        streams = {}
        for exchange in ("sse", "szse"):
            path = live / f"etf_{exchange}.jsonl.gz"; by_date = defaultdict(dict)
            if path.exists():
                for line in gzip.open(path, "rt"):
                    r = json.loads(line); d = str(r.get("date", "")).replace("-", ""); code = str(r.get("code", "")).zfill(6)
                    by_date[d][code] = {"code": code, "name": str(r.get("name", "")), "shares": float(r["shares"])}
            streams[exchange] = by_date
        # A prospective date becomes observable only when both exchanges landed.
        for d in set(streams["sse"]) & set(streams["szse"]):
            old = {r["code"]: r for r in out[d]}
            for records in (streams["sse"][d], streams["szse"][d]):
                for code, record in records.items():
                    if not record["name"] and code in old: record["name"] = old[code]["name"]
                    old[code] = record
            out[d] = list(old.values())
    return dict(out)


def replay_l1(raw: Path, universe_path: Path, live: Path | None = None) -> list[dict]:
    snapshots = load_etf_snapshots(raw, live); cfg = json.loads(universe_path.read_text()); excludes = cfg["exclusion_words_v1"]
    families = cfg["families"]; dates = sorted(snapshots); totals: dict[str, dict[str, float]] = {}
    for d in dates:
        totals[d] = {}
        for family, spec in families.items():
            members = [r for r in snapshots[d] if any(p.lower() in r["name"].lower() for p in spec["name_pattern"])
                       and not any(x.lower() in r["name"].lower() for x in excludes)]
            if members: totals[d][family] = sum(r["shares"] for r in members)
    rows = []
    for i, d in enumerate(dates):
        if i == 0: rows.append({"date": d, "atom": "L1", "state": INSUFFICIENT, "reason": "need_previous_snapshot"}); continue
        prev = totals[dates[i-1]]; cur = totals[d]; common = sorted(set(prev) & set(cur)); deltas = []
        unsafe = []
        for f in common:
            ratio = cur[f] / prev[f] if prev[f] else 0
            # G9: large mechanical-looking jumps require an independently verified adjustment factor.
            if ratio <= .5 or ratio >= 2.0: unsafe.append(f)
            else: deltas.append((cur[f] - prev[f]) / prev[f])
        if unsafe or len(deltas) < 3:
            rows.append({"date": d, "atom": "L1", "state": INSUFFICIENT,
                         "reason": "G9_adjustment_unverified" if unsafe else "fewer_than_3_families",
                         "unsafe_families": unsafe}); continue
        net = statistics.median(deltas); history = [r.get("family_median_delta") for r in rows[-60:] if r.get("family_median_delta") is not None]
        scale = statistics.median(abs(x) for x in history) if len(history) >= 20 else None
        if scale is None or scale == 0: state = "NORMAL"
        elif net >= 3 * scale: state = "STABILIZATION_ACTIVE"
        elif net >= 1.5 * scale: state = "STABILIZATION_READY"
        elif net > 0: state = "WATCH"
        elif any(r.get("state") == "STABILIZATION_ACTIVE" for r in rows[-5:]): state = "NORMALIZING"
        else: state = "NORMAL"
        rows.append({"date": d, "atom": "L1", "state": state, "family_median_delta": net,
                     "families_observed": len(deltas), "available_at": f"{d}+1 conservative",
                     "source_id": "sse_szse_official_etf_share_v1", "g9": "passed_no_large_ratio_jump"})
    return rows
