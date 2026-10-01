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
    fo.build_outcomes(root, cal_path=cal, price_root=price_root)
    fo.join(root)
    fb.enforce_domain_modes(root, price_root=price_root)
    # Portable §9.1 contract (must hold identically in the audit bridge,
    # which materializes the certified tree without filesystem attributes):
    # protocol attempt artifacts stay exactly 0600 per the frozen C4-D/C6
    # contract, every other annotator file carries no write bits, and all
    # annotator bytes are pinned by the freeze content ledger.
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


def test_f1_domain_readonly_is_uniform_no_exempt_files(sandbox):
    """§9.1 硬条件以无例外谓词执行：G-F-DOMAIN-RO 检查每一个 annotator
    文件（含 0600 协议件）的 group/other 写位；协议件被放宽到 0640 也必须
    当场失败——不存在逃过只读判定的"例外集"。"""
    import stat as stat_mod
    root, _, _ = sandbox
    gates = fb.verify_domain_freeze(root)
    assert set(gates.values()) == {"PASS"}
    # 每个 annotator 文件都无 group/other 写位（统一谓词，无豁免名单）
    for p in fb.annotator_files(root):
        assert stat_mod.S_IMODE(os.stat(p).st_mode) & 0o022 == 0, p
    # 协议 0600 件（旧实现的豁免集成员）被放宽 → G-F-DOMAIN-RO 失败
    exempt = fb.protocol_0600_set(root)
    proto = next(p for p in fb.annotator_files(root)
                 if p.relative_to(root).as_posix() in exempt)
    os.chmod(proto, 0o660)   # group 写位：统一只读谓词必须当场失败
    with pytest.raises(RuntimeError, match="G-F-DOMAIN-RO"):
        fb.verify_domain_freeze(root)
    os.chmod(proto, 0o600)
    assert set(fb.verify_domain_freeze(root).values()) == {"PASS"}


def test_f1_os_probe_attempts_every_annotator_file(sandbox):
    """§9.1 全量真实渗透：uid-65534 对 annotator 域每一个文件做真实
    append 写入尝试 + 每个 annotator 目录做 rogue 建档尝试，全部必须
    PERMISSION_DENIED；抽样探测不允许通过。"""
    root, _, _ = sandbox
    out = fb.verify_blinding(root)
    files = {str(p) for p in fb.annotator_files(root)}
    writes = [a for a in out["attempts"]
              if a.get("op") == "write" and a.get("uid") == 65534]
    assert {a["path"] for a in writes} == files
    creates = [a for a in out["attempts"] if a.get("op") == "create"]
    assert creates and all(a["got"] == "PERMISSION_DENIED" for a in creates)
    assert all(a["got"] == "PERMISSION_DENIED" for a in writes)


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
    assert v["all_pass"] and len(v["gates"]) == 14

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


def test_b5b_package_boundary_and_verdict_chain_tamper(tmp_path, sandbox, monkeypatch):
    """§9.2/§9.4 绕过路径：包内敏感副本可达面 + 真实 verdict 历史的
    逐行哈希链 —— 注入 identity token 或改写任一 verdict 行（即使配平
    MANIFEST 行哈希）都必须被包内复验识破。"""
    root, _, _ = sandbox
    fo.build_outcomes(root)
    fo.join(root)
    # authoritative 形态的真实历史种子（runId/stage 覆盖/F 收尾），使包内
    # 复验走 authoritative 分支并执行逐行哈希链。
    stages = ["B4", "B5", "C1", "C2", "C3", "C4", "C5", "C6", "D", "E", "F"]
    seed = [json.dumps({"runId": fp.RUN_ID, "stage": s, "iteration": i + 1,
                        "ts": 1700000000 + i, "headCommit": "0" * 39 + "1",
                        "verdict": {"state": "REVISE", "stage": s,
                                    "iteration": i + 1}},
                       ensure_ascii=False, sort_keys=True)
            for i, s in enumerate(stages)]
    (tmp_path / "verdicts.jsonl").write_text("\n".join(seed) + "\n")
    monkeypatch.setattr(fp, "DURABLE_VERDICTS", tmp_path / "verdicts.jsonl")
    pkg = tmp_path / "pkg"
    fp.export(pkg, root)
    v = fp.verify(pkg)
    assert v["all_pass"]

    def rehash_manifest(rel):
        m = json.loads((pkg / "MANIFEST.json").read_text())
        entry = next(f for f in m["files"] if f["path"] == rel)
        entry["sha256"] = fp.sha_file(pkg / rel)
        entry["bytes"] = (pkg / rel).stat().st_size
        (pkg / "MANIFEST.json").write_text(
            json.dumps(m, ensure_ascii=False, sort_keys=True, indent=1))

    # 渗透 1：向 annotator 可达的规范化副本注入 identity token，并配平
    # corpus ledger 与 MANIFEST（chain 锚定不受影响）—— 只有包内可达面
    # 全量盲态扫描能识破。
    jl = pkg / "corpus/phase_c_annotation_corpus.jsonl"
    rows = [json.loads(x) for x in jl.read_text().splitlines() if x.strip()]
    rows[0]["evidence_note"] = (rows[0].get("evidence_note") or "") + " see sz.301042"
    jl.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                          for r in rows))
    lp = pkg / "corpus/ledger.json"
    led = json.loads(lp.read_text())
    ent = next(f for f in led["files"] if f["path"] == "phase_c_annotation_corpus.jsonl")
    ent["sha256"] = fp.sha_file(jl)
    ent["bytes"] = jl.stat().st_size
    led["file_hashes"] = {f["path"]: f["sha256"] for f in led["files"]}
    led["totals"] = {"files": len(led["files"]),
                     "bytes": sum(f["bytes"] for f in led["files"])}
    lp.write_text(json.dumps(led, ensure_ascii=False, sort_keys=True, indent=1))
    rehash_manifest("corpus/phase_c_annotation_corpus.jsonl")
    rehash_manifest("corpus/ledger.json")
    with pytest.raises(RuntimeError, match="G-P-BOUNDARY"):
        fp.verify(pkg)

    # 还原渗透 1 的影响：重新导出干净包再做渗透 2（verdict 行改写 +
    # 配平 MANIFEST）—— 逐行哈希链必须识破。
    pkg2 = tmp_path / "pkg2"
    fp.export(pkg2, root)
    assert fp.verify(pkg2)["all_pass"]
    fp2 = pkg2 / "verdicts.jsonl"
    lns = fp2.read_text().splitlines()
    r = json.loads(lns[min(3, len(lns) - 1)])
    r["iteration"] = int(r.get("iteration", 1)) + 40
    r["verdict"]["iteration"] = r["iteration"]   # 内层 envelope 同步配平
    lns[min(3, len(lns) - 1)] = json.dumps(r, ensure_ascii=False, sort_keys=True)
    fp2.write_text("\n".join(lns) + "\n")
    m2 = json.loads((pkg2 / "MANIFEST.json").read_text())
    entry = next(f for f in m2["files"] if f["path"] == "verdicts.jsonl")
    entry["sha256"] = fp.sha_file(fp2)
    entry["bytes"] = fp2.stat().st_size
    (pkg2 / "MANIFEST.json").write_text(
        json.dumps(m2, ensure_ascii=False, sort_keys=True, indent=1))
    with pytest.raises(RuntimeError, match="G-P-VERDICTS-CHAIN"):
        fp.verify(pkg2)

    # 渗透 3（后缀跳过废除证明）：非 JSON 形态泄漏——parquet 二进制尾部
    # 注入带前缀代码，并配平 ledger/MANIFEST —— 原始字节全量扫描必须识破。
    pkg3 = tmp_path / "pkg3"
    fp.export(pkg3, root)
    assert fp.verify(pkg3)["all_pass"]
    pq = pkg3 / "corpus/phase_c_annotation_corpus.parquet"
    pq.write_bytes(pq.read_bytes() + b"\nsz.301042\n")
    lp3 = pkg3 / "corpus/ledger.json"
    led3 = json.loads(lp3.read_text())
    ent3 = next(f for f in led3["files"]
                if f["path"] == "phase_c_annotation_corpus.parquet")
    ent3["sha256"] = fp.sha_file(pq)
    ent3["bytes"] = pq.stat().st_size
    led3["file_hashes"] = {f["path"]: f["sha256"] for f in led3["files"]}
    led3["totals"] = {"files": len(led3["files"]),
                      "bytes": sum(f["bytes"] for f in led3["files"])}
    lp3.write_text(json.dumps(led3, ensure_ascii=False, sort_keys=True, indent=1))

    def rehash3(rel):
        m3 = json.loads((pkg3 / "MANIFEST.json").read_text())
        e3 = next(f for f in m3["files"] if f["path"] == rel)
        e3["sha256"] = fp.sha_file(pkg3 / rel)
        e3["bytes"] = (pkg3 / rel).stat().st_size
        (pkg3 / "MANIFEST.json").write_text(
            json.dumps(m3, ensure_ascii=False, sort_keys=True, indent=1))

    rehash3("corpus/phase_c_annotation_corpus.parquet")
    rehash3("corpus/ledger.json")
    with pytest.raises(RuntimeError,
                       match="G-P-BOUNDARY: identity codes in annotator-surface"):
        fp.verify(pkg3)


def test_b5c_package_stale_gates_and_placeholder_envelope(tmp_path, sandbox, monkeypatch):
    """§9.4 绕过路径：向包内塞入过期 gate 报告（与当前 MANIFEST 冲突的
    fileCount/totalBytes、外来 run id）或退回占位符 envelope 元数据 ——
    语义矛盾必须被复验识破，即使 MANIFEST 行哈希全部配平。"""
    root, _, _ = sandbox
    fo.build_outcomes(root)
    fo.join(root)
    monkeypatch.setattr(fp, "DURABLE_VERDICTS", tmp_path / "verdicts.jsonl")
    pkg = tmp_path / "pkg"
    fp.export(pkg, root)
    assert fp.verify(pkg)["all_pass"]
    # 导出必须自始排除自引用报告与外来 run id 证据
    gate_names = {p.relative_to(pkg / "gates").as_posix()
                  for p in (pkg / "gates").rglob("*") if p.is_file()}
    assert "f_phase_audit_package.json" not in gate_names

    def rehash_manifest(rel):
        m = json.loads((pkg / "MANIFEST.json").read_text())
        target = pkg / rel
        m["files"] = [f for f in m["files"] if f["path"] != rel]
        if target.is_file():
            m["files"].append({"path": rel, "sha256": fp.sha_file(target),
                               "bytes": target.stat().st_size})
            m["files"].sort(key=lambda f: f["path"])
        m["fileCount"] = len(m["files"])
        m["totalBytes"] = sum(f["bytes"] for f in m["files"])
        (pkg / "MANIFEST.json").write_text(
            json.dumps(m, ensure_ascii=False, sort_keys=True, indent=1))

    # 渗透 1：塞入一份"上一轮导出"的过期自报告（fileCount 与当前 MANIFEST
    # 冲突）并配平 MANIFEST —— 语义矛盾必须识破
    stale = pkg / "gates/f_phase_audit_package.json"
    stale.write_text(json.dumps({
        "export": {"chain_head_hash": "0" * 64, "fileCount": 7, "totalBytes": 7},
        "verify": {"all_pass": True}}, sort_keys=True))
    rehash_manifest("gates/f_phase_audit_package.json")
    with pytest.raises(RuntimeError, match="G-P-GATES"):
        fp.verify(pkg)
    stale.unlink()
    rehash_manifest("gates/f_phase_audit_package.json")

    # 渗透 2：外来 run id 的 gate 证据
    foreign = pkg / "gates/foreign_provenance.json"
    foreign.write_text(json.dumps({"run": "audit_19990101000000"}))
    rehash_manifest("gates/foreign_provenance.json")
    with pytest.raises(RuntimeError, match="G-P-GATES: foreign audit run id"):
        fp.verify(pkg)
    foreign.unlink()
    rehash_manifest("gates/foreign_provenance.json")

    # 渗透 3：envelope 元数据退化为占位符
    env_p = pkg / "public_anchor_manifest.json"
    env = json.loads(env_p.read_text())
    real_commit = env["source_commit"]
    env["source_commit"] = "pending"
    env_p.write_text(json.dumps(env, sort_keys=True, indent=1))
    rehash_manifest("public_anchor_manifest.json")
    with pytest.raises(RuntimeError, match="G-P-ENVELOPE"):
        fp.verify(pkg)
    env["source_commit"] = real_commit          # 还原为与其余 envelope 一致
    env_p.write_text(json.dumps(env, sort_keys=True, indent=1))
    rehash_manifest("public_anchor_manifest.json")

    # 渗透 4：row_counts 与包内实际矛盾（配平 MANIFEST 后仍须识破）
    env["row_counts"]["verdict_records"] += 5
    env_p.write_text(json.dumps(env, sort_keys=True, indent=1))
    rehash_manifest("public_anchor_manifest.json")
    with pytest.raises(RuntimeError, match="G-P-ENVELOPE: public_anchor_manifest.json row_counts"):
        fp.verify(pkg)


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
    assert v["all_pass"] and len(v["gates"]) == 14
    dur = fp.DURABLE_VERDICTS.read_text().splitlines()
    assert fp.check_authoritative_history(dur)["records"] == 101
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
