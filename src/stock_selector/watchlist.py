"""V3 P1 持续观察状态机与 append-only 事件账本。

先提供独立、可测试的持久化内核；不改变生产选股规则。状态变化只由显式事件驱动，
“今天没再次触发”不会让候选消失。持仓风险监控集合独立于主池/观察池。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

STATES = {"new", "observing", "confirmed", "weakening", "invalidated", "expired"}
ACTIVE_STATES = {"new", "observing", "confirmed", "weakening"}
ALLOWED = {
    "new": {"observing", "invalidated", "expired"},
    "observing": {"confirmed", "weakening", "invalidated", "expired"},
    "confirmed": {"observing", "weakening", "invalidated", "expired"},
    "weakening": {"observing", "confirmed", "invalidated", "expired"},
    "invalidated": set(), "expired": set(),
}


@dataclass(frozen=True)
class SignalEvent:
    code: str
    detection_at: str
    event_type: str
    event_version: str
    evidence: dict
    expiry_at: str | None = None
    event_id: str = ""


class WatchStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript("""
        create table if not exists signal_event(
          event_id text primary key, code text not null, detection_at text not null,
          event_type text not null, event_version text not null, evidence text not null,
          expiry_at text, status text not null default 'active', created_at text default current_timestamp
        );
        create unique index if not exists uq_signal_event
          on signal_event(code,detection_at,event_type,event_version);
        create table if not exists watch_state(
          id integer primary key autoincrement, code text not null, event_id text not null,
          as_of text not null, previous_state text, current_state text not null,
          reason text not null, evidence text not null, rule_version text not null,
          created_at text default current_timestamp
        );
        create index if not exists ix_watch_latest on watch_state(code,event_id,as_of,id);
        create table if not exists monthly_state(
          code text not null, as_of text not null, trend_pass integer not null,
          reason text not null, metrics text not null, state_version text not null,
          primary key(code,as_of,state_version)
        );
        """)
        self.conn.commit()

    def record_event(self, event: SignalEvent, initial_state: str = "new") -> str:
        if initial_state not in STATES:
            raise ValueError(f"invalid state: {initial_state}")
        eid = event.event_id or uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{event.code}|{event.detection_at}|{event.event_type}|{event.event_version}").hex
        self.conn.execute("""insert or ignore into signal_event
          (event_id,code,detection_at,event_type,event_version,evidence,expiry_at)
          values(?,?,?,?,?,?,?)""",
          (eid, event.code, event.detection_at, event.event_type, event.event_version,
           json.dumps(event.evidence, ensure_ascii=False, sort_keys=True), event.expiry_at))
        exists = self.conn.execute("select 1 from watch_state where event_id=?", (eid,)).fetchone()
        if not exists:
            self.conn.execute("""insert into watch_state
              (code,event_id,as_of,previous_state,current_state,reason,evidence,rule_version)
              values(?,?,?,?,?,?,?,?)""",
              (event.code, eid, event.detection_at, None, initial_state, "event_detected",
               json.dumps(event.evidence, ensure_ascii=False, sort_keys=True), event.event_version))
        self.conn.commit()
        return eid

    def current_state(self, event_id: str) -> str | None:
        row = self.conn.execute("""select current_state from watch_state
          where event_id=? order by as_of desc,id desc limit 1""", (event_id,)).fetchone()
        return row[0] if row else None

    def transition(self, event_id: str, as_of: str, new_state: str, reason: str,
                   evidence: dict, rule_version: str) -> None:
        if new_state not in STATES:
            raise ValueError(f"invalid state: {new_state}")
        event = self.conn.execute("select code from signal_event where event_id=?", (event_id,)).fetchone()
        if not event:
            raise KeyError(event_id)
        old = self.current_state(event_id)
        if old is None or new_state not in ALLOWED[old]:
            raise ValueError(f"invalid transition: {old}->{new_state}")
        self.conn.execute("""insert into watch_state
          (code,event_id,as_of,previous_state,current_state,reason,evidence,rule_version)
          values(?,?,?,?,?,?,?,?)""",
          (event[0], event_id, as_of, old, new_state, reason,
           json.dumps(evidence, ensure_ascii=False, sort_keys=True), rule_version))
        if new_state in {"invalidated", "expired"}:
            self.conn.execute("update signal_event set status=? where event_id=?", (new_state, event_id))
        self.conn.commit()

    def active_codes(self) -> set[str]:
        rows = self.conn.execute("""select w.code,w.current_state from watch_state w
          join (select event_id,max(id) id from watch_state group by event_id) x on w.id=x.id""").fetchall()
        return {r[0] for r in rows if r[1] in ACTIVE_STATES}

    def record_monthly_state(self, code: str, as_of: str, trend_pass: bool,
                             reason: str, metrics: dict, state_version: str) -> None:
        self.conn.execute("""insert or replace into monthly_state
          (code,as_of,trend_pass,reason,metrics,state_version) values(?,?,?,?,?,?)""",
          (code, as_of, int(trend_pass), reason,
           json.dumps(metrics, ensure_ascii=False, sort_keys=True), state_version))
        self.conn.commit()

    def monthly_pool(self, as_of: str, state_version: str) -> set[str]:
        rows = self.conn.execute("""select code from monthly_state
          where as_of=? and state_version=? and trend_pass=1""",
          (as_of, state_version)).fetchall()
        return {r[0] for r in rows}


def monitoring_universe(main_pool: Iterable[str], watch_codes: Iterable[str],
                        held_codes: Iterable[str]) -> dict[str, set[str]]:
    """三个集合分开返回；held 永远进入 risk_monitor，不被主池/观察池筛掉。"""
    main, watch, held = set(main_pool), set(watch_codes), set(held_codes)
    return {"scan": main | watch, "deep_check": watch, "risk_monitor": held,
            "intraday_subscription": watch | held}
