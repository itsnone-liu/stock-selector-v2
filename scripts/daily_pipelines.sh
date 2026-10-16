#!/bin/bash
# Daily pipelines for Hermes (run after 19:30 CST on trading days).
# A: R5 OOS-B shadow increment (TDX 052d 5m/daily -> shadow_daily append, fail-closed per stock)
# B: R6/CF official collection (SSE/SZSE ETF shares + margin; dedup-safe, rerun-friendly)
# C: CF-1 L1/M/L4 atom replay + side-by-side Capital Weather (independent/fail-closed)
# Exit code: 0 = ok (skips tolerated); 2 = A fatal; 3 = B fatal; 4 = C fatal.
cd /root/project/workspace/stock-selector-v2
LOG=logs/daily_pipelines.log
mkdir -p logs
echo "=== $(date -Iseconds) daily_pipelines start ===" >> $LOG
# R5/TDX 采集为纯 stdlib；R6 仍需 /tmp/aksy 的 cpython-310 vendored 依赖。
PYTHON=/usr/bin/python3
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,10) else 1)'; then
  echo "FATAL: $PYTHON 不是 3.10，R6 的 /tmp/aksy 需要 cpython-310" >> $LOG
  exit 2
fi
RC_A=0
# Process R5 in restartable shards; one slow/failing shard cannot block all others.
for OFFSET in 0 12 24 36 48 60 72; do
  R5B_OFFSET=$OFFSET R5B_LIMIT=12 \
    timeout 600 "$PYTHON" scripts/cl_r5b_daily_append.py >> $LOG 2>&1 || { echo "R5 shard offset=$OFFSET FAIL" >> $LOG; RC_A=1; }
done
PYTHONPATH=/tmp/aksy "$PYTHON" scripts/cl_r6_equityflow_daily.py >> $LOG 2>&1
RC_B=$?
if [ $RC_B -ne 0 ]; then  # SZSE endpoints intermittently flaky; one retry (dedup-safe)
  sleep 30
  PYTHONPATH=/tmp/aksy "$PYTHON" scripts/cl_r6_equityflow_daily.py >> $LOG 2>&1
  RC_B=$?
fi
PYTHONPATH=src .venv/bin/python scripts/cf/run_atoms.py >> $LOG 2>&1
RC_C=$?
echo "=== $(date -Iseconds) end RC_A=$RC_A RC_B=$RC_B RC_C=$RC_C ===" >> $LOG
[ $RC_A -ne 0 ] && exit 2
[ $RC_B -ne 0 ] && exit 3
[ $RC_C -ne 0 ] && exit 4
exit 0
