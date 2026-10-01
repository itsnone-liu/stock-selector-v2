"""CSR-8 Phase G tests — 最终机器审计（任务书终局 gate，run audit_20260930021152297）。

Machine-measured executor report only:

* every measured section (chain replay incl. the B5-era view rerun, all live
  gates, certification manifest final state, production counts REVEAL=2/SEAL=2,
  dual anchor exactness, audit package integrity) must PASS;
* PRODUCTION INFRA FINAL FROZEN is never declared by the executor — the
  report carries RESERVED-TO-INDEPENDENT-AUDIT regardless of verdict state;
* verdict prerequisites are reported honestly: status flips to COMPLETE only
  when every required stage's authoritative verdict is APPROVE.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import csr8_phase_g_final_machine_audit as fg   # noqa: E402


def _live_ready():
    return (ROOT / "docs/audit/evidence/g_final_machine_audit.json").is_file() \
        or (fg.fb.CSR / "corpus" / fg.fb.SID / "ledger.json").is_file()


def test_g1_final_report_measured_sections_pass(tmp_path):
    if not (fg.fb.CSR / "corpus" / fg.fb.SID / "ledger.json").is_file():
        pytest.skip("live F artifacts not built yet")
    rep = fg.final_report(out_path=tmp_path / "g.json")
    # 全链 replay（含 B5 时期视图全 gate 重放）
    assert rep["chain_replay"]["events"] == ["REVEAL_PACKET", "SEAL_ANNOTATION",
                                             "REVEAL_PACKET", "SEAL_ANNOTATION"]
    b5 = rep["chain_replay"]["b5_freeze"]
    assert b5["b5_freeze"] == "PASS"
    assert all(v == "PASS" for v in b5.values())
    assert rep["chain_replay"]["c6"]["production"] == "REVEAL=2 SEAL=2"
    assert rep["chain_replay"]["d"]["d"] == "PASS"
    # 认证清单最终态
    assert rep["chain_replay"]["certified_files"] > 10000
    assert rep["chain_replay"]["certified_roots"] == 2
    # 全 gate 重跑
    g = rep["gates_rerun"]
    assert g["manifest_anchor"] == "PASS"
    assert g["package_gate_count"] == 14 and "G-P-MANIFEST" in g["package_gates"]
    assert g["join_rows_recount"] > 0
    # 生产计数
    assert rep["production_counts"] == {"REVEAL": 2, "SEAL": 2,
                                        "form": "REVEAL=2 SEAL=2"}
    # anchor 双锚 exact
    d = rep["dual_anchor"]
    heads = set(d["verdict_head_recomputed"].values())
    assert d["verdict_chain_head"] in heads
    assert len(d["surfaces"]) >= 5
    rec = d["verdict_head_recomputed"]
    assert (rec["packaged"] == rec["anchored"]
            and rec["durable_prefix"] == rec["anchored"])
    assert d["verdict_records"] <= d["durable_records"]


def test_g1_executor_never_declares_final_frozen(tmp_path, monkeypatch):
    """执行者永不宣布 FINAL FROZEN：即使全部前置 verdict 已 APPROVE，
    报告也只承载机器实测与 RESERVED 标记 —— 裁决属于独立审计。"""
    if not (fg.fb.CSR / "corpus" / fg.fb.SID / "ledger.json").is_file():
        pytest.skip("live F artifacts not built yet")
    pkg_lines = [x for x in (fg.fp.PKG / "verdicts.jsonl").read_text()
                 .splitlines() if x.strip()]
    stages = {"B5": 900, "C6": 901, "D": 902, "E": 903, "F": 904}
    extra = [json.dumps({"runId": fg.RUN_ID, "stage": s, "iteration": 99,
                         "ts": 1759000000 + i, "headCommit": "0" * 39 + "1",
                         "verdict": {"state": "APPROVE", "stage": s,
                                     "iteration": 99}},
                        ensure_ascii=False, sort_keys=True)
             for i, (s, _) in enumerate(stages.items())]
    fake = tmp_path / "verdicts_all_approve.jsonl"
    fake.write_text("\n".join(pkg_lines + extra) + "\n")
    monkeypatch.setattr(fg.fp, "DURABLE_VERDICTS", fake)
    rep = fg.final_report(out_path=tmp_path / "g2.json")
    assert rep["verdict_prerequisites"]["status"] == "PREREQUISITES-COMPLETE"
    assert rep["verdict_prerequisites"]["owner"] == "INDEPENDENT-AUDIT"
    assert rep["production_infra_final_frozen"] == "RESERVED-TO-INDEPENDENT-AUDIT"
    assert rep["declared_by_executor"] is False
    # packaged 历史仍是 durable 的 exact 前缀（verdict 只增不改写）
    assert rep["dual_anchor"]["verdict_records"] == len(pkg_lines)
    assert rep["dual_anchor"]["durable_records"] == len(pkg_lines) + 5


def test_g1_pending_prerequisite_reported_honestly(tmp_path, monkeypatch):
    if not (fg.fb.CSR / "corpus" / fg.fb.SID / "ledger.json").is_file():
        pytest.skip("live F artifacts not built yet")
    last = {}
    for ln in fg.fp.DURABLE_VERDICTS.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            last[r["stage"]] = r["verdict"]["state"]
    detail = {s: last.get(s) for s in fg.PREREQ_STAGES}
    want = ("PREREQUISITES-COMPLETE"
            if all(v == "APPROVE" for v in detail.values()) else "PENDING")
    got = fg.verdict_prerequisites()
    assert got["status"] == want and got["stages"] == detail
    # 机器实测部分与前置裁决解耦：declared_by_executor 恒为 False
    assert got["owner"] == "INDEPENDENT-AUDIT"
