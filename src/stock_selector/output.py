from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

# 碰撞重试上限：超过后追加微秒级时间戳兜底，避免病态目录下的无限循环。
_COLLISION_LIMIT = 1000


def _replace_atomic(temp_name: str, target: Path) -> None:
    os.replace(temp_name, target)


def reserve_run_dir(runs_root: str | Path, stamp: str, label: str) -> Path:
    """占位并返回不可覆盖的运行归档目录 `runs/<stamp>/<label>`。

    同名目录已存在时依次追加 `-2`、`-3`……（同一秒内的重复/并发运行各得其所）。
    以 `mkdir(exist_ok=False)` 的原子语义占位，而不是先 `exists()` 再创建，
    因此即使两个进程在同一秒同时归档，也不会写入同一个目录、不会覆盖既有证据。
    """
    root = Path(runs_root) / stamp
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / label
    attempt = 2
    while True:
        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            if attempt > _COLLISION_LIMIT:
                candidate = root / f"{label}-{attempt}-{datetime.now().strftime('%f')}"
            else:
                candidate = root / f"{label}-{attempt}"
            attempt += 1


def write_csv(frame: pd.DataFrame, target: str | Path, encoding: str = "utf-8-sig", atomic: bool = True) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    if "代码" in frame.columns:
        frame = frame.copy()
        frame["代码"] = frame["代码"].astype(str).str.zfill(6)
    if not atomic:
        frame.to_csv(path, index=False, encoding=encoding)
        return path
    with NamedTemporaryFile("w", encoding=encoding, newline="", dir=path.parent, delete=False) as fh:
        temp_name = fh.name
        frame.to_csv(fh, index=False)
    _replace_atomic(temp_name, path)
    return path


def write_json(data: Any, target: str | Path, atomic: bool = True) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if not atomic:
        path.write_text(text, encoding="utf-8")
        return path
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
        temp_name = fh.name
        fh.write(text)
    _replace_atomic(temp_name, path)
    return path
