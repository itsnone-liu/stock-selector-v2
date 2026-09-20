#!/usr/bin/env python3
"""adjustment_v1 候选源采集：BaoStock unadj/hfq 全量拉取（断点续跑、原子落盘）。

定位：候选源采集与实证（非 adjusted_verified）。门禁依
docs/reports/ADJUSTMENT_V1_SOURCE_AUDIT.md 与用户放行范围：
- 清单冻结（SHA256）；每股 unadj/hfq 分股票保存 + 请求元数据 + 文件 SHA256
- 单股原子落盘（tmp→校验→rename）；断点恢复验哈希
- 有限重试 + 指数退避 + 随机抖动；登录失败/连续失败 → 停止不无限重试
- 轻校验：行数>0、日期升序无重复、close>0；深度 fail-fast 审计由独立脚本做
"""
import gzip, hashlib, json, random, signal, socket, sys, time
from datetime import datetime, timezone
from pathlib import Path

import baostock as bs

# 内核级 socket 超时（对 baostock 新建连接生效）：服务端挂起时 send/recv
# 60s 后抛 socket.timeout，不依赖 SIGALRM 是否能打断 C 层阻塞。
socket.setdefaulttimeout(60)


class FetchTimeout(Exception):
    """baostock 服务端挂起（连接 ESTAB 但不回包），watchdog 触发。"""


def _on_alarm(_sig, _frm):
    raise FetchTimeout()


def with_timeout(fn, seconds=90):
    """主线程 SIGALRM watchdog：单请求限时，超时抛 FetchTimeout。"""
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)


def relogin():
    """挂死后重建会话（logout 也可能挂，双保险限时）。"""
    try:
        with_timeout(bs.logout, 10)
    except Exception:
        pass
    for attempt in range(3):
        try:
            lg = with_timeout(bs.login, 15)
            if lg.error_code == '0':
                return True
        except Exception:
            pass
        time.sleep(3 + 2 ** attempt)
    return False

OUT = Path("/root/project/workspace/stock-selector-v2/data/adjustment_baostock")
RAW_DIR = OUT / "per_stock"
START_DATE, END_DATE = "2021-01-01", "2026-09-19"
FAMILY_STOP = 20          # 连续失败 N 股 → 停
RETRY_MAX = 4
FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg"


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


def fetch_series(code: str, flag: str) -> list[list[str]]:
    def _run():
        rs = bs.query_history_k_data_plus(code, FIELDS, start_date=START_DATE,
                                          end_date=END_DATE, frequency="d",
                                          adjustflag=flag)
        if rs.error_code != "0":
            raise RuntimeError(f"query err {rs.error_code}: {rs.error_msg}")
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        return rows
    return with_timeout(_run, 90)


def validate(rows: list[list[str]]) -> None:
    assert len(rows) > 0, "empty series"
    dates = [r[0] for r in rows]
    assert len(set(dates)) == len(dates), "duplicate dates"
    assert dates == sorted(dates), "dates not ascending"
    for r in rows:
        c = float(r[4]) if r[4] else 0.0
        assert c > 0, f"close<=0: {r[0]} {r[4]}"


def fetch_stock(code: str) -> dict:
    unadj, hfq = fetch_series(code, "3"), fetch_series(code, "1")
    validate(unadj)
    validate(hfq)
    assert [r[0] for r in unadj] == [r[0] for r in hfq], "date misalignment"
    return {"code": code, "params": {"start": START_DATE, "end": END_DATE,
                                     "fields": FIELDS, "freq": "d"},
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
    tmp.rename(fin)          # 原子改名
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
    print(f"universe={len(codes)} sha={uni_sha[:12]} done={len(done)} todo={len(todo)}")

    lg = None
    for attempt in range(3):
        lg = bs.login()
        if lg.error_code == "0":
            break
        print(f"login retry {attempt}: {lg.error_msg}")
        time.sleep(5 + 2 ** attempt)
    if lg is None or lg.error_code != "0":
        print("[FATAL] login failed -- stop, no infinite retry")
        return 3

    fam = 0
    t0 = time.time()
    for i, code in enumerate(todo):
        fp = RAW_DIR / f"{code}.json.gz"
        if fp.exists() and code in state["stocks"]:      # 断点：验哈希
            try:
                if sha256_file(fp) == state["stocks"][code]["sha256"]:
                    continue
                print(f"[WARN] hash mismatch {code}, refetch")
                fp.unlink()
            except KeyError:
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
                print(f"[FAIL-validate] {code}: {e} -- permanent, no retry")
                state["stocks"][code] = {"status": "validate_fail", "err": str(e)}
                break
            except Exception as e:                        # 网络/接口：退避+抖动
                if isinstance(e, (FetchTimeout, TimeoutError, socket.timeout)):
                    print(f"[timeout] {code}: baostock hang, relogin...", flush=True)
                    if not relogin():
                        print("[FATAL] relogin failed 3x -- stop")
                        fam = FAMILY_STOP
                wait = min(60, 2 ** attempt * 2) + random.uniform(0, 1.5)
                print(f"[retry {attempt}] {code}: {type(e).__name__} {e}; sleep {wait:.1f}s", flush=True)
                time.sleep(wait)
        if not ok and state["stocks"].get(code, {}).get("status") != "validate_fail":
            state["stocks"][code] = {"status": "fetch_fail"}
        fam = 0 if state["stocks"][code]["status"] == "ok" else fam + 1
        if fam >= FAMILY_STOP:
            print(f"[FATAL] {FAMILY_STOP} consecutive failures -- stop (rate/format/auth?)")
            break
        if i % 25 == 0:
            tmp_m = manifest.with_suffix(".tmp")
            tmp_m.write_text(json.dumps(state, ensure_ascii=False))
            tmp_m.rename(manifest)
            el = time.time() - t0
            print(f"[progress] {i + 1}/{len(todo)} elapsed {el / 60:.1f}m "
                  f"eta {(el / max(i + 1, 1) * (len(todo) - i - 1)) / 60:.1f}m", flush=True)
        time.sleep(1.2)                                   # 礼貌限速（0.35s 触发服务端挂连接）
        if (i + 1) % 20 == 0:                              # 每 20 股主动换连接，清半死 socket
            try:
                relogin()
            except Exception:
                pass
    tmp_m = manifest.with_suffix(".tmp")
    tmp_m.write_text(json.dumps(state, ensure_ascii=False))
    tmp_m.rename(manifest)
    bs.logout()
    n_ok = sum(1 for v in state["stocks"].values() if v.get("status") == "ok")
    print(f"[done] ok={n_ok}/{len(codes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
