#!/usr/bin/env bash
# 批量归档 captures/batch* 到百度网盘：逐批 manifest→tar→upload→verify→删临时tar
# 本脚本不动 captures/ 本体；工作盘删除需人工确认后另行执行。
set -euo pipefail
cd /root/project/workspace/stock-selector-v2
mkdir -p captures-archive
BATCHES="${1:-batch3 batch4 batch5 batch6 batch7 batch8 batch9 batch9_extra batch10 batch11 batch14 batch15 batch16}"
for b in $BATCHES; do
  src="captures/$b"
  [ -d "$src" ] || { echo "== $b 不存在，跳过"; continue; }
  echo "======================================== $b $(date +%T)"
  if [ -f "captures-archive/$b.receipt.json" ]; then echo "$b 已有回执，跳过"; continue; fi
  find "$src" -type f -print0 | sort -z | xargs -0 sha256sum > "captures-archive/$b.manifest.sha256"
  tar -cf "captures-archive/$b.tar" -C captures "$b" -C ../captures-archive "$b.manifest.sha256"
  sha256sum "captures-archive/$b.tar" > "captures-archive/$b.tar.sha256"
  python3 scripts/bdpan_archive.py upload "captures-archive/$b.tar"
  python3 scripts/bdpan_archive.py verify "captures-archive/$b.tar"
  python3 - "$b" <<'PY'
import hashlib, json, sys, time
from pathlib import Path
b = sys.argv[1]
tar = Path(f"captures-archive/{b}.tar")
up = Path(f"/root/.config/bdpan/upload-{tar.name}.json")
receipt = {
    "batch": b,
    "tar_sha256": Path(f"captures-archive/{b}.tar.sha256").read_text().split()[0],
    "manifest": f"captures-archive/{b}.manifest.sha256",
    "manifest_sha256": hashlib.sha256(Path(f"captures-archive/{b}.manifest.sha256").read_bytes()).hexdigest(),
    "remote_file": f"/apps/ss2archive/{tar.name}",
    "uploaded_at": time.strftime("%F %T"),
}
if up.exists():
    receipt.update({k: v for k, v in json.loads(up.read_text()).items() if k in ("fs_id", "size", "md5")})
Path(f"captures-archive/{b}.receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=1))
print(f"receipt 写入 captures-archive/{b}.receipt.json")
PY
  rm -f "captures-archive/$b.tar"
  echo "$b 完成 ✓  $(date +%T)"
done
echo "ALL DONE $(date +%T)"
