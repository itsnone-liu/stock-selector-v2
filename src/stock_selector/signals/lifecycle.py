"""生命周期：将每日状态折叠为去重 episode（不改变信号规则）。"""
from __future__ import annotations

from datetime import datetime

from stock_selector.signals.contracts import Episode, UNKNOWN


class EpisodeTracker:
    """按 (code, kind) 跟踪首次触发、持续确认、失效和重触发。

    - 连续active属于同一episode；
    - none/False使active episode失效；
    - unknown仅表示无证据，不得把事件判为失效；
    - 失效后再次active生成新的episode_id，避免把两次机会合并。
    """

    def __init__(self) -> None:
        self._active: dict[tuple[str, str], Episode] = {}
        self._latest: dict[tuple[str, str], Episode] = {}
        self._history: list[Episode] = []
        self._counter = 0

    def _new(self, code: str, kind: str, as_of: datetime, retrigger: bool) -> Episode:
        self._counter += 1
        ep = Episode(
            episode_id=f"{kind}-{self._counter}", code=code, kind=kind,
            first_observed_at=as_of, last_confirmed_at=as_of,
            retriggered_at=as_of if retrigger else None,
            consecutive_confirmations=1, previous_state="none", current_state="active",
            transition_reason="retrigger" if retrigger else "first_observed",
        )
        key = (code, kind)
        self._active[key] = ep
        self._latest[key] = ep
        self._history.append(ep)
        return ep

    def observe(self, code: str, kind: str, state: str, as_of: datetime) -> Episode:
        key = (code, kind)
        ep = self._active.get(key)
        is_unknown = state in (UNKNOWN, None)
        active = state not in (UNKNOWN, "none", None, False)

        if is_unknown:
            if ep is None:
                # 尚无事件时也返回可审计的unknown占位，但不写入事件历史。
                return Episode(episode_id=f"{kind}-unknown", code=code, kind=kind,
                               current_state=UNKNOWN, transition_reason="insufficient_evidence")
            ep.previous_state = ep.current_state
            ep.current_state = UNKNOWN
            ep.transition_reason = "unknown_hold"
            return ep

        if active:
            if ep is None:
                previous = self._latest.get(key)
                return self._new(code, kind, as_of, retrigger=bool(previous and previous.invalidated_at))
            ep.previous_state = ep.current_state
            ep.current_state = str(state)
            ep.last_confirmed_at = as_of
            ep.consecutive_confirmations += 1
            ep.transition_reason = "continuing"
            return ep

        # 明确inactive：只使当前active事件失效；重复inactive不新建事件。
        if ep is not None:
            ep.previous_state = ep.current_state
            ep.current_state = str(state)
            ep.invalidated_at = as_of
            ep.transition_reason = "invalidated"
            self._active.pop(key, None)
            return ep
        previous = self._latest.get(key)
        if previous is not None:
            return previous
        return Episode(episode_id=f"{kind}-none", code=code, kind=kind,
                       current_state=str(state), transition_reason="no_active_episode")

    def history(self) -> tuple[Episode, ...]:
        return tuple(self._history)

    def confirmation_delay(self, code: str, kind: str, sessions_between) -> int | None:
        ep = self._latest.get((code, kind))
        if ep is None or ep.first_observed_at is None or ep.last_confirmed_at is None:
            return None
        return sessions_between(ep.first_observed_at, ep.last_confirmed_at)
