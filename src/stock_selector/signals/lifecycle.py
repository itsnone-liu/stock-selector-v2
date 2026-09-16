"""生命周期：动能状态演化与 episode 跟踪（方案 §3.3/§4.3）。"""
from __future__ import annotations

from datetime import datetime

from stock_selector.signals.contracts import Episode, UNKNOWN


class EpisodeTracker:
    """按 (code, kind) 跟踪首次触发→确认→失效→重触发。

    只接受收盘后确认的状态（盘中观察记 first_observed_intraday，不算确认）。
    """

    def __init__(self) -> None:
        self._episodes: dict[tuple[str, str], Episode] = {}
        self._counter = 0

    def observe(self, code: str, kind: str, state: str, as_of: datetime) -> Episode:
        key = (code, kind)
        ep = self._episodes.get(key)
        active = state not in (UNKNOWN, "none", None, False)
        if ep is None:
            self._counter += 1
            ep = Episode(episode_id=f"{kind}-{self._counter}", code=code, kind=kind)
            self._episodes[key] = ep
        ep.previous_state = ep.current_state or UNKNOWN
        ep.current_state = str(state)
        if active:
            if ep.first_observed_at is None:
                ep.first_observed_at = as_of
                ep.transition_reason = "first_observed"
            else:
                ep.retriggered_at = as_of if ep.invalidated_at else ep.retriggered_at
                ep.transition_reason = "retrigger" if ep.invalidated_at else "continuing"
                ep.invalidated_at = None
            ep.last_confirmed_at = as_of
            ep.consecutive_confirmations += 1
        else:
            if ep.first_observed_at is not None and ep.invalidated_at is None:
                ep.invalidated_at = as_of
                ep.transition_reason = "invalidated"
                ep.consecutive_confirmations = 0
        return ep

    def confirmation_delay(self, code: str, kind: str, sessions_between) -> int | None:
        ep = self._episodes.get((code, kind))
        if ep is None or ep.first_observed_at is None:
            return None
        return sessions_between(ep.first_observed_at, ep.last_confirmed_at) if ep.last_confirmed_at else None
