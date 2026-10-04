"""Read-only wiring contracts for the frozen Round-1 Shadow runtime.

Adapters are deliberately dependency-injected. They must implement the frozen outputs;
this module does not contain research thresholds and never imports research engines.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

class FrozenAdapter(Protocol):
    def __call__(self, asof: str) -> Mapping[str, Any]: ...

@dataclass(frozen=True)
class RuntimeAdapters:
    load_market_state: FrozenAdapter
    load_sector_states: FrozenAdapter
    load_candidate_pool: FrozenAdapter
    load_episode_state: FrozenAdapter
    load_lifecycle_state: FrozenAdapter
    derive_primary_zone: FrozenAdapter
    derive_frozen_decisions: FrozenAdapter

    def stages(self, asof: str) -> dict[str, Callable[[], Mapping[str, Any]]]:
        """Expose only frozen stage outputs to cd_shadow_daily.run_shadow_day."""
        def l3():
            x = dict(self.load_candidate_pool(asof))
            return {"candidate_pool": list(x.get("candidates", [])), "candidate_source": x.get("candidate_source", {})}
        def l4():
            e = self.load_episode_state(asof); l = self.load_lifecycle_state(asof)
            return {"episodes": list(e.get("episodes", [])), "lifecycle": list(l.get("lifecycle", []))}
        return {
            "ingest": lambda: {"input_manifest": {"data_asof": asof}},
            "pit": lambda: {"pit": {"data_asof": asof, "future_data_rejected": True}},
            "l1": lambda: {"market_state": dict(self.load_market_state(asof))},
            "l2": lambda: {"sector_states": dict(self.load_sector_states(asof))},
            "l3": l3, "l4": l4,
            "primary_zone": lambda: {"primary_zone": self.derive_primary_zone(asof)},
            "decision": lambda: dict(self.derive_frozen_decisions(asof)),
        }

def assert_asof(record: Mapping[str, Any], asof: str) -> None:
    """Fail closed when an adapter advertises a future timestamp."""
    for key in ("data_asof", "asof", "decision_asof"):
        value = record.get(key)
        if value is not None and str(value)[:10] > asof:
            raise ValueError(f"future {key}: {value} > {asof}")

def parity_check(reference: Mapping[str, Any], actual: Mapping[str, Any]) -> dict:
    """Compare frozen semantic fields; no numeric outcome comparison is involved."""
    fields = ("market_state", "sector_states", "candidate_pool", "candidate_source", "episodes", "lifecycle", "primary_zone", "decisions", "positions", "terminals")
    checks = {field: reference.get(field) == actual.get(field) for field in fields if field in reference or field in actual}
    return {"gate": "G-SHADOW-PARITY", "status": "PARITY_PASS" if all(checks.values()) else "PARITY_FAIL", "checks": checks}
