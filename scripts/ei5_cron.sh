#!/usr/bin/env bash
# EI-5P cron wrapper — 数据采集 only（不动 EOD 链路）
# usage: ei5_cron.sh auction|window|labels
set -uo pipefail
ROOT=/root/project/workspace/stock-selector-v2
cd "$ROOT" || exit 1
LOG="$ROOT/logs/ei5_cron.log"
mkdir -p "$ROOT/logs"
PY="$ROOT/.venv/bin/python"
STAGE="${1:?usage: ei5_cron.sh auction|window|labels}"
TODAY=$(date +%F)

case "$STAGE" in
  auction) echo "[$(date '+%F %T')] stage=auction day=$TODAY" >> "$LOG"
           "$PY" src/r2/ei5_collect.py --stage auction --day "$TODAY" >> "$LOG" 2>&1 ;;
  window)  echo "[$(date '+%F %T')] stage=window day=$TODAY" >> "$LOG"
           "$PY" src/r2/ei5_collect.py --stage window --day "$TODAY" >> "$LOG" 2>&1 ;;
  labels)  echo "[$(date '+%F %T')] stage=labels sweep" >> "$LOG"
           for d in $(seq 0 25); do
             D=$(date -d "-$d day" +%F)
             if [ -f "$ROOT/data/r2/ei5/features/day=$D.parquet" ]; then
               "$PY" src/r2/ei5_collect.py --stage labels --day "$D" >> "$LOG" 2>&1
             fi
           done ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
echo "[$(date '+%F %T')] stage=$STAGE done rc=$?" >> "$LOG"