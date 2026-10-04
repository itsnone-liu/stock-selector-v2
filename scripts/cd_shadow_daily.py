#!/usr/bin/env python3
"""CD Round-1 frozen-policy shadow runner.

This runner is deliberately an observation system: it writes no orders and no capital
instructions. Production adapters may supply the seven stage payloads; missing/failed
stages invalidate the day rather than permitting partial decisions.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("ingest", "pit", "l1", "l2", "l3", "l4", "primary_zone", "decision")
FILES = ("run_manifest.json", "input_manifest.json", "market_state.json",
         "sector_states.json.gz", "candidate_pool.json.gz", "episodes.json.gz",
         "lifecycle.json.gz", "decisions.json.gz", "positions.json.gz",
         "accounting_report.json", "artifact_manifest.json")

class ShadowInvalid(RuntimeError):
    pass

def canon(x: Any) -> bytes:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())

def json_bytes(x: Any) -> bytes:
    return canon(x) + b"\n"

def write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ShadowInvalid(f"immutable artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

def check_accounting(payload: Mapping[str, Any]) -> dict:
    """Return a fail-closed accounting report; payload is stage output, not a guess."""
    decisions = list(payload.get("decisions", []))
    positions = list(payload.get("positions", []))
    terminals = list(payload.get("terminals", []))
    opened = int(payload.get("opened_positions", sum(1 for x in decisions if x.get("decision") == "ENTER")))
    closed = int(payload.get("closed_positions", sum(1 for x in terminals if x.get("reason"))))
    current = int(payload.get("current_open_positions", len(positions)))
    checks = {
        "position_conservation": opened == closed + current,
        "decision_episode_binding": all(bool(x.get("episode_id")) for x in decisions),
        "terminal_reason_exactly_one": all(sum(bool(x.get(k)) for k in ("reason", "terminal_reason")) == 1 for x in terminals),
        "no_orphan_open_position": all(bool(x.get("episode_id")) for x in positions),
        "no_silent_terminal": len(terminals) == int(payload.get("terminal_episode_count", len(terminals))),
        "reduce_to_zero_recorded": int(payload.get("reduce_to_zero", 0)) == int(payload.get("reduce_to_zero_close_records", payload.get("reduce_to_zero", 0))),
    }
    return {"gate": "G-SHADOW-ACCOUNTING", "status": "SHADOW_VALID" if all(checks.values()) else "SHADOW_INVALID", "checks": checks,
            "counts": {"opened": opened, "closed": closed, "current_open": current, "decisions": len(decisions), "terminals": len(terminals)}}

def run_shadow_day(day: str, out_root: Path, *, git_commit: str = "unknown", policy_version: str = "round1-frozen-v1", freeze_version: str = "round1-freeze-v1", stages: Mapping[str, Callable[[], Mapping[str, Any]]] | None = None, metadata: Mapping[str, Any] | None = None) -> dict:
    """Run all stages and atomically freeze a date directory.

    Each stage must return a mapping. Exceptions, missing stages, and missing required
    outputs produce SHADOW_INVALID and no decision-bearing partial-success status.
    """
    if datetime.fromisoformat(day).date().isoformat() != day:
        raise ValueError("day must be YYYY-MM-DD")
    root = Path(out_root); target = root / day
    existing_manifest = target / "run_manifest.json"
    if existing_manifest.exists():
        created_at = json.loads(existing_manifest.read_text()).get("created_at", "")
    else:
        created_at = datetime.now(timezone.utc).isoformat()
    data_asof = day; decision_asof = f"{day}T23:59:59Z"
    run = {"status":"SHADOW_INVALID", "data_asof":data_asof, "decision_asof":decision_asof, "created_at":created_at, "git_commit":git_commit, "policy_version":policy_version, "freeze_version":freeze_version, "orders_allowed":False, "capital_allowed":False, "stages":{}}
    stages = stages or {}
    payload: dict[str, Any] = {}
    try:
        for name in STAGES:
            fn = stages.get(name)
            if fn is None: raise ShadowInvalid(f"missing stage: {name}")
            result = fn()
            if not isinstance(result, Mapping): raise ShadowInvalid(f"stage {name} did not return mapping")
            run["stages"][name] = "OK"; payload.update(result)
    except Exception as exc:
        run["error"] = {"type": type(exc).__name__, "message": str(exc)}
        accounting = {"gate":"G-SHADOW-ACCOUNTING", "status":"SHADOW_INVALID", "checks":{}, "counts":{}}
        write_immutable(target / "run_manifest.json", json_bytes(run))
        write_immutable(target / "accounting_report.json", json_bytes(accounting))
        return {"status":"SHADOW_INVALID", "day":day, "error":run["error"]}
    accounting = check_accounting(payload)
    run["status"] = accounting["status"]
    run["accounting_status"] = accounting["status"]
    docs = {
        "run_manifest.json": run,
        "input_manifest.json": dict(metadata or {}, data_asof=data_asof, decision_asof=decision_asof),
        "market_state.json": payload.get("market_state", {}),
        "sector_states.json.gz": payload.get("sector_states", {}),
        "candidate_pool.json.gz": payload.get("candidate_pool", []),
        "episodes.json.gz": payload.get("episodes", []),
        "lifecycle.json.gz": payload.get("lifecycle", []),
        "decisions.json.gz": payload.get("decisions", []),
        "positions.json.gz": payload.get("positions", []),
        "accounting_report.json": accounting,
    }
    import gzip
    for name, value in docs.items():
        raw = json_bytes(value)
        if name.endswith(".gz"): raw = gzip.compress(raw, mtime=0)
        write_immutable(target / name, raw)
    manifest = {"day": day, "status": run["status"], "artifacts": {name: sha256_file(target / name) for name in docs}}
    write_immutable(target / "artifact_manifest.json", json_bytes(manifest))
    return {"status": run["status"], "day": day, "path": str(target), "accounting": accounting}

def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--day", default=date.today().isoformat()); p.add_argument("--out", default="shadow")
    a = p.parse_args(); result = run_shadow_day(a.day, ROOT / a.out)
    print(json.dumps(result, ensure_ascii=False, indent=2)); raise SystemExit(0 if result["status"] == "SHADOW_VALID" else 2)
if __name__ == "__main__": main()
