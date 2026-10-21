#!/usr/bin/env bash
# ============================================================================
# 慢频数据抓取 (H) —— stock-data 仓库 → data/r2/e5/ → 重建 e5.db
#
# 背景: 慢频 e5(两融/龙虎榜/大宗) 的原始数据由老刘手动上传到 GitHub 私有仓库
#       itsnone-liu/stock-data, 然后通知助手「上 github 抓」。本脚本就是那一抓。
#       与 CD-2A 阈值重推挂钩: 慢频更新事件 → 本脚本 → (可选) h_refit_thresholds.sh
#
# 用法:
#   bash scripts/h_slowdata_pull.sh                    # 抓+校验+同步+重建 e5.db
#   bash scripts/h_slowdata_pull.sh --check            # 只看: 拉取+校验+报告差异, 不落盘
#   bash scripts/h_slowdata_pull.sh --no-build         # 同步文件但不重建 e5.db
#   bash scripts/h_slowdata_pull.sh --force            # 无变化也重建 e5.db
#   bash scripts/h_slowdata_pull.sh --refit "e5 2026-10-25"   # 完成后接阈值重推+重跑链
#
# 生产上脱离会话跑 (前台 >180s 可能被 SIGKILL):
#   systemd-run --unit=h-slowdata-$(date +%s) --collect \
#     bash /root/project/workspace/stock-selector-v2/scripts/h_slowdata_pull.sh --refit "e5 2026-10-25"
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
# systemd-run / 裸环境里 HOME 可能丢 → git 凭据 (~/.git-credentials, helper=store) 会读不到
export HOME="${HOME:-/root}"
export GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL:-$HOME/.gitconfig}"

REPO="${SLOWDATA_REPO:-https://github.com/itsnone-liu/stock-data.git}"
STAGE="${SLOWDATA_STAGE:-/root/slowdata/stock-data}"
E="$(pwd)/data/r2/e5"
PY=/usr/bin/python3            # capital_data 脚本只用 stdlib, 系统 3.10 即可

MODE=run; DO_BUILD=1; FORCE=0; REFIT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check)    MODE=check; DO_BUILD=0 ;;
    --no-build) DO_BUILD=0 ;;
    --force)    FORCE=1 ;;
    --refit)    shift; REFIT="${1:-slow-data update}"; DO_BUILD=1 ;;
    *) echo "[slowdata] 未知参数: $1"; exit 2 ;;
  esac
  shift
done

echo "[slowdata] start $(date -Is)  mode=$MODE  stage=$STAGE"

# --- 1) 拉取 (常驻浅克隆, 之后每次只增量 fetch) -----------------------------
mkdir -p "$(dirname "$STAGE")"
if [ -d "$STAGE/.git" ]; then
  GIT_TERMINAL_PROMPT=0 git -C "$STAGE" fetch --depth 1 origin main -q \
    || { echo "[slowdata] FAIL: fetch 失败 (凭据/网络?)"; exit 1; }
  git -C "$STAGE" reset --hard FETCH_HEAD -q || { echo "[slowdata] FAIL: reset"; exit 1; }
else
  GIT_TERMINAL_PROMPT=0 git clone --depth 1 -q "$REPO" "$STAGE" \
    || { echo "[slowdata] FAIL: clone 失败 (凭据/网络?)"; exit 1; }
fi
echo "[slowdata] repo HEAD: $(git -C "$STAGE" log -1 --format='%h | %ad | %s' --date=short)"

# --- 2) MANIFEST sha256 完整性闸门 + 与本地差异分类 -------------------------
VERDICT="$($PY - "$STAGE" "$E" <<'PY'
import json, hashlib, sys, pathlib
stage, E = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
man = json.loads((stage / 'MANIFEST.json').read_text())
same, new, changed = [], [], []
def check(paths):
    ok, prob = [], []
    for e in paths:
        sp = stage / e['path']
        if not sp.exists():
            prob.append(f"{e['path']} 缺文件"); continue
        h = hashlib.sha256(sp.read_bytes()).hexdigest()
        if h != e.get('sha256'):
            d = sp.stat().st_size - e.get('bytes', sp.stat().st_size)
            prob.append(f"{e['path']} sha256 不符 (实体 {sp.stat().st_size} B vs 清单 {e.get('bytes')} B, Δ{d:+d})")
            continue
        lp = E / e['path']
        if not lp.exists(): new.append(e)
        elif hashlib.sha256(lp.read_bytes()).hexdigest() != h: changed.append(e)
        else: same.append(e)
        ok.append(e)
    return ok, prob

print(f"  [gate] MANIFEST generated={man.get('generated')}")
arc_ok, arc_bad = check(man.get('archives', []))
csv_ok, csv_bad = check(man.get('csv', []))
print(f"  [gate] 归档 {len(man.get('archives', []))} 项 sha256: {'全部通过' if not arc_bad else 'FAIL'}")
for b in arc_bad: print("  [gate] !!", b)
if csv_bad:
    print(f"  [gate] CSV 清单不一致 {len(csv_bad)} 项 —— 软告警, 不阻断 (e5/csv 目前代码零消费):")
    for b in csv_bad: print("  [gate] ~", b)
    print("  [gate] ~ 上游待修: 重新生成 MANIFEST 的 csv 段 (实体是准的, 清单是旧的)")
elif csv_ok:
    print("  [gate] CSV 3 项 sha256: 通过")
if new:
    print(f"  [diff] 新增 {len(new)}:")
    for e in new: print(f"      + {e['path']}  {e.get('date_min','')}..{e.get('date_max','')}")
if changed:
    print(f"  [diff] 变更 {len(changed)}:")
    for e in changed: print(f"      ~ {e['path']}  {e.get('date_min','')}..{e.get('date_max','')}")
print(f"  [diff] 未变 {len(same)}  (新增 {len(new)} / 变更 {len(changed)})")
need = 1 if (new or changed) else 0
print(f"NEED_BUILD={need}")
print(f"GATE_FAIL={1 if arc_bad else 0}")
PY
)"
echo "$VERDICT"
# 闸门自身没吐结论 = 硬失败 (宁可停, 不可静默放行)
grep -q 'GATE_FAIL=' <<<"$VERDICT" || { echo "[slowdata] FAIL: 完整性闸门未产生结论 (脚本异常)"; exit 1; }
grep -q 'GATE_FAIL=1' <<<"$VERDICT" && { echo "[slowdata] FAIL: 归档 sha256 未过, 未落盘"; exit 1; }
NEED_BUILD="$(grep -oE 'NEED_BUILD=[01]' <<<"$VERDICT" | cut -d= -f2)"

if [ "$MODE" = check ]; then
  echo "[slowdata] --check 结束: 未改任何文件 ($(date -Is))"
  exit 0
fi

# --- 3) 同步进 data/r2/e5/ (rsync -a 不加 --delete: 只覆盖同名, 不删本地) ----
for d in block lhb_raw margin csv; do
  [ -d "$STAGE/$d" ] && rsync -a "$STAGE/$d/" "$E/$d/" || { echo "[slowdata] FAIL: rsync $d"; exit 1; }
done
for f in MANIFEST.json README.md; do
  [ -f "$STAGE/$f" ] && cp -f "$STAGE/$f" "$E/$f"
done
echo "[slowdata] 文件已同步 → $E  (du: $(du -sh "$E" | cut -f1))"

# --- 4) 重建 e5.db ----------------------------------------------------------
stats() { $PY -c "
import sqlite3,sys
c=sqlite3.connect('$E/e5.db')
for t in ('margin','block','lhb'):
    try: print(f'    {t:7s}', c.execute(f'SELECT COUNT(*),MIN(date),MAX(date) FROM {t}').fetchone())
    except Exception as ex: print(f'    {t:7s} n/a')
"; }
counts() { $PY -c "
import sqlite3
c=sqlite3.connect('$E/e5.db')
print(' '.join(t+'='+str(c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]) for t in ('margin','block','lhb')))
" 2>/dev/null; }
if [ "$DO_BUILD" = 1 ]; then
  if [ "$NEED_BUILD" = 1 ] || [ "$FORCE" = 1 ]; then
    echo "[slowdata] 重建 e5.db 前:"; stats
    BEFORE="$(counts)"
    $PY src/capital_data/e5_build_db.py || { echo "[slowdata] FAIL: e5_build_db.py"; exit 1; }
    $PY src/capital_data/e5_lhb_build.py || { echo "[slowdata] FAIL: e5_lhb_build.py"; exit 1; }
    echo "[slowdata] 重建 e5.db 后:"; stats
    # 膨胀绊线: 重建是幂等的, 行数只应随新数据小幅增长; 出现倍数级膨胀 = 摄取出问题
    $PY - "$BEFORE" "$(counts)" <<'PY' || exit 1
import sys
b={k:int(v) for k,v in (x.split('=') for x in sys.argv[1].split())}
a={k:int(v) for k,v in (x.split('=') for x in sys.argv[2].split())}
bad=[]
for t in ('margin','block','lhb'):
    if t in b and b[t]>0 and a.get(t,0) > b[t]*1.4:
        bad.append(f"{t}: {b[t]} -> {a[t]}")
if bad:
    print("[slowdata] FAIL: 行数膨胀 (摄取非幂等?) " + "; ".join(bad))
    sys.exit(1)
print("[slowdata] 幂等核验通过: " + ", ".join(f"{t} {b.get(t,0)}->{a.get(t,0)}" for t in ('margin','block','lhb')))
PY
  else
    echo "[slowdata] 归档无变化 → 跳过 e5.db 重建 (要强重建加 --force)"
  fi
else
  echo "[slowdata] --no-build: 跳过 e5.db 重建"
fi

# --- 5) 可选: 慢频事件 → CD-2A 阈值重推 + 重跑链 -----------------------------
if [ -n "$REFIT" ]; then
  echo "[slowdata] 接阈值重推: trigger='$REFIT' $(date -Is)"
  bash scripts/h_refit_thresholds.sh "$REFIT" || { echo "[slowdata] FAIL: h_refit_thresholds.sh"; exit 1; }
fi

echo "[slowdata] DONE $(date -Is)"