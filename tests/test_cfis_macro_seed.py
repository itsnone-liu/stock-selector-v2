"""Real seed metadata regression checks; no network."""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def events():
    return json.loads((ROOT / "docs/research/cfis/macro_events_seed.json").read_text())["events"]


def test_overseas_diversity():
    rows = events()
    assert len(rows) == 11
    fed = [e for e in rows if e["event_type"] == "fed_monetary_policy"]
    assert {e["policy_action"] for e in fed} == {"raise", "hold", "cut"}
    for e in fed:
        assert datetime.fromisoformat(e["published_at"]) == datetime.fromisoformat(e["first_usable_at"])
        assert e["surprise"] is None
        assert e["implementation_source_url"].endswith("a1.htm")


def test_conflict_not_independent_windows():
    rows = [e for e in events() if e["event_type"].startswith("geopolitical_")]
    assert len(rows) == 2
    assert len({e["event_cluster_id"] for e in rows}) == 1
    assert all(e.get("effective_at_semantics") for e in rows)


def test_trade_chain_preserves_upgrade_then_easing():
    rows = [e for e in events() if e['event_cluster_id'] == 'US_CHINA_TRADE_CHAIN_2025']
    assert {e['event_type'] for e in rows} == {'trade_escalation', 'trade_deescalation'}
    rows.sort(key=lambda e: e['first_usable_at'])
    assert rows[0]['event_id'] == 'CN_US_TARIFF_RESPONSE_20250404'
    assert rows[0]['scheduled_not_final_effective'] is True
