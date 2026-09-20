#!/usr/bin/env python3
"""adjustment_v1 候选源采集（腾讯版）：web.ifzq.gtimg.cn fqkline unadj/hfq。

与 baostock 版同门禁：冻结 universe（同一清单/SHA256）、单股原子落盘、
断点哈希恢复、有限重试+指数退避+抖动、轻校验。输出：data/adjustment_tx/。

腾讯 API 要点（2026-09-20 实测）：
- GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
  ?param={sym},day,{start},{end},{lmt},{fq}   fq: ""=unadj / "hfq"
- lmt 上限 640，超出返回 data=[]；返回窗口【末端】lmt 根 → 分页回退 end
- data.{sym}.day / .hfqday 行 = [date, open, close, high, low, volume(手)]
  （注意 open,close,high,low 顺序；无成交额）
- 东财/新浪对本机 IP 断连，腾讯可用；baostock 深度限流中（并行冷却）
"""
import gzip, hashlib, json, random, socket, sys, time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path("/root/project/workspace/stock-selector-v2/data/adjustment_tx")
RAW_DIR = OUT / "per_stock"
START_DATE, END_DATE = "2021-01-01", "2026-09-19"
PAGE = 640
FAMILY_STOP = 20
RETRY_MAX = 5
BASE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="

socket.setdefaulttimeout(30)


def universe() -> list[str]:
    codes = []
    for mkt, prefixes in (("sh", ("6",)), ("sz", ("0", "3"))):
        for f in Path(f"/root/tdx_data/vipdoc/{mkt}/lday").glob("*.day"):
            c = f.stem[2:]
            if c.startswith(("399", "880", "800")):
                continue          # 深市指数/板块指数：非股票（erratum 2026-09-20）
            if c.startswith(prefixes):
                codes.append(f"{mkt}.{c}")
    return sorted(set(codes))


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(sym: str, end: str, fq: str) -> list[list[str]]:
    url = f"{BASE}{sym},day,{START_DATE},{end},{PAGE},{fq}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    if r.get("code") != 0:
        raise RuntimeError(f"tx code={r.get('code')}")
    d = r["data"][sym]
    key = "hfqday" if fq == "hfq" else "day"
    if key not in d:
        if fq == "hfq" and "day" in d:
            key = "day"        # 无除权历史(新股等): 腾讯回退 day, hfq≡unadj → F≡1
        else:
            return []
    return [[str(x[0]), str(x[1]), str(x[2]), str(x[3]), str(x[4]), str(x[5])]
            for x in d[key]]


def fetch_series(sym: str, fq: str) -> list[list[str]]:
    """end 回退分页拉全窗口。"""
    out: list[list[str]] = []
    end = END_DATE
    while True:
        seg = _get(sym, end, fq)
        if not seg:
            if not out:
                raise RuntimeError("empty series")
            break
        out = seg + out if out and out[0][0] > seg[-1][0] else out + seg
        if seg[0][0] <= START_DATE or len(seg) < PAGE:
            break
        d0 = datetime.strptime(seg[0][0], "%Y-%m-%d") - timedelta(days=1)
        end = d0.strftime("%Y-%m-%d")
    # 去重排序（分页边界保险）
    seen = {}
    for r in out:
        seen[r[0]] = r
    return [seen[d] for d in sorted(seen)]


def validate(rows: list[list[str]]) -> None:
    assert len(rows) > 0, "empty series"
    dates = [r[0] for r in rows]
    assert len(set(dates)) == len(dates), "duplicate dates"
    assert dates == sorted(dates), "dates not ascending"
    for r in rows:
        c = float(r[2]) if r[2] else 0.0   # 腾讯行: date,o,c,h,l,v → close=idx2
        assert c > 0, f"close<=0: {r[0]} {r[2]}"


def fetch_stock(code: str) -> dict:
    sym = code.replace(".", "")
    unadj, hfq = fetch_series(sym, ""), fetch_series(sym, "hfq")
    validate(unadj)
    validate(hfq)
    assert [r[0] for r in unadj] == [r[0] for r in hfq], "date misalignment"
    return {"code": code,
            "params": {"source": "tencent-fqkline", "start": START_DATE,
                       "end": END_DATE, "freq": "d", "volume_unit": "hand",
                       "row_schema": "date,open,close,high,low,volume"},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "n_rows": len(unadj),
            "first_date": unadj[0][0], "last_date": unadj[-1][0],
            "unadj": unadj, "hfq": hfq}


def write_atomic(code: str, payload: dict) -> str:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RAW_DIR / f"{code}.tmp"
    fin = RAW_DIR / f"{code}.json.gz"
    with open(tmp, "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(payload, ensure_ascii=False,
                                separators=(",", ":")).encode())
    if tmp.stat().st_size == 0:
        tmp.unlink()
        raise RuntimeError("empty write")
    sha = sha256_file(tmp)
    tmp.rename(fin)
    return sha


def main() -> int:
    codes = universe()
    manifest = OUT / "fetch_manifest.json"
    state = {"universe_sha256": None, "stocks": {}}
    if manifest.exists():
        state = json.loads(manifest.read_text())
    blob = "\n".join(codes).encode()
    uni_sha = hashlib.sha256(blob).hexdigest()
    old_full = state.get("universe_sha256") or ""
    if old_full.startswith("1b2ac933635a"):
        # 旧全量清单(含指数) → 股票子集迁移：丢弃指数码记录，保留全部股票进度
        stock_set = set(codes)
        state["stocks"] = {c: v for c, v in state["stocks"].items() if c in stock_set}
        state["universe_sha256"] = uni_sha
    elif state.get("universe_sha256") in (None, uni_sha):
        state["universe_sha256"] = uni_sha
    else:
        print(f"[FATAL] universe changed: {state['universe_sha256']} != {uni_sha}")
        return 2
    done = {c for c, v in state["stocks"].items() if v.get("status") == "ok"}
    todo = [c for c in codes if c not in done]
    print(f"universe={len(codes)} sha={uni_sha[:12]} done={len(done)} todo={len(todo)}",
          flush=True)

    fam = 0
    t0 = time.time()
    for i, code in enumerate(todo):
        fp = RAW_DIR / f"{code}.json.gz"
        if fp.exists() and code in state["stocks"]:
            if sha256_file(fp) == state["stocks"][code]["sha256"]:
                continue
            print(f"[WARN] hash mismatch {code}, refetch", flush=True)
            fp.unlink()
        ok = False
        for attempt in range(RETRY_MAX):
            try:
                payload = fetch_stock(code)
                sha = write_atomic(code, payload)
                state["stocks"][code] = {"status": "ok", "sha256": sha,
                                         "n_rows": payload["n_rows"],
                                         "first": payload["first_date"],
                                         "last": payload["last_date"]}
                ok = True
                break
            except AssertionError as e:
                print(f"[FAIL-validate] {code}: {e} -- permanent, no retry",
                      flush=True)
                state["stocks"][code] = {"status": "validate_fail", "err": str(e)}
                break
            except Exception as e:
                wait = min(90, 3 ** attempt * 2) + random.uniform(0, 2)
                print(f"[retry {attempt}] {code}: {type(e).__name__} {e}; sleep {wait:.1f}s",
                      flush=True)
                time.sleep(wait)
        if not ok and state["stocks"].get(code, {}).get("status") != "validate_fail":
            state["stocks"][code] = {"status": "fetch_fail"}
        fam = 0 if state["stocks"][code]["status"] == "ok" else fam + 1
        if fam >= FAMILY_STOP:
            print(f"[FATAL] {FAMILY_STOP} consecutive failures -- stop", flush=True)
            break
        if i % 25 == 0:
            tmp_m = manifest.with_suffix(".tmp")
            tmp_m.write_text(json.dumps(state, ensure_ascii=False))
            tmp_m.rename(manifest)
            el = time.time() - t0
            print(f"[progress] {i + 1}/{len(todo)} elapsed {el / 60:.1f}m "
                  f"eta {(el / max(i + 1, 1) * (len(todo) - i - 1)) / 60:.1f}m",
                  flush=True)
        time.sleep(0.45 + random.uniform(0, 0.25))     # 礼貌限速+抖动
    tmp_m = manifest.with_suffix(".tmp")
    tmp_m.write_text(json.dumps(state, ensure_ascii=False))
    tmp_m.rename(manifest)
    n_ok = sum(1 for v in state["stocks"].values() if v.get("status") == "ok")
    print(f"[done] ok={n_ok}/{len(codes)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
