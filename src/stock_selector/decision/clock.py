"""盘中时钟与证据层（蓝图 §3）。

一切计算以 as_of 为唯一时钟：
- L0：当日尚无数据（开盘前/非交易日），最近完整证据=上一交易日；
- L1：当日部分K线（盘中），必须携带会话完成度与量能折算视图；
- L2：当日收盘后，当日证据完整。

价格不投影：L1 只记录已实现值。量能是累积变量，允许按分布折算，
折算方法带版本号；分布样本不足时输出 None 并降级证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

import pandas as pd

from stock_selector.calendar import (
    AFTERNOON_END,
    MINUTES_PER_SESSION,
    MORNING_START,
    elapsed_trading_minutes,
    current_week_rows,
)

MIN_COMPLETION_FOR_PRORATION = 0.10  # 完成度低于10%时量能折算噪声过大，拒绝折算


@dataclass(frozen=True)
class SessionClock:
    """as_of 时点的会话与证据状态。"""

    as_of: datetime
    evidence_level: str  # "L0" | "L1" | "L2"
    observed_minutes: int
    total_minutes: int = MINUTES_PER_SESSION
    completion: float = 0.0
    calendar_weekday: int = 0  # isoweekday: 1=周一 … 7=周日
    trading_session_in_week: int | None = None  # 本周第几个交易日（按日线索引），信息不足为 None
    trading_day: bool = True

    @property
    def week_completion_with_today(self) -> float:
        """周完成度：已完成交易日 + 当日会话完成度，再 /5（保守上界1.0）。"""
        sessions = self.trading_session_in_week or 0
        if self.evidence_level == "L0":
            # 当日还没开盘：当日不贡献完成度，本周已完成 sessions-1 个交易日。
            return max(0.0, min(1.0, (sessions - 1) / 5.0)) if sessions else 0.0
        if self.evidence_level == "L2":
            return max(0.0, min(1.0, sessions / 5.0)) if sessions else 0.0
        return max(0.0, min(1.0, (sessions - 1 + self.completion) / 5.0)) if sessions else 0.0


def session_clock(as_of: datetime, daily: pd.DataFrame | None = None) -> SessionClock:
    """构造 as_of 时点的会话时钟。

    daily 提供交易日索引（判断本周第几个交易日与是否交易日）；
    无日线时 trading_session_in_week=None，交易日按工作日近似（标注 trading_day 近似）。
    """
    weekday = as_of.isoweekday()
    observed = elapsed_trading_minutes(as_of)
    t = as_of.time()

    if weekday >= 6:
        # 周末：最近一次会话已完整（相对该会话为 L2）。
        level = "L2"
    elif t < MORNING_START:
        level = "L0"
    elif t >= AFTERNOON_END:
        level = "L2"
    else:
        level = "L1"

    sessions_before_today = 0
    has_today = False
    approx = daily is None or daily.empty
    if not approx:
        rows = current_week_rows(daily, as_of)
        today = as_of.date()
        for ts in rows.index:
            d = pd.Timestamp(ts).date()
            if d < today:
                sessions_before_today += 1
            elif d == today:
                has_today = True
        session_idx = sessions_before_today + (1 if has_today else 0)
        # 盘中（L1）时 as_of 当日必为交易时段（节假日取不到盘中行情）：
        # 即使帧中尚无当日行（仅有quote），当日也计入本周会话数。
        if not has_today and level == "L1" and weekday <= 5:
            session_idx = sessions_before_today + 1
        session_idx = session_idx if session_idx > 0 else None
        # 帧里有今天但 as_of 在开盘前（例如凌晨重算）→ 视作 L0 复核昨日。
    else:
        session_idx = weekday if weekday <= 5 else None

    completion = max(0.0, min(1.0, observed / MINUTES_PER_SESSION))
    trading_day = weekday <= 5 and (approx or (has_today or sessions_before_today >= 0 and weekday <= 5))
    return SessionClock(
        as_of=as_of,
        evidence_level=level,
        observed_minutes=observed,
        completion=completion,
        calendar_weekday=weekday,
        trading_session_in_week=session_idx,
        trading_day=weekday <= 5,
    )


class VolumeClock:
    """量能折算：当日累计量 → 当日预期全量。

    method="uniform_v0"（默认）：完成度=时钟占比，无分布假设，保守；
    method="profile_v1"：传入按分钟校准的累计分布（来自历史分钟数据的中位分布）。
    折算结果始终与原始累计量一起输出，禁止只报折算值。
    """

    def __init__(self, profile: Callable[[int], float] | None = None):
        self._profile = profile
        self.method = "profile_v1" if profile is not None else "uniform_v0"

    def fraction_at(self, observed_minutes: int) -> float | None:
        if self._profile is not None:
            value = float(self._profile(observed_minutes))
        else:
            value = observed_minutes / float(MINUTES_PER_SESSION)
        if value <= MIN_COMPLETION_FOR_PRORATION:
            return None
        return min(value, 1.0)

    def expected_day_volume(self, cum_volume: float | None, observed_minutes: int) -> tuple[float | None, str]:
        """返回 (预期全量, 方法名)。样本/完成度不足时 (None, method)。"""
        if cum_volume is None or cum_volume < 0:
            return None, self.method
        fraction = self.fraction_at(observed_minutes)
        if fraction is None:
            return None, self.method
        return cum_volume / fraction, self.method


def build_minute_profile(minute_frames: list[pd.DataFrame]) -> Callable[[int], float] | None:
    """从分钟数据校准累计量分布（供 profile_v1）。

    minute_frames: 每个元素为单日分钟K线，索引为时间戳，含 volume 列。
    返回 observed_minutes(0..240) → 截至该分钟的累计量占全日比例（跨日中位）。
    样本 < 20 日时返回 None（拒绝校准，保持 uniform_v0）。
    """
    if not minute_frames or len(minute_frames) < 20:
        return None
    by_minute: dict[int, list[float]] = {}
    for frame in minute_frames:
        total = float(frame["volume"].sum())
        if total <= 0:
            continue
        cum = 0.0
        for ts, vol in zip(frame.index, frame["volume"]):
            minute = _minutes_of_day(pd.Timestamp(ts))
            cum += float(vol)
            by_minute.setdefault(minute, []).append(cum / total)
    samples: list[tuple[int, float]] = []
    for minute in sorted(by_minute):
        values = by_minute[minute]
        values.sort()
        samples.append((minute, values[len(values) // 2]))
    table = dict(samples)

    def profile(observed: int) -> float:
        if observed <= 0:
            return 0.0
        if observed in table:
            return table[observed]
        keys = sorted(table)
        lower = max(k for k in keys if k <= observed)
        return table[lower]

    return profile


def _minutes_of_day(ts: pd.Timestamp) -> int:
    t = ts.time()
    base = 0 if t.hour < 12 else 120
    if t.hour < 12:
        return max(0, (t.hour - 9) * 60 + t.minute)
    return min(MINUTES_PER_SESSION, base + (t.hour - 13) * 60 + t.minute)


def iso_week_end(day: date) -> str:
    """该日所在自然周的周五日期（证据周标签用）。"""
    ts = pd.Timestamp(day)
    friday = ts + pd.Timedelta(days=(4 - ts.weekday()))
    return str(friday.date())
