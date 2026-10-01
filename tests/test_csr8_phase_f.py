"""CSR-8 Phase F tests（任务书 §9，run audit_20260930021152297）。

Machine-measured on real transaction surfaces (no fixture snapshots):

* §9.1 immutable annotation corpus — built from the sealed chain + frozen
  receipts domain, hash-ledgered, read-only; real tamper attempts (byte flip,
  mode drift, extra file) must be CAUGHT by verify_corpus;
* §9.2 blinding boundary — analysis rows derive only via the closed-world
  guarded reader; penetration attempts (forbidden keys, identity tokens,
  post-T dates, secret/outcome/labeled reads, HMAC blind-key inversion)
  genuinely execute and fail; negative controls prove each gate detects;
* §9.3 outcome join — blind join keys only, explicit right-censoring
  semantics (censored <=> forward_return null, explicit reason), full
  audit-side recomputation from frozen prices, join completeness, and the
  blinded analysis domain still passes every §9.2 gate after the join;
* §9.4 audit package — one-click export re-verified standalone from package
  bytes alone (frozen chain replay, receipt/approval/authorization/corpus
  bindings, verdicts hash-chain); real package tampering is caught;
* live artifacts — the committed evidence and the live F domains re-verify
  read-only.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import csr8_phase_f_bridge as fb                      # noqa: E402
import csr8_phase_f_outcome_join as fo                # noqa: E402
import csr8_phase_f_audit_package as fp               # noqa: E402
from csr8_phase_f_outcome_join import (CENSOR_PRICE,  # noqa: E402
                                       CENSOR_WINDOW)

SID = fb.SID


@pytest.fixture()
def sandbox(tmp_path):
    root, price_root, cal = fb.make_post_c6_sandbox(tmp_path)
    fb.build_corpus(root)
    fb.build_analysis(root)
    return root, price_root, cal


# ---------------------------------------------------------------- §9.1 ------
def test_f1_immutable_corpus_ledger_and_real_tamper_detection(sandbox):
    root, _, _ = sandbox
    gates = fb.verify_corpus(root)
    assert len(gates) == 5 and set(gates.values()) == {"PASS"}
    ledger = fb.read_ledger(root)
    assert ledger["totals"]["files"] == 11          # 2 pairs x corpus surface
    assert ledger["chain"]["event_count"] == 4

    # real tamper 1: flip one byte in a sealed packet copy (root can write
    # 0o444 — detection must come from the hash ledger)
    pkt = fb.corpus_dir(root) / "pairs/ordinal-0001/reveal_packet.json"
    raw = pkt.read_bytes()
    pkt.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0x01]))
    with pytest.raises(RuntimeError, match="G-F-CORPUS-LEDGER"):
        fb.verify_corpus(root)
    pkt.write_bytes(raw)

    # real tamper 2: relax the read-only mode
    os.chmod(pkt, 0o644)
    with pytest.raises(RuntimeError, match="G-F-CORPUS-RO"):
        fb.verify_corpus(root)
    os.chmod(pkt, 0o444)

    # real tamper 3: extra file inside the closed corpus world
    extra = fb.corpus_dir(root) / "pairs/ordinal-0001/rogue.json"
    extra.write_text("{}")
    with pytest.raises(RuntimeError, match="G-F-CORPUS-WORLD"):
        fb.verify_corpus(root)
    extra.unlink()
    assert set(fb.verify_corpus(root).values()) == {"PASS"}


def test_f1_corpus_bytes_bind_to_chain(sandbox):
    root, _, _ = sandbox
    cdir = fb.corpus_dir(root)
    for ordinal, rev, seal in fb.sealed_pairs(root):
        od = f"ordinal-{ordinal:04d}"
        import hashlib
        pb = (cdir / f"pairs/{od}/reveal_packet.json").read_bytes()
        rb = (cdir / f"pairs/{od}/seal_receipt.json").read_bytes()
        h = hashlib.sha256
        assert h(pb).hexdigest() == rev["payload"]["packet_sha256"]
        assert h(rb).hexdigest() == seal["payload"]["receipt_sha256"]


# ---------------------------------------------------------------- §9.2 ------
def test_f2_blinding_boundary_real_penetration_attempts(sandbox):
    root, _, _ = sandbox
    out = fb.verify_blinding(root)
    assert out["all_pass"]
    by_attempt = {a["attempt"]: a for a in out["attempts"]}
    key_scan = next(a for k, a in by_attempt.items()
                    if k.startswith("forbidden-key"))
    assert key_scan["tried"] > 0 and key_scan["found"] == []
    ident = by_attempt["identity code token scan over all values"]
    assert ident["universe_codes"] > 5000 and ident["found"] == []
    future = by_attempt["post-T date string scan per row"]
    assert future["rows"] == 2 and future["found"] == []
    blocked = [a for a in out["attempts"] if a.get("result") == "BLOCKED"]
    assert len(blocked) == 4                        # secret/outcome/labeled/price
    inv = next(a for k, a in by_attempt.items()
               if k.startswith("HMAC"))
    assert inv["computations"] >= 420 and inv["matches"] == 0  # 84 frozen case keys x 5 salt guesses = full space


def test_f2_negative_controls_each_gate_detects(sandbox):
    root, _, _ = sandbox
    rows_p = fb.analysis_dir(root) / "analysis_rows.jsonl"
    good = rows_p.read_text()
    rows = [json.loads(x) for x in good.splitlines()]

    # control 1: forbidden key injection
    bad = json.loads(good.splitlines()[0])
    bad["panel"]["stock_code"] = "x"
    rows_p.write_text(fb.canon(bad) + "\n" + good.splitlines()[1] + "\n")
    with pytest.raises(RuntimeError, match="G-F-KEYS"):
        fb.verify_blinding(root)
    rows_p.write_text(good)

    # control 2: identity token injection (a real universe code as a value)
    bad = json.loads(good.splitlines()[0])
    bad["panel"]["close_last"] = "sz.002693"
    rows_p.write_text(fb.canon(bad) + "\n" + good.splitlines()[1] + "\n")
    with pytest.raises(RuntimeError, match="G-F-IDENTITY"):
        fb.verify_blinding(root)
    rows_p.write_text(good)

    # control 3: post-T (future) date injection
    bad = json.loads(good.splitlines()[0])
    bad["panel"]["end"] = "2099-01-01"
    rows_p.write_text(fb.canon(bad) + "\n" + good.splitlines()[1] + "\n")
    with pytest.raises(RuntimeError, match="G-F-FUTURE"):
        fb.verify_blinding(root)
    rows_p.write_text(good)
    assert fb.verify_blinding(root)["all_pass"]


# ---------------------------------------------------------------- §9.3 ------
def test_f3_outcome_join_contract_and_censoring(sandbox):
    root, price_root, cal = sandbox
    fo.build_outcomes(root, cal_path=cal, price_root=price_root)
    gates = fo.verify_outcomes(root, cal_path=cal, price_root=price_root)
    assert len(gates) == 6 and set(gates.values()) == {"PASS"}
    rows = fo.read_outcomes(root)
    assert len(rows) == 6 and all(not r["censored"] for r in rows)

    # explicit right-censoring variant: outcome_as_of between horizons
    shutil.rmtree(root / "analysis_labeled", ignore_errors=True)
    fo.build_outcomes(root, cal_path=cal, price_root=price_root,
                      outcome_as_of="2021-04-30")
    assert set(fo.verify_outcomes(root, cal_path=cal,
                                  price_root=price_root).values()) == {"PASS"}
    rows = fo.read_outcomes(root)
    by = {(r["T"], r["horizon_days"]): r for r in rows}
    assert by[("2021-03-08", 5)]["censored"] is False
    assert by[("2021-03-08", 20)]["censored"] is False
    late = by[("2021-03-08", 60)]
    assert late["censored"] and late["forward_return"] is None
    assert late["censor_reason"] == CENSOR_WINDOW
    for h in (5, 20, 60):
        r = by[("2023-10-13", h)]
        assert r["censored"] and r["censor_reason"] == CENSOR_WINDOW

    # join completeness + blinded domain survives the join
    joined = fo.join(root)
    assert joined["manifest"]["n_labeled_rows"] == 6
    assert joined["manifest"]["censored"] == 4
    assert fb.verify_blinding(root)["all_pass"]     # labeled NOT reachable


def test_f3_join_keys_do_not_leak_identity(sandbox):
    root, price_root, cal = sandbox
    fo.build_outcomes(root, cal_path=cal, price_root=price_root)
    fo.join(root)
    for line in (root / "analysis_labeled" / SID /
                 "analysis_labeled.jsonl").read_text().splitlines():
        r = json.loads(line)
        assert {"opaque_case_id", "packet_id"} <= set(r)
        assert not (set(r) & {"code", "stock_code", "symbol", "identity",
                              "case_key", "name"})


# ---------------------------------------------------------------- §9.4 ------
def test_f4_audit_package_standalone_reverify_and_tamper(
        tmp_path, sandbox, monkeypatch):
    root, _, _ = sandbox
    fo.build_outcomes(root)
    fo.join(root)
    monkeypatch.setattr(fp, "DURABLE_VERDICTS", tmp_path / "verdicts.jsonl")
    pkg = tmp_path / "pkg"
    m = fp.export(pkg, root)
    assert m["chain_event_count"] == 4 and m["fileCount"] > 30
    v = fp.verify(pkg)
    assert v["all_pass"] and len(v["gates"]) == 11

    # real tamper 1: flip a packaged receipt byte
    rec = next(p for p in sorted((pkg / "receipts").rglob("receipt.json")))
    raw = rec.read_bytes()
    rec.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0x01]))
    with pytest.raises(RuntimeError):
        fp.verify(pkg)
    rec.write_bytes(raw)

    # real tamper 2: rewrite one verdicts line — detection is two-layer:
    # the manifest byte binding fires first, and the internal hash chain is
    # provably broken (line 1's prev no longer equals sha of tampered line 0)
    vp = pkg / "verdicts.jsonl"
    good = vp.read_text()
    lines = good.splitlines()
    tampered = json.loads(lines[0])
    tampered["commit"] = "deadbeef"          # A16 already says APPROVE — mutate the commit instead
    new_line = fp.canon(tampered)
    nxt = json.loads(lines[1])
    assert nxt["prev_sha256"] != fp.sha(new_line.encode())
    vp.write_text("\n".join([new_line] + lines[1:]) + "\n")
    with pytest.raises(RuntimeError, match="G-P-"):
        fp.verify(pkg)
    vp.write_text(good)

    # real tamper 3: closed world — drop a gate evidence file
    (pkg / "gates" / "verdict_A16.md").unlink()
    with pytest.raises(RuntimeError, match="G-P-MANIFEST"):
        fp.verify(pkg)
    (pkg / "gates" / "verdict_A16.md").write_text("restore")
    # (restored content differs — closed world still fails, proving binding)
    with pytest.raises(RuntimeError):
        fp.verify(pkg)


# ---------------------------------------------------- bypass coverage ------
# 审计方指出的可绕过路径：逐条真实执行并证明被识破。


def _rewrite_ledger_entry(root, rel_path, blob):
    """root 权限下的账本重写攻击：把 ledger 条目改成与篡改字节一致。"""
    lp = fb.ledger_path(root)
    os.chmod(lp, 0o644)
    led = json.loads(lp.read_text())
    for f in led["files"]:
        if f["path"] == rel_path:
            f["sha256"] = fb.sha(blob)
            f["bytes"] = len(blob)
    lp.write_text(json.dumps(led, ensure_ascii=False, sort_keys=True, indent=1))
    os.chmod(lp, 0o444)


def test_b1_corpus_tamper_with_ledger_rewrite_is_caught(sandbox):
    """§9.1 绕过路径：篡改非链 payload 的 corpus 字节并配平账本 —— anchors
    必须仍然锚定到链绑定 receipt（draft_sha256 / registry 语义）而识破。"""
    root, _, _ = sandbox
    # 攻击 1：annotation_draft.json 内容替换 + 账本配平
    od = "pairs/ordinal-0002/annotation_draft.json"
    fp_ = fb.corpus_dir(root) / od
    good = fp_.read_bytes()
    poisoned = json.dumps({"annotation": {"flags": ["FAKE_FLAG"]},
                           "note": "rewritten"}, sort_keys=True).encode()
    fp_.write_bytes(poisoned)
    _rewrite_ledger_entry(root, od, poisoned)
    with pytest.raises(RuntimeError, match="G-F-CORPUS-ANCHORS"):
        fb.verify_corpus(root)
    fp_.write_bytes(good)
    _rewrite_ledger_entry(root, od, good)
    # 攻击 2：registry 语义改写（换 packet 绑定）+ 账本配平
    od = "pairs/ordinal-0002/annotation_session_registry.json"
    fp_ = fb.corpus_dir(root) / od
    good = fp_.read_bytes()
    reg = json.loads(good)
    reg["annotation_sessions"][0]["packet_id"] = "0" * 64
    poisoned = fb.canon(reg).encode()
    fp_.write_bytes(poisoned)
    _rewrite_ledger_entry(root, od, poisoned)
    with pytest.raises(RuntimeError, match="G-F-CORPUS-ANCHORS"):
        fb.verify_corpus(root)
    fp_.write_bytes(good)
    _rewrite_ledger_entry(root, od, good)
    assert set(fb.verify_corpus(root).values()) == {"PASS"}


def test_b2_symlink_escape_is_blocked(sandbox):
    """§9.2 绕过路径：分析域内 symlink 指向 secret —— guarded reader 与
    closed-world 双层都必须拒绝。"""
    root, _, _ = sandbox
    secret = root / "secret" / "secret_salt"
    link = fb.analysis_dir(root) / "escape.json"
    link.symlink_to(secret)
    try:
        with pytest.raises(fb.BlindingRefusal):
            fb.guarded_read(link, fb.analysis_allowed_roots(root))
        with pytest.raises(RuntimeError, match="G-F-NOSYMLINK"):
            fb.verify_blinding(root)
    finally:
        link.unlink()
    assert fb.verify_blinding(root)["all_pass"]


def test_b3_analysis_wholesale_rewrite_with_consistent_manifest(sandbox):
    """§9.2 绕过路径：整体重写 analysis 行并配平 manifest row_sha ——
    行必须是 corpus 的唯一确定性推导结果（G-F-DERIVE）。"""
    root, _, _ = sandbox
    rp = fb.analysis_dir(root) / "analysis_rows.jsonl"
    mp = fb.analysis_dir(root) / "analysis_manifest.json"
    good_rows, good_man = rp.read_text(), mp.read_text()
    rows = [json.loads(x) for x in good_rows.splitlines()]
    rows[0]["panel"]["close_last"] = "999.99"      # 盲态安全但非派生值
    rp.write_text("".join(fb.canon(r) + "\n" for r in rows))
    man = json.loads(good_man)
    man["rows"][0]["row_sha256"] = fb.sha(fb.canon(rows[0]).encode())
    mp.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True, indent=1))
    with pytest.raises(RuntimeError, match="G-F-DERIVE"):
        fb.verify_blinding(root)
    rp.write_text(good_rows)
    mp.write_text(good_man)
    assert fb.verify_blinding(root)["all_pass"]


def test_b4_package_corpus_tamper_with_ledger_and_manifest_rewrite(
        tmp_path, sandbox, monkeypatch):
    """§9.4 绕过路径：包内 corpus 篡改 + 包内账本与 MANIFEST 全部配平 ——
    包内复验仍必须从链绑定 receipt anchors 识破。"""
    root, _, _ = sandbox
    fo.build_outcomes(root)
    fo.join(root)
    monkeypatch.setattr(fp, "DURABLE_VERDICTS", tmp_path / "verdicts.jsonl")
    pkg = tmp_path / "pkg"
    fp.export(pkg, root)
    assert fp.verify(pkg)["all_pass"]
    rel = "pairs/ordinal-0002/annotation_draft.json"
    cp = pkg / "corpus" / rel
    cp.write_bytes(json.dumps({"annotation": {"flags": []}}).encode())
    # 配平包内 ledger
    lp = pkg / "corpus/ledger.json"
    led = json.loads(lp.read_text())
    for f in led["files"]:
        if f["path"] == rel:
            f["sha256"] = fp.sha_file(cp)
            f["bytes"] = cp.stat().st_size
    lp.write_text(json.dumps(led, ensure_ascii=False, sort_keys=True, indent=1))
    # 配平包内 MANIFEST
    mp = pkg / "MANIFEST.json"
    man = json.loads(mp.read_text())
    for f in man["files"]:
        if f["path"] in ("corpus/ledger.json", f"corpus/{rel}"):
            f["sha256"] = fp.sha_file(pkg / f["path"])
            f["bytes"] = (pkg / f["path"]).stat().st_size
    mp.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True, indent=1))
    with pytest.raises(RuntimeError, match="G-P-CORPUS"):
        fp.verify(pkg)


def test_b5_durable_verdicts_are_append_only(tmp_path, monkeypatch):
    """§9.4 绕过路径：重写 durable 审计历史 —— hash 链断链必须拒绝导出。"""
    monkeypatch.setattr(fp, "DURABLE_VERDICTS", tmp_path / "verdicts.jsonl")
    lines = fp.load_or_bootstrap_verdicts()
    assert len(lines) == 11
    poisoned = json.loads(lines[5])
    poisoned["verdict"] = "APPROVE"
    dv = tmp_path / "verdicts.jsonl"
    dv.write_text("\n".join([fp.canon(poisoned)] + lines[6:]) + "\n")
    with pytest.raises(RuntimeError, match="hash chain broken"):
        fp.load_or_bootstrap_verdicts()


def test_b6_labeled_join_tamper_with_consistent_manifest(sandbox):
    """§9.3/§9.4 绕过路径：改 labeled 行 + 配平 join_manifest 计数 ——
    join 必须是 analysis×outcomes 的唯一确定性复推导。"""
    root, _, _ = sandbox
    fo.build_outcomes(root)
    fo.join(root)
    lp = fo.labeled_dir(root) / "analysis_labeled.jsonl"
    good = lp.read_text()
    rows = [json.loads(x) for x in good.splitlines()]
    rows[0]["forward_return"] = "9.9999999999"
    lp.write_text("".join(fb.canon(r) + "\n" for r in rows))
    with pytest.raises(RuntimeError, match="G-F-JOIN-CONTRACT"):
        fo.verify_outcomes(root)
    lp.write_text(good)
    assert set(fo.verify_outcomes(root).values()) == {"PASS"}


# ---------------------------------------------------------------- live ------
def test_f5_live_artifacts_and_evidence_reverify_readonly():
    if not (fb.CSR / "corpus" / SID / "ledger.json").is_file():
        pytest.skip("live F artifacts not built yet")
    assert set(fb.verify_corpus(fb.CSR).values()) == {"PASS"}
    assert fb.verify_blinding(fb.CSR)["all_pass"]
    assert set(fo.verify_outcomes(fb.CSR).values()) == {"PASS"}
    v = fp.verify(fp.PKG)
    assert v["all_pass"] and len(v["gates"]) == 11
    dur = fp.DURABLE_VERDICTS.read_text().splitlines()
    assert fp.check_verdict_chain(dur)["stage"] == "F"
    ev = json.loads((ROOT / "docs/audit/evidence/f_phase_bridge.json").read_text())
    head = json.loads((fb.CSR / "production" / SID / "sealing" /
                       "sealing_log.head.json").read_text())
    assert ev["corpus"]["chain_head_hash"] == head["head_hash"]
    assert set(ev["corpus"]["gates"].values()) == {"PASS"}
    assert set(ev["analysis"]["gates"].values()) == {"PASS"}
    assert set(ev["outcomes"]["gates"].values()) == {"PASS"}
    assert any(c["censored"] for c in ev["outcomes"]["censoring_variant"]["rows"])
    pkgev = json.loads((ROOT / "docs/audit/evidence/"
                        "f_phase_audit_package.json").read_text())
    assert pkgev["verify"]["all_pass"]
    assert pkgev["verify"]["head_hash"] == head["head_hash"]
