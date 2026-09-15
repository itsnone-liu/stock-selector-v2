"""大盘 regime（指数 vs MA20/MA60）与 capital-observer 上下文适配（蓝图 §7、§9）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from stock_selector.indicators import sma

BULL = "bull"
MID = "mid"
WEAK = "weak"


def market_regime(index_daily: pd.DataFrame, asof: datetime) -> tuple[str | None, dict]:
    """指数收盘 vs MA20/MA60。数据截至 as_of（由调用方截断），三态输出。

    返回 (regime, metrics)；数据不足时 (None, {"reason": ...})，
    None 表示 unknown——**不得**当作 mid/neutral 处理。
    """
    if index_daily is None or len(index_daily) < 60:
        return None, {"reason": "insufficient_index_bars"}
    frame = index_daily[index_daily.index <= pd.Timestamp(asof)]
    if len(frame) < 60:
        return None, {"reason": "insufficient_index_bars_asof"}
    close = frame["close"]
    ma20 = sma(close, 20)
    ma60 = sma(close, 60)
    c, m20, m60 = float(close.iloc[-1]), float(ma20.iloc[-1]), float(ma60.iloc[-1])
    if any(pd.isna(v) for v in (m20, m60)):
        return None, {"reason": "index_ma_nan"}
    metrics = {"index_close": round(c, 2), "ma20": round(m20, 2), "ma60": round(m60, 2),
               "asof_index_date": str(pd.Timestamp(frame.index[-1]).date())}
    if c > m20 and c > m60:
        return BULL, metrics
    if c < m20 and c < m60:
        return WEAK, metrics
    return MID, metrics


EVIDENCE_TYPES = {"fact", "proxy", "estimate"}
VALID_CONTEXTS = {"supportive", "neutral", "divergent", "unknown"}


@dataclass
class CapitalChannel:
    name: str
    evidence_type: str  # fact / proxy / estimate
    observation_date: str | None
    available_at: str | None
    status: str  # fresh / stale / unknown
    direction: str  # inflow / outflow / flat / unknown


@dataclass
class CapitalContext:
    """capital-observer 上下文的消费端快照（unknown ≠ neutral）。"""

    sector_id: str | None = None
    as_of: str | None = None
    context: str = "unknown"  # supportive / neutral / divergent / unknown
    channels: dict[str, CapitalChannel] = field(default_factory=dict)
    method_version: str | None = None
    limitations: list[str] = field(default_factory=list)
    coverage_reported: str | None = None  # 上游按预期通道总数给出的覆盖（缺失计入分母）

    @property
    def coverage(self) -> str:
        # 优先用上游报告（分母=预期通道数，含规划位）；无上游字段时退回
        # 已知通道数口径（兼容旧payload，注意该口径会高估覆盖率）。
        if self.coverage_reported:
            return self.coverage_reported
        known = sum(1 for ch in self.channels.values() if ch.status != "unknown")
        return f"{known}/{len(self.channels)}" if self.channels else "0/0"

    def divergent_or_unknown(self) -> bool:
        return self.context in ("divergent", "unknown")


def parse_capital_context(payload: dict | None) -> CapitalContext:
    """解析 capital-observer 的 context JSON（契约见蓝图 §7）。

    缺失/损坏输入一律返回 unknown 上下文，绝不默认 neutral。
    """
    result = CapitalContext()
    if not isinstance(payload, dict):
        result.limitations.append("capital_context_unavailable")
        return result
    result.sector_id = payload.get("sector_id")
    result.as_of = payload.get("as_of")
    result.method_version = payload.get("method_version")
    cov = payload.get("coverage")
    if isinstance(cov, str) and "/" in cov:
        result.coverage_reported = cov
    ctx = payload.get("context", "unknown")
    result.context = ctx if ctx in VALID_CONTEXTS else "unknown"
    channels = payload.get("channels") or {}
    for name, raw in channels.items():
        if not isinstance(raw, dict):
            result.channels[name] = CapitalChannel(name, "proxy", None, None, "unknown", "unknown")
            continue
        etype = raw.get("evidence_type", "proxy")
        etype = etype if etype in EVIDENCE_TYPES else "proxy"
        status = raw.get("status", "unknown")
        result.channels[name] = CapitalChannel(
            name=name,
            evidence_type=etype,
            observation_date=raw.get("observation_date"),
            available_at=raw.get("available_at"),
            status=status if status in ("fresh", "stale", "unknown") else "unknown",
            direction=raw.get("direction", "unknown"),
        )
    for item in payload.get("limitations") or []:
        if isinstance(item, str):
            result.limitations.append(item)
    return result
