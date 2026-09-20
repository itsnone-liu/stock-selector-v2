#!/bin/bash
# fetch_watchdog.sh — 数据采集进程外看门狗（通用版，env 可覆盖）
# 背景：baostock 服务端会挂起连接（ESTAB 不回包），进程内 SIGALRM 无法打断
# 内核阻塞（PEP 475 自动重启），唯一可靠方案是进程外监控产出、停滞即
# kill -9 + 重启（fetch 脚本断点续跑：manifest 逐股哈希，重启零损失）。
# 用法: FETCH_SCRIPT=... DIR=... setsid nohup bash fetch_watchdog.sh &
set -u
WS=/root/project/workspace/stock-selector-v2
PY=/root/.hermes/hermes-agent/venv/bin/python3
FETCH_SCRIPT="${FETCH_SCRIPT:-$WS/scripts/fetch_adjustment_source.py}"
DIR="${DIR:-$WS/data/adjustment_baostock/per_stock}"
MANIFEST="${MANIFEST:-$(dirname "$DIR")/fetch_manifest.json}"
LOG="${LOG:-/tmp/fetch_adj.log}"
STALL_MIN="${STALL_MIN:-4}"
TARGET="${TARGET:-5594}"

last=-1; last_change=$(date +%s)
while true; do
  n=$(ls "$DIR" 2>/dev/null | wc -l)
  now=$(date +%s)
  if [ "$n" != "$last" ]; then last=$n; last_change=$now; fi
  pid=$(pgrep -f "$(basename "$FETCH_SCRIPT")$" | head -1)
  stalled=$(( now - last_change > STALL_MIN * 60 ))
  if [ -n "$pid" ] && [ "$stalled" = "1" ]; then
    echo "[watchdog $(date +%H:%M:%S) $(basename "$FETCH_SCRIPT")] stalled ${STALL_MIN}m at n=$n, kill+restart pid=$pid" >> "$LOG"
    kill -9 "$pid" 2>/dev/null
    sleep 3
    ( cd "$WS" && setsid nohup "$PY" "$FETCH_SCRIPT" >> "$LOG" 2>&1 < /dev/null & )
    sleep 120   # 重启静默窗口
  elif [ -z "$pid" ]; then
    ok=$("$PY" -c "import json;print(sum(1 for v in json.load(open('$MANIFEST'))['stocks'].values() if v.get('status')=='ok'))" 2>/dev/null || echo 0)
    if [ "${ok:-0}" -ge "$TARGET" ]; then
      echo "[watchdog $(date +%H:%M:%S) $(basename "$FETCH_SCRIPT")] all done (ok=$ok) -- exit" >> "$LOG"
      break
    fi
    echo "[watchdog $(date +%H:%M:%S) $(basename "$FETCH_SCRIPT")] process gone at n=$n ok=$ok -- restart" >> "$LOG"
    ( cd "$WS" && setsid nohup "$PY" "$FETCH_SCRIPT" >> "$LOG" 2>&1 < /dev/null & )
    sleep 120
  fi
  sleep 60
done
