"""V3 P1 观察状态机与持仓独立监控。"""
import pytest

from stock_selector.watchlist import SignalEvent, WatchStore, monitoring_universe


def test_event_is_idempotent_and_no_retrigger_does_not_disappear(tmp_path):
    s = WatchStore(tmp_path / "watch.db")
    ev = SignalEvent("600001", "2026-09-16T15:05:00", "low_volume_advance",
                     "event-v1", {"return": 0.03}, "2026-09-30")
    a = s.record_event(ev)
    b = s.record_event(ev)
    assert a == b
    assert s.current_state(a) == "new"
    assert s.active_codes() == {"600001"}  # 下一天没有重触发也不会消失


def test_recovery_transition_and_audit_history(tmp_path):
    s = WatchStore(tmp_path / "watch.db")
    eid = s.record_event(SignalEvent("600001", "2026-09-16", "price_acceleration",
                                     "v1", {}))
    s.transition(eid, "2026-09-17", "observing", "follow", {}, "v1")
    s.transition(eid, "2026-09-18", "weakening", "low_progress", {}, "v1")
    s.transition(eid, "2026-09-19", "confirmed", "recovered", {}, "v1")
    assert s.current_state(eid) == "confirmed"
    n = s.conn.execute("select count(*) from watch_state where event_id=?", (eid,)).fetchone()[0]
    assert n == 4
    with pytest.raises(ValueError):
        s.transition(eid, "2026-09-20", "new", "bad", {}, "v1")


def test_due_event_expires_with_audited_transition(tmp_path):
    s = WatchStore(tmp_path / "watch.db")
    eid = s.record_event(SignalEvent("600001", "2026-09-16", "x", "v1", {},
                                     expiry_at="2026-09-18"))
    assert s.expire_due("2026-09-19") == 1
    assert s.current_state(eid) == "expired"
    assert s.expire_due("2026-09-20") == 0


def test_held_risk_monitor_is_independent():
    u = monitoring_universe(main_pool=[], watch_codes=[], held_codes=["600009"])
    assert u["scan"] == set()
    assert u["risk_monitor"] == {"600009"}
    assert u["intraday_subscription"] == {"600009"}
