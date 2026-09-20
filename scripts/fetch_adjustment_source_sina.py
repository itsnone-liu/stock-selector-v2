#!/usr/bin/env python3
"""adjustment_v1 第二独立源：新浪 hfq.js 事件驱动累积复权因子表。

用途：与 baostock 价格反推 F（hfq/raw）构成规范 §5.2 交叉验证对——
①事件日集合等价检验；②事件日因子比值恒定性（std<1e-4）。
语义（2026-09-20 实测 sh.600000 验证）：f = 该除权日之后的累积后复权
因子（最新事件最大，历史事件→1.0；表首 1900-01-01 f=1.0 为哨兵）。
腾讯 hfqday 已判路径污染（corr(ΔF,Δraw)=-0.92），不用于 F 构造。

GET https://finance.sina.com.cn/realstock/company/{sh600000|sz000001}/hfq.js
GBK 编码，需 Referer。输出：data/adjustment_sina/factors/{code}.json.gz
"""
import gzip, hashlib, json, random, socket, sys, time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("/root/project/workspace/stock-selector-v2/data/adjustment_sina")
RAW_DIR = OUT / "factors"
FAMILY_STOP = 20
RETRY_MAX = 5

socket.setdefaulttimeout(30)


def universe() -> list[str]:
    codes = []
    for mkt, prefixes in (("sh", ("6",)), ("sz", ("0", "3"))):
        for f in Path(f"/root/tdx_data/vipdoc/{mkt}/lday").glob("*.day"):
            c = f.stem[2:]
            if c.startswith(prefixes):
                codes.append(f"{mkt}.{c}")
    return sorted(set(codes))


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_factors(code: str) -> dict:
    sym = code.replace(".", "")
    url = f"https://finance.sina.com.cn/realstock/company/{sym}/hfq.js"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.sina.com.cn/",
    })
    raw = urllib.request.urlopen(req, timeout=30).read().decode("gbk", errors="ignore")
    i = raw.find("{")
    # raw_decode 在匹配的 '}' 处停止，忽略尾部水印注释等 JS 附加内容
    obj, _ = json.JSONDecoder().raw_decode(raw[i:])
    ev = [(x["d"], float(x["f"])) for x in obj.get("data", [])]
    ev = [(d, f) for d, f in ev if d >= "1990-01-01"]        # 去 1900 哨兵
    # 语义校验：因子>0；若按时间升序排则因子非降（累积后复权）
    asc = sorted(ev)
    fvals = [f for _, f in asc]
    assert all(f > 0 for f in fvals), "factor<=0"
    assert fvals == sorted(fvals), "cumulative factor not non-decreasing"
    return {"code": code,
            "params": {"source": "sina-hfq.js", "semantics":
                       "cumulative hfq factor effective ON/AFTER event date"},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "n_events": len(ev),
            "events": [{"date": d, "factor": f} for d, f in ev]}


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
    if state.get("universe_sha256") in (None, uni_sha):
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
            fp.unlink()
        ok = False
        for attempt in range(RETRY_MAX):
            try:
                payload = fetch_factors(code)
                sha = write_atomic(code, payload)
                state["stocks"][code] = {"status": "ok", "sha256": sha,
                                         "n_events": payload["n_events"]}
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
        if i % 50 == 0:
            tmp_m = manifest.with_suffix(".tmp")
            tmp_m.write_text(json.dumps(state, ensure_ascii=False))
            tmp_m.rename(manifest)
            el = time.time() - t0
            print(f"[progress] {i + 1}/{len(todo)} elapsed {el / 60:.1f}m "
                  f"eta {(el / max(i + 1, 1) * (len(todo) - i - 1)) / 60:.1f}m",
                  flush=True)
        time.sleep(0.4 + random.uniform(0, 0.2))
    tmp_m = manifest.with_suffix(".tmp")
    tmp_m.write_text(json.dumps(state, ensure_ascii=False))
    tmp_m.rename(manifest)
    n_ok = sum(1 for v in state["stocks"].values() if v.get("status") == "ok")
    print(f"[done] ok={n_ok}/{len(codes)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
