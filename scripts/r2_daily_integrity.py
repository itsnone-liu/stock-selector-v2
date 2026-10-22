#!/usr/bin/env python3
"""R2 每日数据完整性自检 — 「拥堵/禁用/不完整」的确定性闸门（2026-10-21 建立）。

用法: .venv/bin/python scripts/r2_daily_integrity.py [--day YYYY-MM-DD] [--quiet]
      （--day 省略 = 今天 Asia/Shanghai）
输出: data/r2/daily_update/integrity_<day>.json + stdout 一行摘要
退出码: 0=PASS / 1=FAIL(有 BLOCK) / 2=环境错误

BLOCK 项（任一出现 => FAIL，需人工看）:
 A  manifest 缺 / ok!=true / ok 与 hard_fail<=gate_limit 自相矛盾
 A1 sum(stats) != n_codes（账不平 = 有票被静默丢弃）
 A2 suspended_benign != stats['tdx_no_daily']（良性桶口径只认停牌/退市/未覆盖）
 A3 hard_fail != 非 OK 非良性桶之和（hard 计数口径）
 A4 stats / tdx_mismatch 出现「未登记」桶或原因（fail-closed：新口径须显式登记才放行）
 A5 真异常桶非空：overlap_missing / overlap_raw_mismatch / tdx_mismatch / fetch_fail /
    tdx_transport:* / tdx_err:*（口径上计入 hard，但 integrity 层不放过）
 B  逐票覆盖：daily_fullmarket 末根 bar==day 的票数 != 当日已写入桶之和（updated* + current）
 C  C 链 5 个产物：最新日期 != day 或文件缺失
 E  scans/current_scan_<day>.json 缺失
 F  daily_update/report_<day>.json 缺失
 L  step_*.log 出现 Traceback / 'FAIL'（A,C1..C5,E,F）
WARN 项（提示不拦）:
 W1 TDX 镜像 .tdx_daily_sync_state.json 的 trade_date < day
 W2 产物 mtime 早于当日 15:00（可能跑的是旧产物）
 W3 容忍桶（window_too_short / tdx_short_history）非空：计入 hard_fail 并由 gate ratio 容忍，
    本层只记数不拦（但 daily_price_update 的 ok 已含此判定，故与 A6 交叉核）

桶口径（2026-10-22 随 src/r2/daily_price_update.py 同步，勿改）:
 成功桶 = updated*（updated / updated_rawfallback / updated_seam / updated_rawfallback_seam）/ current
 良性桶 = tdx_no_daily（停牌/退市/未覆盖，及「当日无成交」的停牌占位根；不计入 hard_fail）
 容忍 hard 桶 = window_too_short / tdx_short_history（计入 hard_fail，由 max(20, 2%*票数) 容忍）
 真异常桶 = overlap_missing / overlap_raw_mismatch / tdx_mismatch / fetch_fail / tdx_transport:* / tdx_err:*
 生产者闸门 = ok ⇔ hard_fail <= gate_limit；本脚本以 manifest 为准，再叠加 A1–A5 交叉核
"""
import argparse, gzip, json, os, re, sys, time
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
STEPS = ['A', 'C1', 'C1A', 'C2', 'C3', 'C4', 'C5', 'E', 'F']
# A 步桶口径（随 src/r2/daily_price_update.py 同步，2026-10-22）
BENIGN = 'tdx_no_daily'                                 # 停牌/退市/未覆盖：良性，不计入 hard_fail
TOL_HARD = ('window_too_short', 'tdx_short_history')    # 计入 hard_fail，由 gate ratio 容忍
ANOM_HARD = ('overlap_missing', 'overlap_raw_mismatch',  # 真异常：计入 hard_fail 且本层不放过
             'tdx_mismatch', 'fetch_fail', 'tdx_transport', 'tdx_err')


def bucket_kind(k):
    """stats/manifest 的 status key 归类，未登记一律 'unknown'（fail-closed）。"""
    if k.split('_')[0] == 'updated' or k == 'current':
        return 'ok'                 # 当日已写入 / 已含当日 bar（计入 B 覆盖）
    if k == 'no_change':
        return 'ok_nocover'         # 无新 bar（末根 bar < day），不计入覆盖
    if k == BENIGN:
        return 'benign'
    if k in TOL_HARD:
        return 'tol_hard'
    if k.split(':')[0] in ANOM_HARD or k in ANOM_HARD:
        return 'anom_hard'
    return 'unknown'


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
    if not ds:      # l4_episodes 等用 start/end 区间表示；取 end 为最新
        ds = [r.get('end') or r.get('start') for r in rows if isinstance(r, dict)]
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

    # A: manifest（口径 = src/r2/daily_price_update.py，2026-10-22 同步）
    mf = DU / f'update_{day}.json'
    if not mf.exists():
        block.append(f'A: manifest 缺失 {mf}')
    else:
        m = json.loads(mf.read_text())
        info['manifest'] = {k: m.get(k) for k in ('n_codes', 'new_bars', 'elapsed_s', 'suspended_benign', 'hard_fail', 'gate_limit', 'ok')}
        info['stats'] = m.get('stats')
        stats = m.get('stats') or {}
        n = m.get('n_codes') or 0
        ben = m.get('suspended_benign') or 0
        hard = m.get('hard_fail') or 0
        limit = m.get('gate_limit')
        kind = {k: bucket_kind(k) for k in stats}
        tol = sum(v for k, v in stats.items() if kind[k] == 'tol_hard')
        anom = sum(v for k, v in stats.items() if kind[k] == 'anom_hard')
        unk = sorted(k for k in stats if kind[k] == 'unknown')
        # A1 账平：每票必须落进恰好一个桶（否则有票被静默丢弃）
        if sum(stats.values()) != n:
            block.append(f'A: 账不平 sum(stats)={sum(stats.values())} != n_codes={n}')
        # A2 良性桶：口径只认 tdx_no_daily
        if ben != stats.get(BENIGN, 0):
            block.append(f"A: suspended_benign({ben}) != stats['{BENIGN}']({stats.get(BENIGN, 0)})")
        # A3 hard_fail 口径：非 OK 非良性桶之和
        hard_stat = tol + anom + sum(stats.get(k, 0) for k in unk)
        if hard != hard_stat:
            block.append(f'A: hard_fail({hard}) != 非OK非良性桶之和({hard_stat}；容忍{tol}+异常{anom}+未登记{len(unk)}桶)')
        # A4 fail-closed：新桶/新原因必须先显式登记
        if unk:
            block.append(f'A: stats 出现未登记桶 {unk}（口径未登记，须人工确认后再放行）')
        bad_reason = sorted({str(e[1]) for e in (m.get('tdx_mismatch') or [])
                             if isinstance(e, (list, tuple)) and len(e) > 1 and bucket_kind(str(e[1])) == 'unknown'})
        if bad_reason:
            block.append(f'A: tdx_mismatch 出现未登记原因 {bad_reason[:6]}')
        # A5 真异常桶：本层不放过（口径上计入 hard，但需人工看）
        anom_keys = sorted(k for k in stats if kind[k] == 'anom_hard')
        if anom_keys:
            block.append(f'A: 真异常桶非空 {[(k, stats[k]) for k in anom_keys]}：共 {anom} 票')
        if m.get('fails') or m.get('tdx_mismatch'):
            warn.append(f"A: fails={len(m.get('fails') or [])} tdx_mismatch={len(m.get('tdx_mismatch') or [])}"
                        f"（明细见 update_{day}.json；其中容忍桶 {tol} 票）")
        # A6 manifest 自评闸门一致
        if m.get('ok') is not True:
            block.append(f"A: manifest ok={m.get('ok')}（hard_fail={hard} gate_limit={limit}）")
        elif limit is not None and hard > limit:
            block.append(f'A: manifest ok=true 但 hard_fail={hard} > gate_limit={limit}（自相矛盾）')
        if tol:
            warn.append(f'W3: 容忍桶 {tol} 票（window_too_short/tdx_short_history）计入 hard_fail 未超 gate_limit={limit}，不拦')
        info['coverage_manifest'] = sum(v for k, v in stats.items() if kind[k] == 'ok')
        info['hard_breakdown'] = {'tol_hard': tol, 'anom_hard': anom, 'unknown': {k: stats[k] for k in unk}}

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
            block.append(f'B: 逐票覆盖 {cnt} != 当日已写入桶(updated*+current) {cur}（差 {cnt - cur}）')
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
        elif re.search(r'^\[[A-Z0-9]+\]\s+FAIL\b', t, re.M) or 'rc=-' in t:
            # 只在「编排器式 FAIL 行」或负退出码(信号杀,如 rc=-9/-11)时报；
            # 不扫描裸 'FAIL' 字样 —— C5 的 STRUCTURAL_FAILURE 是正常分类标签（2026-10-21）
            block.append(f'L: step_{s}.log 报 FAIL 或被信号杀(stderr 为空时只剩这行线索)')

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