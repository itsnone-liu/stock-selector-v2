#!/usr/bin/env python3
"""CF-1A sampling scheduler — 按自然时点自动执行五时点采样 (后台常驻)

时点计划 (2026-10-16):
  08:30  morning_0830   两融 T+1 定案 + ETF same-day 复核 (T=20261016)
  11:00  intraday_1100  ETF 盘中可查性
  14:30  tail_1430      ETF 尾盘可查性
  15:30  post_1530      收盘后
  20:05  evening        T=20261016 采样 + T=20261015 修订复查(vs 基线)
Usage: nohup python3 scripts/cf/sampling_scheduler.py > /tmp/cf_sampler.log 2>&1 &
"""
import datetime as dt
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV = dict(os.environ, PYTHONPATH='/tmp/aksy')
# 解释器钉死：/tmp/aksy 的 vendored 依赖只编译了 cpython-310，PATH 里的 python3 是
# Hermes venv(3.11) -> import numpy 必崩。与 daily_pipelines.sh 同一铁律，禁止改回裸 python3。
PY = '/usr/bin/python3'


def _python_ok():
    try:
        r = subprocess.run([PY, '-c',
                            'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,10) else 1)'],
                           capture_output=True, text=True, timeout=60)
    except Exception as e:
        log(f"interpreter check failed to run: {e}")
        return False
    v = subprocess.run([PY, '-c', 'import sys;print(".".join(map(str,sys.version_info[:3])))'],
                       capture_output=True, text=True).stdout.strip()
    log(f"interpreter {PY} = python {v}")
    if r.returncode != 0:
        log(f"FATAL: {PY} 不是 3.10，vendored /tmp/aksy 需要 cpython-310")
        return False
    return True

SCHEDULE = [
    ('2026-10-16 08:30', [('20261016', 'morning_0830')]),
    ('2026-10-16 11:00', [('20261016', 'intraday_1100')]),
    ('2026-10-16 14:30', [('20261016', 'tail_1430')]),
    ('2026-10-16 15:30', [('20261016', 'post_1530')]),
    ('2026-10-16 20:05', [('20261016', 'evening'), ('20261015', 'evening_revcheck_T15')]),
]


def log(msg):
    print(f"[{dt.datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def run_probe(trade_date, label):
    cmd = [PY, os.path.join(ROOT, 'scripts', 'cf', 'release_time_probe.py'),
           '--trade-date', trade_date, '--label', label]
    log(f"probe start T={trade_date} label={label}")
    try:
        r = subprocess.run(cmd, env=ENV, capture_output=True, text=True, timeout=600)
        ok = 'saved:' in r.stdout
        log(f"probe done ok={ok} rc={r.returncode}")
    except Exception as e:
        log(f"probe ERR {e}")


def main():
    if not _python_ok():
        sys.exit(2)
    log('scheduler up; plan=' + '; '.join(t for t, _ in SCHEDULE))
    for when, probes in SCHEDULE:
        target = dt.datetime.strptime(when, '%Y-%m-%d %H:%M')
        now = dt.datetime.now()
        if now >= target + dt.timedelta(minutes=10):
            log(f"skip past slot {when}")
            continue
        if now < target:
            wait = (target - now).total_seconds()
            log(f"waiting {wait/60:.0f}min for {when}")
            time.sleep(min(wait, 3300))  # 分段 sleep 便于观察存活
            while dt.datetime.now() < target:
                time.sleep(5)
        for td, label in probes:
            run_probe(td, label)
    log('ALL SLOTS DONE — scheduler exit')


if __name__ == '__main__':
    main()
