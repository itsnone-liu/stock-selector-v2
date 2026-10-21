#!/usr/bin/env python3
"""TDX 涨跌分析工具 — 纯本地数据，无外部依赖、无对拍。

数据源: /root/tdx_data/vipdoc/{sh,sz,bj}/lday/*.day (裸价) + xdxr 事件表
复权:   客户端仿射口径 (src/r2/tdx_client.py adjust)，与通达信客户端一致

用法:
  python3 scripts/tdx_rise_fall.py --all --top 20
  python3 scripts/tdx_rise_fall.py --codes sh600125,sz000001 --bars 260
  python3 scripts/tdx_rise_fall.py --file /tmp/pool.txt --sort chg20d --top 30
  python3 scripts/tdx_rise_fall.py --all --realtime        # 叠加今日实时快照
输出:
  data/r2/tdx/rise_fall_<date>.json  (全量)
  终端 markdown 表 (Top N + 分布统计)
"""
from __future__ import annotations
import argparse, gzip, json, os, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "r2"))
from r2.tdx_client import adjust  # noqa: E402

DATA = Path("/root/tdx_data/vipdoc")
CLI = Path("/root/tdx-protocol/realclient/cli.py")
BOOTSTRAP = Path("/root/tdx-protocol/lab/op11_template.bin")
REC = struct.Struct("<IIIIIfII")  # date, o, h, l, c, amount, vol, reserved  (价格 = /100)


def read_day(path: Path, nbars: int):
    """读最后 nbars 根裸价 K 线。"""
    size = path.stat().st_size
    n = min(nbars, size // 32)
    if n <= 0:
        return []
    with open(path, "rb") as f:
        f.seek((size // 32 - n) * 32)
        buf = f.read(n * 32)
    out = []
    for i in range(0, len(buf), 32):
        d, o, h, l, c, amt, vol, _ = REC.unpack(buf[i:i + 32])
        if d < 19000101:
            continue
        out.append((d, o / 100, h / 100, l / 100, c / 100, amt, vol))
    return out


def iso(d: int) -> str:
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def load_events() -> dict:
    files = sorted((ROOT / "data/r2/tdx").glob("xdxr_fullmarket_*.json.gz"))
    if not files:
        return {}
    with gzip.open(files[-1], "rt", encoding="utf8") as f:
        raw = json.load(f)
    table = raw.get("data", raw)
    ev = {}
    for code, rec in table.items():
        events = rec.get("events", rec) if isinstance(rec, dict) else rec
        c6 = code[-6:]
        ev[c6] = events
    return ev


def univ_codes() -> list:
    codes = []
    for mk in ("sh", "sz", "bj"):
        for p in (DATA / mk / "lday").glob(f"{mk}*.day"):
            c6 = p.stem[2:]
            if mk == "sh" and c6[:2] not in ("60", "68", "90"):
                continue          # 排除上证指数/基金等
            if mk == "sz" and c6[:2] not in ("00", "30", "20"):
                continue
            if mk == "bj" and c6[0] not in ("4", "8", "9"):
                continue
            codes.append(p.stem)
    return sorted(codes)


def realtime_prices(codes: list, batch: int = 80) -> dict:
    """协议 snapshot-batch 取今日实时价 (price/last_close)。"""
    out = {}
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp = tf.name
        cmd = [sys.executable, str(CLI), "snapshot-batch", *chunk,
               "--bootstrap", str(BOOTSTRAP), "--out", tmp]
        try:
            subprocess.run(cmd, cwd=str(CLI.parents[1]), capture_output=True, timeout=60)
            with open(tmp, encoding="utf8") as f:
                d = json.load(f)
            mkmap = {0: "sz", 1: "sh", 2: "bj"}
            for r in d.get("rows", []):
                c6 = r.get("code")
                if c6 and r.get("price"):
                    out[c6] = r
                    out[mkmap.get(r.get("market"), "sh") + c6] = r
        except Exception:
            pass
        finally:
            os.path.exists(tmp) and os.unlink(tmp)
    return out


def pct(a, b):
    return None if not b else (a / b - 1) * 100


def week_key(d: int) -> str:
    import datetime as dt
    y, m, dd = d // 10000, d // 100 % 100, d % 100
    return dt.date(y, m, dd).strftime("%G-W%V")


def analyze(code: str, bars: list, events: list, rt: dict | None) -> dict | None:
    if len(bars) < 30:
        return None
    dates = [iso(b[0]) for b in bars]
    closes = [b[4] for b in bars]
    vols = [b[6] for b in bars]

    asof = dates[-1]
    adj = adjust(list(zip(dates, closes)), events, asof)
    ac = [p for _, p in adj]
    if len(ac) != len(closes):
        return None

    def back(n):
        return ac[-1 - n] if len(ac) > n else None

    rec = {
        "code": code, "date": asof, "close": closes[-1], "adj_close": round(ac[-1], 4),
        "chg1d": pct(ac[-1], back(1)), "chg5d": pct(ac[-1], back(5)),
        "chg20d": pct(ac[-1], back(20)), "chg60d": pct(ac[-1], back(60)),
    }
    # 年初至今
    ytd = [p for d, p in adj if d >= asof[:4] + "-01-01"]
    rec["chg_ytd"] = pct(ac[-1], ytd[0]) if ytd else None
    # 量能
    v5 = sum(vols[-5:]) / 5
    v20 = sum(vols[-20:]) / 20
    rec["vol_ratio_5_20"] = v5 / v20 if v20 else None
    rec["vol_vs_v5"] = vols[-1] / v5 if v5 else None
    # 均线位置 (复权)
    for w in (5, 20, 60):
        if len(ac) >= w:
            ma = sum(ac[-w:]) / w
            rec[f"vs_ma{w}"] = pct(ac[-1], ma)
            rec[f"ma{w}"] = round(ma, 4)
    # 距 60 日高点回撤
    hi = max(ac[-60:]) if len(ac) >= 60 else max(ac)
    rec["dd_from_60d_high"] = pct(ac[-1], hi)
    # 周线双阳 (上周阳 + 本周阳)
    wk = {}
    for d, p, c in zip(dates, ac, ac):
        wk.setdefault(week_key(int(d[:4] + d[5:7] + d[8:])), []).append((d, p, c))
    ks = sorted(wk)
    if len(ks) >= 3:
        def wo(k):
            v = sorted(wk[k])
            prev = wk[ks[ks.index(k) - 1]][-1][2] if ks.index(k) else None
            return v[-1][2] - (prev if prev else v[0][1])
        rec["week_bull"] = wo(ks[-1]) > 0 and wo(ks[-2]) > 0
    # 实时叠加
    if rt:
        r = rt.get(code) or rt.get(code[2:])
        if r and r.get("price"):
            rec["rt_price"] = r["price"]
            rec["rt_chg1d"] = pct(r["price"], r.get("last_close") or closes[-1])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--codes", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--bars", type=int, default=260)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--sort", default="chg5d")
    ap.add_argument("--realtime", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    if a.codes:
        codes = [c.strip() for c in a.codes.split(",") if c.strip()]
    elif a.file:
        codes = [l.split()[0] for l in open(a.file) if l.strip()]
    else:
        codes = univ_codes()
    codes = [c if len(c) > 6 else ("sh" if c[0] in "65" else "sz" if c[0] in "03" else "bj") + c for c in codes]
    codes = [c.replace(".day", "") for c in codes]

    events = load_events()
    rt = realtime_prices(codes) if a.realtime else None

    rows, skipped = [], 0
    for code in codes:
        p = DATA / code[:2] / "lday" / f"{code}.day"
        if not p.exists():
            skipped += 1
            continue
        bars = read_day(p, a.bars)
        r = analyze(code, bars, events.get(code[2:], []), rt)
        if r:
            rows.append(r)
        else:
            skipped += 1

    if rt:
        rtrows = [r for r in rows if r.get("rt_chg1d") is not None]
        dist_rt = {
            "n": len(rtrows),
            "up": len([r for r in rtrows if r["rt_chg1d"] > 0]),
            "down": len([r for r in rtrows if r["rt_chg1d"] < 0]),
            "median": sorted(r["rt_chg1d"] for r in rtrows)[len(rtrows) // 2],
            "gt5": len([r for r in rtrows if r["rt_chg1d"] > 5]),
            "lt_m5": len([r for r in rtrows if r["rt_chg1d"] < -5]),
        }
        globals()["dist_rt"] = dist_rt
    rows.sort(key=lambda r: (r.get(a.sort) is None, -(r.get(a.sort) or 0)))
    last_date = max((r["date"] for r in rows), default="?")

    # 分布统计
    ups = [r for r in rows if (r.get("chg1d") or 0) > 0]
    dns = [r for r in rows if (r.get("chg1d") or 0) < 0]
    def med(v):
        v = sorted(x for x in v if x is not None)
        return v[len(v) // 2] if v else None
    dist = {
        "universe": len(codes), "analyzed": len(rows), "skipped": skipped,
        "last_date": last_date,
        "up": len(ups), "down": len(dns), "flat": len(rows) - len(ups) - len(dns),
        "median_chg1d": med([r["chg1d"] for r in rows]),
        "median_chg5d": med([r["chg5d"] for r in rows]),
        "median_chg20d": med([r["chg20d"] for r in rows]),
        "gt5_1d": len([r for r in rows if (r["chg1d"] or 0) > 5]),
        "lt_m5_1d": len([r for r in rows if (r["chg1d"] or 0) < -5]),
        "week_bull": len([r for r in rows if r.get("week_bull")]),
        "above_ma20": len([r for r in rows if (r.get("vs_ma20") or -99) > 0]),
    }

    out = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
           "bars": a.bars, "realtime": bool(rt), "dist": dist, "rows": rows}
    outpath = Path(a.out) if a.out else ROOT / "data/r2/tdx" / f"rise_fall_{last_date.replace('-','')}.json"
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text(json.dumps(out, ensure_ascii=False), encoding="utf8")

    # 终端输出
    print(f"# TDX 涨跌分析 — 数据截至 {last_date}  (样本 {len(rows)}, 跳过 {skipped})")
    print(f"涨 {dist['up']} / 跌 {dist['down']} / 平 {dist['flat']}  |  "
          f"中位: 1日 {dist['median_chg1d']:.2f}%  5日 {dist['median_chg5d']:.2f}%  20日 {dist['median_chg20d']:.2f}%")
    if rt and globals().get("dist_rt"):
        d = dist_rt
        print(f"【今日实时】样本 {d['n']} | 涨 {d['up']} / 跌 {d['down']} | 中位 {d['median']:.2f}% | "
              f"涨超5% {d['gt5']} / 跌超5% {d['lt_m5']}")
    print(f"涨超5% {dist['gt5_1d']} 只 / 跌超5% {dist['lt_m5_1d']} 只 | "
          f"站上MA20 {dist['above_ma20']} 只 | 周线双阳 {dist['week_bull']} 只\n")
    rtc = " 实时% |" if rt else ""
    hdr = f"| {'代码':<8} | 收盘 | 1日% | 5日% | 20日% | 60日% | 年初% | 量比5/20 | vsMA20 | 距60高 | 双阳 |{rtc}"
    print(hdr)
    print("|" + "-" * 10 + "|" + "|".join(["-" * 8] * (10 + (1 if rt else 0))) + "|")
    for r in rows[:a.top]:
        f = lambda k, w=6: (f"{r[k]:.{1}f}".rjust(w) if r.get(k) is not None else "–".rjust(w))
        extra = f" {f('rt_chg1d')} |" if rt else ""
        print(f"| {r['code']:<8} | {r['close']:>5.2f} | {f('chg1d')} | {f('chg5d')} | {f('chg20d')} | "
              f"{f('chg60d')} | {f('chg_ytd')} | {f('vol_ratio_5_20',5)} | {f('vs_ma20')} | "
              f"{f('dd_from_60d_high',6)} | {'✓' if r.get('week_bull') else ' '} |{extra}")
    print(f"\n全量 → {outpath}")


if __name__ == "__main__":
    main()