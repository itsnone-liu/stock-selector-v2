from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd


def _replace_atomic(temp_name: str, target: Path) -> None:
    os.replace(temp_name, target)


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
