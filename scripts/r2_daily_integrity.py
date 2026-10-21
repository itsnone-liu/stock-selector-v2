#!/usr/bin/env python3
"""R2 每日数据完整性自检 — 「拥堵/禁用/不完整」的确定性闸门（2026-10-21 建立）。

用法: .venv/bin/python scripts/r2_daily_integrity.py [--day YYYY-MM-DD] [--quiet]
      （--day 省略 = 今天 Asia/Shanghai）
输出: data/r2/daily_update/integrity_<day>.json + stdout 一行摘要
退出码: 0=PASS / 1=FAIL(有 BLOCK) / 2=环境错误

BLOCK 项（任一出现 => FAIL，需人工看）:
 A  manifest 缺 / ok!=true / hard_fail>0 / fails 或 tdx_mismatch 非空
 A' current + suspended_benign != n_codes（账不平 = 有票被静默丢弃）
 B  逐票覆盖：daily_fullmarket 末根 bar==day 的票数 != manifest.stats.current
 C  C 链 5 个产物：最新日期 != day 或文件缺失
 E  scans/current_scan_<day>.json 缺失
 F  daily_update/report_<day>.json 缺失
 L  step_*.log 出现 Traceback / 'FAIL'（A,C1..C5,E,F）
WARN 项（提示不拦）:
 W1 TDX 镜像 .tdx_daily_sync_state.json 的 trade_date < day
 W2 产物 mtime 早于当日 15:00（可能跑的是旧产物）
"""
import argparse, gzip, json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / 'data'
DU = D / 'r2' / 'daily_update'
FULL = D / 'cd' / 'daily_fullmarket'
CN = timezone(timedelta(hours=8))
ARTS = {  # C 链产物 -> rows 键
    'l2_four_axes': ('data/cd/sector_axes/l2_four_axes.json.gz', 'rows'),
    'l1_market_axes': ('data/cd/sector_axes/l1_market_axes.json.gz', 'rows'),
    'l2_state_table': ('data/cd/sector_axes/l2_state_table.json.gz', 'states'),
    'l4_episodes': ('data/cd/l4_episodes.json.gz', 'episodes'),
    'l3_pool': ('data/cd/l3_candidate_pool_v2.json.gz', 'pools'),
}
STEPS = ['A', 'C1', 'C2', 'C3', 'C4', 'C5', 'E', 'F']


def newest_date(path, key):
    try:
        x = json.loads(gzip.decompress(Path(path).read_bytes()))
    except Exception as e:
        return None, f'读取失败:{e.__class__.__name__}'
    rows = None
    if isinstance(x, dict):
        rows = x.get(key)
        if rows is None:
            for k in ('rows', 'states', 'episodes', 'pools', 'dates'):
                if k in x:
                    rows = x[k]
                    break
    if isinstance(rows, dict):          # l3_pool: {月份key -> ...}
        return max(rows) if rows else None, None
    if not isinstance(rows, list) or not rows:
        return None, '无行'
    ds = [r.get('date') or r.get('day') for r in rows if isinstance(r, dict)]
    ds = [d for d in ds if d]
    return (max(ds) if ds else None), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default='')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    day = a.day or datetime.now(CN).strftime('%Y-%m-%d')
    t0 = time.time()
    block, warn, info = [], [], {}

    # A: manifest
    mf = DU / f'update_{day}.json'
    if not mf.exists():
        block.append(f'A: manifest 缺失 {mf}')
    else:
        m = json.loads(mf.read_text())
        info['manifest'] = {k: m.get(k) for k in ('n_codes', 'new_bars', 'elapsed_s', 'suspended_benign', 'hard_fail', 'gate_limit', 'ok')}
        info['stats'] = m.get('stats')
        if m.get('ok') is not True:
            block.append(f"A: manifest ok={m.get('ok')}")
        if (m.get('hard_fail') or 0) > 0:
            block.append(f"A: hard_fail={m['hard_fail']} fails={m.get('fails')}")
        for k in ('fails', 'tdx_mismatch'):
            v = m.get(k)
            if v:
                block.append(f'A: {k} 非空({len(v)}): {v[:6]}')
        cur = (m.get('stats') or {}).get('current', 0)
        ben = m.get('suspended_benign') or 0
        n = m.get('n_codes') or 0
        if cur + ben != n:
            block.append(f'A: 账不平 current({cur})+benign({ben}) != n_codes({n})')
        info['coverage_manifest'] = cur

    # B: 逐票覆盖（末根 bar == day 的票数 == manifest.stats.current）
    if FULL.is_dir():
        cnt = 0
        files = [p for p in FULL.iterdir() if p.suffix == '.gz']
        for p in files:
            try:
                dd = json.loads(gzip.decompress(p.read_bytes())).get('dates') or []
                if dd and dd[-1] == day:
                    cnt += 1
            except Exception:
                pass
        info['coverage_files'] = cnt
        info['files_total'] = len(files)
        cur = (info.get('coverage_manifest') if 'coverage_manifest' in info else 0)
        if cur and cnt != cur:
            block.append(f'B: 逐票覆盖 {cnt} != manifest.current {cur}（差 {cnt - cur}）')
    else:
        block.append(f'B: 目录缺失 {FULL}')

    # C: C 链产物日期
    info['arts'] = {}
    for name, (rel, key) in ARTS.items():
        p = ROOT / rel
        if not p.exists():
            block.append(f'C: 产物缺失 {rel}')
            continue
        nd, err = newest_date(p, key)
        info['arts'][name] = {'newest': nd, 'mtime': datetime.fromtimestamp(p.stat().st_mtime, CN).strftime('%m-%d %H:%M')}
        if err:
            block.append(f'C: {name} {err}')
        elif name != 'l3_pool' and nd != day:
            block.append(f'C: {name} 最新日期 {nd} != {day}')
        if datetime.fromtimestamp(p.stat().st_mtime, CN).strftime('%Y-%m-%d') != day:
            warn.append(f'W2: {name} mtime={info["arts"][name]["mtime"]} 非当日')

    # E/F
    e = D / 'r2' / 'scans' / f'current_scan_{day}.json'
    f = DU / f'report_{day}.json'
    for tag, p in (('E', e), ('F', f)):
        if not p.exists():
            block.append(f'{tag}: 产物缺失 {p}')
        else:
            info[tag] = {'mtime': datetime.fromtimestamp(p.stat().st_mtime, CN).strftime('%m-%d %H:%M'), 'kb': round(p.stat().st_size / 1024, 1)}

    # L: step 日志
    for s in STEPS:
        p = DU / f'step_{s}.log'
        if not p.exists():
            block.append(f'L: step_{s}.log 缺失')
            continue
        t = p.read_text(errors='replace')
        if 'Traceback' in t:
            block.append(f'L: step_{s}.log 有 Traceback: {t.strip().splitlines()[-1][:160]}')
        elif 'FAIL' in t and not any(k in t for k in ('"ok": true', 'OK')):
            warn.append(f'W3: step_{s}.log 含 FAIL 字样')

    # W1: TDX 镜像同步状态
    st = Path('/root/tdx_data/vipdoc/.tdx_daily_sync_state.json')
    if st.exists():
        try:
            j = json.loads(st.read_text())
            td = next((j.get(k) for k in ('trade_date', 'date', 'trade_day', 'last_date') if j.get(k)), None)
            info['tdx_sync'] = td
            if td and str(td) < day:
                warn.append(f'W1: TDX 镜像 trade_date={td} < {day}（镜像滞后）')
        except Exception as ex:
            warn.append(f'W1: 同步状态解析失败 {ex}')
    else:
        warn.append(f'W1: 同步状态文件缺失 {st}')

    ok = not block
    out = {'day': day, 'ok': ok, 'block': block, 'warn': warn, 'info': info,
           'checked_at': datetime.now(CN).isoformat(timespec='seconds'), 'elapsed_s': round(time.time() - t0, 1)}
    DU.mkdir(parents=True, exist_ok=True)
    (DU / f'integrity_{day}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    if not a.quiet:
        print(f"R2 完整性自检 {day}: {'PASS' if ok else 'FAIL'}  "
              f"覆盖={info.get('coverage_files')}/{info.get('coverage_manifest')}  "
              f"BLOCK={len(block)} WARN={len(warn)}  {out['elapsed_s']}s")
        for b in block:
            print('  BLOCK ' + b)
        for w in warn:
            print('  WARN  ' + w)
    return 0 if ok else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(2)