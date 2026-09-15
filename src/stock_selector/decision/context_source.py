"""capital-observer 上下文自动接入（蓝图 §7 消费端）。

decide 默认从本地 capital-observer (127.0.0.1:8120) 拉取 /api/v1/context。
失败/超时/契约不符 → 返回 None，决策层按 unknown 处理（绝不 crash、
绝不默认 neutral）。
"""

from __future__ import annotations

from datetime import datetime

import requests

DEFAULT_CONTEXT_BASE = "http://127.0.0.1:8120"
_TIMEOUT = (3, 8)  # (连接, 读取) — 本机服务，快失败


def fetch_context_payload(code: str, board: str | None = None,
                          base_url: str = DEFAULT_CONTEXT_BASE,
                          timeout: tuple[float, float] = _TIMEOUT) -> dict | None:
    """拉取并做最小契约校验；任何异常返回 None。"""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/v1/context",
                            params={"code": code, **({"board": board} if board else {})},
                            timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001 — 网络面全部降级为 unknown
        return None
    if not isinstance(payload, dict) or "context" not in payload:
        return None
    payload.setdefault("sector_id", board)
    return payload


def context_available_at(payload: dict | None) -> str | None:
    """上下文里最新的观测日期（无则 None）。"""
    if not payload:
        return None
    channels = payload.get("channels") or {}
    dates = [ch.get("observation_date") for ch in channels.values()
             if isinstance(ch, dict) and ch.get("observation_date")]
    return max(dates) if dates else payload.get("as_of")


def context_freshness(payload: dict | None, asof: datetime) -> str:
    """粗新鲜度：最新观测距 as_of 的工作日数（0=当日，1=T-1...）。

    用工作日近似（周末/节假日修正自然日偏差）；完整交易日历不在本模块
    的依赖范围内，标注为近似。"""
    latest = context_available_at(payload)
    if not latest:
        return "unknown"
    try:
        d = datetime.fromisoformat(str(latest)[:10].replace("/", "-")).date()
    except ValueError:
        return "unknown"
    try:
        import numpy as np
        business_days = int(np.busday_count(d, asof.date()))
    except Exception:
        business_days = (asof.date() - d).days * 5 // 7
    if business_days <= 1:
        return "current"
    if business_days <= 5:
        return "t_minus_few"
    return "stale"
