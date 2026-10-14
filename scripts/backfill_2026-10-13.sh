#!/bin/bash
# 一次性补跑：2026-10-13 A步缺口（腾讯qfq滞后99只）→ E → F 重封 shadow
# cron: 0 8 14 10 * （10-14 08:00 一次性，跑完可删）
set -e
cd /root/project/workspace/stock-selector-v2
LOG=logs/backfill_2026-10-13.log
echo "=== [A] $(date) ===" >> $LOG
.venv/bin/python src/r2/daily_price_update.py --day 2026-10-13 >> $LOG 2>&1
echo "=== [E] $(date) ===" >> $LOG
.venv/bin/python src/r2/current_scan.py >> $LOG 2>&1
echo "=== [F] $(date) ===" >> $LOG
.venv/bin/python src/r2/shadow_portfolio.py --day 2026-10-13 >> $LOG 2>&1
echo "=== DONE $(date) ===" >> $LOG
