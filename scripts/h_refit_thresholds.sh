#!/usr/bin/env bash
# ============================================================================
# 慢频阈值重推入口 (CD-2A)  —— 仅在老刘手动更新完慢频数据并通知后执行。
#
# 定案 (user ruling 2026-10-21, 2nd): 阈值随「慢频数据更新事件」重推, 不按天。
#   日常链 C1A = carry: 只重建 band 表, 沿用 docs/cd/cd2a_thresholds.json 里的
#                     thresholds + stratum_map, 不重推。
#   --refit     = 重推: 从 dev 窗口(2021-01..2023-12) 重算分位阈值。
#   慢频节奏: e5 每周一 / holders 每月 1 号 / 机构持仓每季 / 新股纳入每月
#
# 用法:
#   bash scripts/h_refit_thresholds.sh "holders 2026-11-01"            # 重推 + 重跑全链
#   bash scripts/h_refit_thresholds.sh "e5 每周增量" --no-chain        # 只重推
#   SKIP=A,C1,C2 bash scripts/h_refit_thresholds.sh "e5"              # 慢频不影响轴输入时省时
#
# 生产上请脱离会话跑 (前台 >180s 会被 SIGKILL):
#   systemd-run --unit=h-refit-$(date +%s) --collect \
#     bash /root/project/workspace/stock-selector-v2/scripts/h_refit_thresholds.sh "holders 2026-11-01"
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

TRIGGER="${1:-slow-data update}"
MODE="${2:-}"
SKIP="${SKIP:-}"          # 空 = 全链(A..F); 逗号分隔步骤将被跳过
DAY="${DAY:-$(date +%F)}"
PY=.venv/bin/python

echo "[h-refit] start $(date -Is)  trigger='$TRIGGER'  day=$DAY  skip='${SKIP:-<none>}'"

# --- 1) 重推阈值 + 重建 band 表 (幂等; 确定性自检在脚本内部) --------------------
$PY scripts/cd2a_census_and_bands.py --refit --trigger "$TRIGGER" || {
  echo "[h-refit] FAIL refit step rc=$?"; exit 1; }

if [ "$MODE" = "--no-chain" ]; then
  echo "[h-refit] refit done, chain NOT rerun (--no-chain) $(date -Is)"
  exit 0
fi

# --- 2) 重跑链, 让状态表/池子用新阈值重算 (C1A 必须重跑) ------------------------
ARGS=(--day "$DAY")
[ -n "$SKIP" ] && ARGS+=(--skip "$SKIP")
$PY src/r2/daily_update.py "${ARGS[@]}"
rc=$?

if [ $rc -ne 0 ]; then
  echo "[h-refit] chain FAILED rc=$rc $(date -Is)"
  echo "[h-refit] 若上面报 'rows relabelled (bound 500)' —— 重推日的合法大迁移,"
  echo "          用显式预算重跑(留痕 NOTE):  R2_L2_RELABEL_BUDGET=3000 $0 '$TRIGGER'"
  echo "          身份丢失(l2/date/n 消失)类报错不允许用该预算绕过, 必须查因。"
  exit $rc
fi
echo "[h-refit] DONE $(date -Is)  (band/state/pool 已按新阈值重算)"