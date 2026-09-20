#!/bin/bash
# start_baostock_tonight.sh — baostock 冷却后定时自动续跑
# 2026-09-20 服务端深度限流（新进程首请求即挂），停机冷却；22:00 拉起
# 断点续跑 + 保守看门狗（STALL 20 分钟，避免整夜频繁 kill/login 恶化封锁）。
# 用法: setsid nohup bash start_baostock_tonight.sh >/dev/null 2>&1 &
set -u
WS=/root/project/workspace/stock-selector-v2
PY=/root/.hermes/hermes-agent/venv/bin/python3
LOG=/tmp/fetch_adj.log
HOUR=22

now=$(date +%s)
target=$(date -d "today ${HOUR}:00" +%s)
[ "$target" -lt "$now" ] && target=$(date -d "tomorrow ${HOUR}:00" +%s)
echo "[scheduler $(date +%H:%M:%S)] baostock 续跑定于 $(date -d @$target '+%F %H:%M')" >> "$LOG"
sleep $(( target - now ))

echo "[scheduler $(date +%H:%M:%S)] 冷却完毕，拉起 baostock 断点续跑" >> "$LOG"
( cd "$WS" && setsid nohup "$PY" scripts/fetch_adjustment_source.py >> "$LOG" 2>&1 < /dev/null & )
sleep 5
FETCH_SCRIPT="$WS/scripts/fetch_adjustment_source.py" \
DIR="$WS/data/adjustment_baostock/per_stock" \
MANIFEST="$WS/data/adjustment_baostock/fetch_manifest.json" \
STALL_MIN=20 setsid nohup bash "$WS/scripts/fetch_watchdog.sh" >/dev/null 2>&1 < /dev/null &
echo "[scheduler $(date +%H:%M:%S)] watchdog(STALL=20m) 已挂" >> "$LOG"
