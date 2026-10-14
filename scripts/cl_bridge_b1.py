#!/usr/bin/env python3
"""Capital Bridge B1: CD-5 cost state x daily price-impact lambda.

Read-only research sidecar. Does not alter CD-5 or production outputs.
Frozen protocol: docs/external_ideas/radar/BRIDGE_B1_PREREGISTRATION.md
"""
from __future__ import annotations
import csv, gzip, hashlib, json, math, statistics, time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "cd" / "daily_fullmarket"
AMT = ROOT / "data" / "r2" / "market_ext"
EPS = ROOT / "data" / "cd" / "l4_episodes.json.gz"
SAMPLE = ROOT / "output" / "research" / "csr" / "08_pilot_cases" / "phase_a" / "sample_selection.json"
OUT = ROOT / "data" / "cl_radar" / "bridge_b1"
REPORT = ROOT / "docs" / "external_ideas" / "radar" / "BRIDGE_B1_REPORT.md"
NBUCKETS = 50
MIN_VALID = 15
WINDOW = 20


def read_json_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def frozen_codes():
    x = json.loads(SAMPLE.read_text(encoding="utf-8"))
    codes = [r["code"] for g in x["groups"].values() for r in g["chosen"]]
    return codes, hashlib.sha256(("\n".join(codes) + "\n").encode()).hexdigest()


def qweighted(hist, lo, hi, frac):
    total = sum(hist)
    if total <= 0:
        return None
    target = total * frac
    acc = 0.0
    span = hi - lo
    for b, w in enumerate(hist):
        if acc + w >= target and w > 0:
            return lo + (b + (target - acc) / w) / NBUCKETS * span
        acc += w
    return hi


def safe_float(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def parse_daily(code):
    six = code.split(".")[-1]
    rec = json.loads(gzip.open(D / f"{six}.json.gz", "rt", encoding="utf-8").read())
    dates = rec["dates"]
    q = {r[0]: r for r in rec["qfq"]}
    u = {r[0]: r for r in rec["unadj"]}
    m = json.loads((AMT / f"{six}.json").read_text(encoding="utf-8"))
    a = {r["date"]: r for r in m["rows"]}
    rows = []
    for d in dates:
        qr, ur, ar = q.get(d), u.get(d), a.get(d)
        if not qr or not ur:
            continue
        # qfq layout from CD-5: date, open, close, high, low, volume
        close, high, low = safe_float(qr[2]), safe_float(qr[3]), safe_float(qr[4])
        vol = safe_float(ur[5])
        amount = safe_float(ar.get("amount")) if ar else None
        rows.append({"date": d, "close": close, "high": high, "low": low,
                     "volume": vol, "amount": amount})
    return rows


def limit_like(code, ret, row):
    # Conservative diagnostic only; no exchange limit claim is made.
    if row["high"] is not None and row["low"] is not None and abs(row["high"] - row["low"]) <= 1e-12:
        return True
    if ret is None:
        return False
    six = code.split(".")[-1]
    threshold = 0.295 if six.startswith("8") or six.startswith("4") else (0.195 if six.startswith(("30", "68")) else 0.095)
    return abs(ret) >= threshold


def ols_no_intercept(points):
    if len(points) < MIN_VALID:
        return None
    xx = sum(x*x for x, y in points)
    return None if xx <= 0 else sum(x*y for x, y in points) / xx


def metrics(code, rows, i):
    if i < WINDOW:
        return None
    win = rows[i-WINDOW+1:i+1]
    points_raw, points_norm, amihud = [], [], []
    excluded = Counter()
    for j, r in enumerate(win):
        row_i = i - WINDOW + 1 + j
        prev = rows[row_i - 1]["close"]
        c, amt = r["close"], r["amount"]
        if c is None or prev is None or prev <= 0 or amt is None or amt <= 0:
            excluded["missing_or_invalid"] += 1
            continue
        ret = c / prev - 1.0
        if limit_like(code, ret, r):
            excluded["limit_like_or_one_price"] += 1
            continue
        sign = 1.0 if ret > 0 else (-1.0 if ret < 0 else 0.0)
        of = amt * sign
        if sign == 0:
            excluded["zero_return"] += 1
            continue
        points_raw.append((of, c - prev, prev))
        amihud.append(abs(ret) / amt)
    adv = sum(r["amount"] for r in win if r["amount"] is not None and r["amount"] > 0) / max(1, sum(1 for r in win if r["amount"] is not None and r["amount"] > 0))
    if adv <= 0:
        return None
    raw_points = [(of, dp) for of, dp, prev in points_raw]
    for of, dp, prev in points_raw:
        # amount/ADV is dimensionless; response is return.
        # Raw price lambda and normalized return lambda are both retained.
        points_norm.append((of / adv, dp / prev if prev else 0.0))
    raw = ols_no_intercept(raw_points)
    norm = ols_no_intercept(points_norm)
    # Exploratory marginal impact concavity: log(|return|) on log(amount/ADV).
    logpts = []
    for of, dp, prev in points_raw:
        if prev and abs(dp) > 0 and adv > 0 and abs(of) > 0:
            logpts.append((math.log(abs(of) / adv), math.log(abs(dp / prev))))
    beta = None
    if len(logpts) >= MIN_VALID:
        xm = sum(x for x, y in logpts) / len(logpts)
        ym = sum(y for x, y in logpts) / len(logpts)
        den = sum((x - xm) ** 2 for x, y in logpts)
        if den > 0:
            beta = sum((x - xm) * (y - ym) for x, y in logpts) / den
    return {"lambda_raw": raw, "lambda_norm": norm, "impact_beta": beta,
            "lambda_raw_x1e8": raw * 1e8 if raw is not None else None,
            "amihud": statistics.fmean(amihud) if amihud else None,
            "valid_n": len(points_raw), "excluded_n": sum(excluded.values()),
            "exclusions": dict(excluded), "adv20": adv}


def state_rows(code, rows, episodes):
    by_date = {r["date"]: (i, r) for i, r in enumerate(rows)}
    out = []
    for ep in episodes:
        start, end = ep["start"], ep["end"]
        eligible = [(i, r) for i, r in enumerate(rows) if start <= r["date"] <= end]
        if not eligible:
            continue
        hist = [0.0] * NBUCKETS
        lo = hi = None
        for i, r in eligible:
            tp_vals = (r["high"], r["low"], r["close"], r["volume"])
            if any(v is None for v in tp_vals) or r["volume"] < 0:
                continue
            tp = (r["high"] + r["low"] + r["close"]) / 3.0
            lo = tp if lo is None else min(lo, tp)
            hi = tp if hi is None else max(hi, tp)
            span = hi - lo
            b = 0 if span <= 0 else min(NBUCKETS - 1, int((tp - lo) / span * NBUCKETS))
            hist[b] += r["volume"]
            p25 = qweighted(hist, lo, hi, 0.25)
            p50 = qweighted(hist, lo, hi, 0.50)
            p75 = qweighted(hist, lo, hi, 0.75)
            total = sum(hist)
            close = r["close"]
            if not total or p25 is None or p50 is None or p75 is None or close is None:
                continue
            pos = "below" if close < p25 else ("above" if close > p75 else "inside")
            dist = close / p50 - 1.0 if p50 else None
            width = (p75 - p25) / p50 if p50 else None
            # CD-5 semantics: cumulative histogram volume whose price_proxy is
            # strictly below current close. Approximate within the current bin.
            if close <= lo:
                below_ratio = 0.0
            elif close >= hi or hi <= lo:
                below_ratio = 1.0 if close > lo else 0.0
            else:
                bf = (close - lo) / (hi - lo) * NBUCKETS
                b0 = min(NBUCKETS, max(0, int(bf)))
                frac = bf - int(bf)
                below = sum(hist[:b0])
                if b0 < NBUCKETS:
                    below += hist[b0] * frac
                below_ratio = below / total if total else None
            lm = metrics(code, rows, i)
            if lm is None:
                continue
            out.append({"code": code, "episode_id": ep["episode_id"], "date": r["date"],
                        "episode_origin": ep.get("origin"), "cost_position": pos,
                        "cost_center_p50": p50, "cost_p25": p25, "cost_p75": p75,
                        "cost_band_width_norm": width, "distance_to_cost_center": dist,
                        "volume_below_current_price_ratio": below_ratio,
                        **{k: v for k, v in lm.items() if k != "exclusions"},
                        "lambda_exclusions": json.dumps(lm["exclusions"], sort_keys=True)})
    return out


def main():
    t0 = time.time(); OUT.mkdir(parents=True, exist_ok=True)
    codes, sample_sha = frozen_codes()
    eps_all = read_json_gz(EPS)["episodes"]
    eps_by = defaultdict(list)
    for e in eps_all:
        if e["stock"] in {c.split(".")[-1] for c in codes}:
            eps_by[e["stock"]].append(e)
    all_rows = []; audit = []; errors = []
    for n, code in enumerate(codes, 1):
        six = code.split(".")[-1]
        try:
            rows = parse_daily(code)
            es = eps_by[six]
            got = state_rows(code, rows, es)
            all_rows.extend(got)
            audit.append({"code": code, "daily_rows": len(rows), "amount_rows": sum(r["amount"] is not None and r["amount"] > 0 for r in rows),
                          "episodes": len(es), "observations": len(got)})
            print(f"{n}/{len(codes)} {code} daily={len(rows)} eps={len(es)} obs={len(got)}", flush=True)
        except Exception as e:
            errors.append({"code": code, "error": repr(e)})
            print(f"ERROR {code}: {e}", flush=True)
    fields = sorted({k for r in all_rows for k in r})
    with gzip.open(OUT / "observations.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(all_rows)
    summary = {
        "protocol": "capital-bridge-b1-v1", "sample_n": len(codes), "sample_sha": sample_sha,
        "episode_n": sum(len(v) for v in eps_by.values()), "observation_n": len(all_rows),
        "errors": errors, "audit": audit, "elapsed_sec": time.time() - t0,
        "definitions": {"cost": "CD-5 exact running 50-bin qfq HLC/3 + unadjusted volume",
                        "lambda": "20d no-intercept signed-flow OLS; normalized return lambda and Amihud retained",
                        "amount_source": "data/r2/market_ext, akshare stock_zh_a_daily(sina)"}}
    (OUT / "run_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    by_pos = Counter(r["cost_position"] for r in all_rows)
    by_origin = Counter(r["episode_origin"] for r in all_rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("# Bridge B1 Run Report\n\n" +
        f"- protocol: capital-bridge-b1-v1\n- sample: {len(codes)} codes; sha `{sample_sha}`\n" +
        f"- episodes: {summary['episode_n']}; observations: {len(all_rows)}; errors: {len(errors)}\n" +
        f"- cost positions: `{dict(by_pos)}`\n- origins: `{dict(by_origin)}`\n- elapsed_sec: {summary['elapsed_sec']:.1f}\n\n" +
        "This is a mechanism-observation dataset only. No production decision or CD-5 artifact was modified.\n",
        encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("sample_n", "episode_n", "observation_n", "errors", "elapsed_sec")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
