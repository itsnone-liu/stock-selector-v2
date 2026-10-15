#!/bin/bash
# Daily pipelines for Hermes (run after 19:30 CST on trading days).
# A: R5 OOS-B shadow increment (baostock 5m/daily -> shadow_daily append, fail-closed per stock)
# B: R6 EquityFlow official collection (SSE/SZSE ETF shares + margin; dedup-safe, rerun-friendly)
# Exit code: 0 = ok (skips tolerated); 2 = A fatal; 3 = B fatal.
cd /root/project/workspace/stock-selector-v2
LOG=logs/daily_pipelines.log
mkdir -p logs
echo "=== $(date -Iseconds) daily_pipelines start ===" >> $LOG
RC_A=0
# Process R5 in restartable shards; one slow/failing shard cannot block all others.
for OFFSET in 0 12 24 36 48 60 72; do
  R5B_OFFSET=$OFFSET R5B_LIMIT=12 PYTHONPATH=/tmp/bspy \
    timeout 600 python3 scripts/cl_r5b_daily_append.py >> $LOG 2>&1 || { echo "R5 shard offset=$OFFSET FAIL" >> $LOG; RC_A=1; }
done
PYTHONPATH=/tmp/aksy python3 scripts/cl_r6_equityflow_daily.py >> $LOG 2>&1
RC_B=$?
if [ $RC_B -ne 0 ]; then  # SZSE endpoints intermittently flaky; one retry (dedup-safe)
  sleep 30
  PYTHONPATH=/tmp/aksy python3 scripts/cl_r6_equityflow_daily.py >> $LOG 2>&1
  RC_B=$?
fi
echo "=== $(date -Iseconds) end RC_A=$RC_A RC_B=$RC_B ===" >> $LOG
[ $RC_A -ne 0 ] && exit 2
[ $RC_B -ne 0 ] && exit 3
exit 0
