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
    # Stage E 实际重跑并复现提交工件
    assert rep["chain_replay"]["e"]["e_runner"] == "PASS"
    assert rep["chain_replay"]["e"]["rerun_structurally_exact"] is True
    assert rep["chain_replay"]["e"]["checkpoints"] > 0
    # 认证清单最终态
    assert rep["chain_replay"]["certified_files"] > 10000
    assert rep["chain_replay"]["certified_roots"] == 2
    # 全 gate 重跑
    g = rep["gates_rerun"]
    assert g["manifest_anchor"] == "PASS"
    assert g["package_gate_count"] == 15 and "G-P-MANIFEST" in g["package_gates"]
    assert "G-P-CROSSSTAGE" in g["package_gates"]
    assert g["join_rows_recount"] > 0
    # 生产计数
    assert rep["production_counts"] == {"REVEAL": 2, "SEAL": 2,
                                        "form": "REVEAL=2 SEAL=2"}
    # anchor 双锚 exact：durable 全量纳入 exact 判定
    d = rep["dual_anchor"]
    rec = d["verdict_head_recomputed"]
    assert set(rec) == {"packaged", "durable_full", "anchored"}
    assert rec["packaged"] == rec["durable_full"] == rec["anchored"]
    assert d["verdict_records"] == d["durable_records"] > 100
    assert len(d["surfaces"]) >= 5


def test_g1_grown_durable_fails_anchor(tmp_path, monkeypatch):
    """终局锚定不允许 durable 增长未被 re-export 吸收：package 快照必须
    与 durable 全量逐字一致，否则 G-ANCHOR fail-closed。"""
    if not (fg.fb.CSR / "corpus" / fg.fb.SID / "ledger.json").is_file():
        pytest.skip("live F artifacts not built yet")
    lines = fg.fp.DURABLE_VERDICTS.read_text().splitlines()
    extra = json.dumps({"runId": fg.RUN_ID, "stage": "F", "iteration": 99,
                        "ts": 9_999_999_999_999, "headCommit": "0" * 39 + "1",
                        "verdict": {"state": "APPROVE", "stage": "F",
                                    "iteration": 99}},
                       ensure_ascii=False, sort_keys=True)
    fake = tmp_path / "verdicts_grown.jsonl"
    fake.write_text("\n".join(lines + [extra]) + "\n")
    monkeypatch.setattr(fg.fp, "DURABLE_VERDICTS", fake)
    with pytest.raises(RuntimeError, match="G-ANCHOR"):
        fg.dual_anchor_exact()


def test_g1_executor_never_declares_final_frozen(tmp_path, monkeypatch):
    """执行者永不宣布 FINAL FROZEN：即便全部前置 verdict 已 APPROVE、
    锚定全 exact，报告也只承载机器实测与 RESERVED 标记 —— 裁决属于
    独立审计。"""
    if not (fg.fb.CSR / "corpus" / fg.fb.SID / "ledger.json").is_file():
        pytest.skip("live F artifacts not built yet")
    rep = fg.final_report(out_path=tmp_path / "g.json")
    detail = rep["verdict_prerequisites"]["stages"]
    complete = all(v == "APPROVE" for v in detail.values())
    assert rep["verdict_prerequisites"]["status"] == (
        "PREREQUISITES-COMPLETE" if complete else "PENDING")
    assert rep["verdict_prerequisites"]["owner"] == "INDEPENDENT-AUDIT"
    assert rep["production_infra_final_frozen"] == "RESERVED-TO-INDEPENDENT-AUDIT"
    assert rep["declared_by_executor"] is False
    # 裁决态翻转（任一前置退回 REVISE）只改变 prerequisites，不改变 RESERVED
    lines = [x for x in fg.fp.DURABLE_VERDICTS.read_text().splitlines()
             if x.strip()]
    flipped = [x for x in lines
               if json.loads(x)["stage"] != "F"
               or json.loads(x)["iteration"] != 18]
    flipped.append(json.dumps({"runId": fg.RUN_ID, "stage": "F",
                               "iteration": 99, "ts": 9_999_999_999_998,
                               "headCommit": "0" * 39 + "2",
                               "verdict": {"state": "REVISE", "stage": "F",
                                           "iteration": 99}},
                              ensure_ascii=False, sort_keys=True))
    fake = tmp_path / "verdicts_f_revise.jsonl"
    fake.write_text("\n".join(flipped) + "\n")
    monkeypatch.setattr(fg.fp, "DURABLE_VERDICTS", fake)
    got = fg.verdict_prerequisites()
    assert got["status"] == "PENDING" and got["stages"]["F"] == "REVISE"


def test_g1_no_g_report_inside_audit_package():
    """F 包不得内嵌 G 终局报告副本 —— 跨阶段自引用必然与同包 verdict
    锚点矛盾（G-P-CROSSSTAGE 的导出侧对应物）。"""
    if not fg.fp.PKG.is_dir():
        pytest.skip("audit package not exported yet")
    hits = [p for p in (fg.fp.PKG / "gates").rglob("g_final_machine_audit.json")]
    assert hits == []
    for p in (fg.fp.PKG / "gates").rglob("*.json"):
        if p.stat().st_size > 2_000_000:
            continue
        try:
            doc = json.loads(p.read_text(errors="replace"))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(doc, dict):
            assert not ({"production_infra_final_frozen",
                         "verdict_prerequisites", "dual_anchor"} & set(doc)), p


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
