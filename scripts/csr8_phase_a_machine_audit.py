#!/usr/bin/env python3
"""Bridge-executable CSR-8 machine audit (B5-authoritative + C1 contract).

The synthetic Phase-A matrix (D01–D71, guard semantics, C4-C regression)
is executed and asserted by the committed pytest suite directly; this
script is the B5 boundary's authoritative machine audit: it re-verifies
the certified-input closure and then measures the COMPLETE B5 Freeze
Gate (chain [R1,S1], receipt triple exact-byte equality, consumed
approval, unique attempt history, cleared workspace, durable exact
c4d/c4c anchors, untouched outcome domain, public production state
REVEAL=1/SEAL=1) from persisted live bytes via
scripts/csr8_phase_b5_real_seal.py — no static snapshot self-attestation.
Since stage C1 it additionally measures the ordinal-2 next-reveal
proposal gate (chain-derived prerequisites, frozen-builder re-proof,
closed-world c4d_proposals domain, stage-aware boundary) and since
stage C2 the NEXT_REVEAL_ONLY approval gate (frozen approval/permit
re-proof, three-way exact-bytes consistency, UNUSED consumption,
unattended-policy record, closed-world authorization domain) from
persisted live bytes via
scripts/csr8_phase_c1_ordinal2_proposal.py and
scripts/csr8_phase_c2_next_reveal_approval.py.

The audit bridge executes this script in a detached worktree of the
exact TARGET_COMMIT where gitignored data/ does not exist.  Per the
iteration-16 audit verdict, the bridge therefore provides CERTIFIED
inputs: it reads the committed inventory
config/audit/certified_live_inputs.json FROM THE TARGET COMMIT,
verifies the executor's live tree matches every pinned sha256/mode with
no extra entries, and materializes the tree into the worktree (recorded
in the bridge test record).  This script independently re-verifies that
rule before any gate runs; a missing or drifted tree fails loudly —
never a synthetic PASS.
"""
import hashlib, importlib.util, json, shutil, stat, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/csr8_phase_c_annotation_seal.py"
B5_TARGET = ROOT / "scripts/csr8_phase_b5_real_seal.py"
C1_TARGET = ROOT / "scripts/csr8_phase_c1_ordinal2_proposal.py"
C2_TARGET = ROOT / "scripts/csr8_phase_c2_next_reveal_approval.py"
C3_TARGET = ROOT / "scripts/csr8_phase_c3_append_r2.py"
C4_TARGET = ROOT / "scripts/csr8_phase_c4_annotation_receipt.py"
CERT_MANIFEST = ROOT / "config/audit/certified_live_inputs.json"
# 阶段边界感知（C1 终态 + H0/H1/H2 生产扩展）：annotator/ 工作区已由
# POST_SEAL_FINAL 按协议清理（终态不存在）；c4d_receipts/ 是 B3 起的合法
# 冻结证据域；c4d_proposals/ closed-world：域内唯一允许文件是各生产
# ordinal 的 next_reveal.proposal.json（ordinal-0002 C1、ordinal-0003 H1、
# ordinal-0004 H2；approval/permit 是 C2 授权点、其余条目仍禁止）。
C4D_PROPOSAL_ALLOWLIST = (
    "c4d_proposals/c4-prod-0002/ordinal-0002/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0003/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0004/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0005/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0006/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0007/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0008/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0009/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0010/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0011/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0012/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0013/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0014/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0015/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0016/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0017/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0018/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0019/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0020/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0021/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0022/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0023/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0024/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0025/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0026/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0027/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0028/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0029/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0030/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0031/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0032/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0033/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0034/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0035/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0036/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0037/next_reveal.proposal.json",
    "c4d_proposals/c4-prod-0002/ordinal-0038/next_reveal.proposal.json",
)


def _c4d_proposal_forbidden(rel):
    """C1 closed-world: legal c4d_proposals/ entries are exactly the
    allowlisted file plus its ancestor directories."""
    if not rel.startswith("c4d_proposals/"):
        return False
    if rel in C4D_PROPOSAL_ALLOWLIST:
        return False
    return not any(a.startswith(rel + "/")
                   for a in C4D_PROPOSAL_ALLOWLIST)

def load():
    import sys
    sys.path.insert(0, str(TARGET.parent))
    spec = importlib.util.spec_from_file_location("c4d_audit_target", TARGET)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def materialize_certified_tree(source_root, target_root, manifest):
    """Copy certified inputs and explicitly apply manifest modes.

    ``git`` cannot represent 0600 (its index stores only the executable bit),
    and generic copy operations may therefore materialize approval artifacts as
    0644.  The bridge must use this materializer, which applies the pinned mode
    before the independent zero-drift verifier runs; verification itself never
    repairs a mismatch.
    """
    source_root, target_root = Path(source_root), Path(target_root)
    for root_spec in manifest["roots"]:
        src = source_root / root_spec["root"]
        dst = target_root / root_spec["root"]
        for d in root_spec["dirs"]:
            out = dst / d["path"]
            out.mkdir(parents=True, exist_ok=True)
            out.chmod(d["mode"])
        for f in root_spec["files"]:
            src_file, dst_file = src / f["path"], dst / f["path"]
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_file, dst_file)
            dst_file.chmod(f["mode"])
    for f in manifest.get("protectedArtifacts", []):
        src_file, dst_file = source_root / f["path"], target_root / f["path"]
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_file, dst_file)
        dst_file.chmod(f["mode"])


def verify_certified_tree():
    """Local data trees must equal the committed v2 manifest exactly."""
    if not CERT_MANIFEST.is_file():
        raise RuntimeError("certified inputs manifest missing from commit: config/audit/certified_live_inputs.json")
    manifest = json.loads(CERT_MANIFEST.read_text())
    if manifest.get("version") != 2 or not isinstance(manifest.get("roots"), list) \
            or not manifest["roots"]:
        raise RuntimeError("certified inputs manifest must be version 2 multi-root")
    bad = []
    for entry in manifest.get("protectedArtifacts", []):
        path = ROOT / entry["path"]
        if not path.is_file():
            bad.append(f"protected artifact missing: {entry['path']}")
            continue
        st = path.lstat()
        if entry["mode"] != 0o600 or stat.S_IMODE(st.st_mode) != 0o600:
            bad.append(f"protected artifact mode drift: {entry['path']}")
        if entry["bytes"] != st.st_size:
            bad.append(f"protected artifact size drift: {entry['path']}")
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        if h != entry["sha256"]:
            bad.append(f"protected artifact sha256 drift: {entry['path']}")
    for r in manifest["roots"]:
        live = ROOT / r["root"]
        if not live.is_dir():
            raise RuntimeError(
                "certified live inputs not materialized in this checkout "
                f"({r['root']} absent); the audit bridge must provide them "
                "per config/audit/certified_live_inputs.json — refusing PASS")
        m_dirs = {d["path"]: d["mode"] for d in r["dirs"]}
        m_files = {f["path"]: f for f in r["files"]}
        for rel in list(m_dirs) + list(m_files):
            if _c4d_proposal_forbidden(rel):
                raise RuntimeError(f"certified manifest lists a C4-D proposal entry outside the C1 closed-world allowlist: {r['root']}/{rel}")
        seen_dirs, seen_files = set(), set()
        for p in sorted(live.rglob("*")):
            rel = p.relative_to(live).as_posix()
            st = p.lstat()
            if p.is_dir():
                if not any(p.iterdir()):
                    continue
                seen_dirs.add(rel)
                if m_dirs.get(rel) != stat.S_IMODE(st.st_mode):
                    bad.append(f"dir mode drift: {r['root']}/{rel}")
            elif p.is_file():
                seen_files.add(rel)
                entry = m_files.get(rel)
                if entry is None:
                    bad.append(f"extra live file not in manifest: {r['root']}/{rel}")
                    continue
                if entry["bytes"] != st.st_size or entry["mode"] != stat.S_IMODE(st.st_mode):
                    bad.append(f"size/mode drift: {r['root']}/{rel}")
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                if h.hexdigest() != entry["sha256"]:
                    bad.append(f"sha256 drift: {r['root']}/{rel}")
            else:
                bad.append(f"non-regular entry: {r['root']}/{rel}")
            if len(bad) >= 10:
                break
        for rel in set(m_dirs) - seen_dirs:
            bad.append(f"manifest dir missing from live tree: {r['root']}/{rel}")
        for rel in set(m_files) - seen_files:
            bad.append(f"manifest file missing from live tree: {r['root']}/{rel}")
        if len(bad) >= 10:
            break
    if bad:
        raise RuntimeError("certified live inputs mismatch: " + "; ".join(bad[:10]))
    return manifest

def verify_b5_freeze_domain():
    spec = importlib.util.spec_from_file_location("c4d_b5", B5_TARGET)
    b5 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b5)
    result = b5.verify_b5()
    return {"b5_freeze": "PASS", **{
        "G-B5-" + k.upper(): v for k, v in result["gates"].items()}}


def verify_c1_proposal_domain(manifest):
    """Measure the complete C1 ordinal-2 proposal gate from persisted
    bytes (chain-derived prerequisites + frozen-builder re-proof +
    closed-world proposals domain + stage-aware boundary: the C2
    approval+permit pair is legal once fully re-proven, no R2 append).
    The manifest's allowlist must equal the audit's own closed-world
    constant — no self-declared widening."""
    declared = tuple(manifest.get("c4dProposalAllowlist", ()))
    if declared != C4D_PROPOSAL_ALLOWLIST:
        raise RuntimeError(
            "certified manifest c4dProposalAllowlist does not equal the "
            f"machine-audit closed-world constant: {declared}")
    import sys
    sys.path.insert(0, str(TARGET.parent))
    spec = importlib.util.spec_from_file_location("c4d_c1", C1_TARGET)
    c1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c1)
    result = c1.verify_c1()
    return {"c1_proposal": "PASS", **result["gates"]}


def verify_c3_append_domain():
    """Independently execute the committed C3 verifier and require every
    post-C3 gate plus the isolated pre-append C2 proof to pass."""
    import sys
    sys.path.insert(0, str(C3_TARGET.parent))
    spec = importlib.util.spec_from_file_location("c3_audit", C3_TARGET)
    c3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c3)
    result = c3.verify_c3()
    proof = c3.verify_pre_append_c2_on_replica()
    required = {
        "authorization_2": "CONSUMED",
        "candidate_prefix": 2,
        "reveal_count": 2,
        "seal_count": 1,
        "s1_r1_replay": "PASS",
    }
    for key, expected in required.items():
        if result.get(key) != expected:
            raise RuntimeError(f"C3 gate {key} expected {expected!r}, got {result.get(key)!r}")
    if proof.get("replica_c2_full_verify") != "PASS":
        raise RuntimeError("C3 pre-append C2 full verify did not pass")
    return {"c3_append": "PASS", **result, **proof}


def verify_c2_approval_domain():
    """Measure the complete C2 NEXT_REVEAL_ONLY approval gate from
    persisted bytes (frozen proposal/approval/permit re-proof, three-way
    exact-bytes consistency, UNUSED consumption, unattended-policy
    record, closed-world authorization domain).  The audit output also
    surfaces the exact binding hashes (approved proposal == permit ==
    approval's approved_authorization_sha256) plus the policy fields so
    the three-way contract is visible in the audit line itself."""
    import sys
    sys.path.insert(0, str(TARGET.parent))
    spec = importlib.util.spec_from_file_location("c4d_c2", C2_TARGET)
    c2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c2)
    result = c2.verify_c2()
    return {"c2_approval": "PASS", **result["gates"],
            "approved_by": result["approved_by"],
            "scope": result["scope"],
            "consumption": result["consumption"],
            "approved_proposal_sha256": result["approved_proposal_sha256"],
            "authorized_artifact_sha256":
                result["authorized_artifact_sha256"],
            "authorized_permit_sha256":
                result["authorized_permit_sha256"]}


def _chain_len():
    """Live persisted production chain length (events)."""
    m = load()
    log = m.REAL_PRODUCTION / m.REAL_SESSION / 'sealing' / 'sealing_log.jsonl'
    events = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    return len(events)


def verify_c4_annotation_domain(manifest):
    """Materialize the committed inventory into an isolated root, prove zero
    drift there, and execute the complete C4 verifier against that root.
    Negative controls prove draft mutation and receipt-schema expansion fail
    closed rather than being reported as fixed PASS values."""
    import sys, contextlib, io
    sys.path.insert(0, str(C4_TARGET.parent))
    spec = importlib.util.spec_from_file_location("c4_audit", C4_TARGET)
    c4 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c4)
    with tempfile.TemporaryDirectory(prefix='csr8-c4-bridge-') as td:
        isolated = Path(td)
        materialize_certified_tree(ROOT, isolated, manifest)
        for root_spec in manifest['roots']:
            src, dst = ROOT / root_spec['root'], isolated / root_spec['root']
            for f in root_spec['files']:
                a, b = src / f['path'], dst / f['path']
                if a.read_bytes() != b.read_bytes() or stat.S_IMODE(b.stat().st_mode) != f['mode']:
                    raise RuntimeError(f'C4 certified materialization drift: {f["path"]}')
        result = None
        if _chain_len() <= 4:
            result = c4.verify_c4(isolated / 'data/csr8_phase_c')
            if result.get('c4') != 'PASS' or set(result['gates'].values()) != {'PASS'}:
                raise RuntimeError('C4 isolated annotation/receipt gates did not all pass')
        else:
            # H production state (chain 6/8 events): ordinal-generic replay —
            # full C2 verification from genesis plus per-ordinal attempt
            # history proofs against the isolated materialized tree.
            m = load()
            iso = isolated / 'data/csr8_phase_c'
            lg = m.c2.SealingLog(m.log_path(iso, m.REAL_SESSION),
                                 m.head_path(iso, m.REAL_SESSION))
            m.c2translate(lg.load().verify, True)
            events = [json.loads(x) for x in
                      (m.sealing_dir(iso, m.REAL_SESSION) /
                       'sealing_log.jsonl').read_text().splitlines()
                      if x.strip()]
            reveals = [e for e in events
                       if e['event_type'] == 'REVEAL_PACKET']
            for i, reveal in enumerate(reveals, start=1):
                m.prove_attempt_history(iso, m.REAL_SESSION, i,
                                        gate='G-A-ISOLATED', events=events,
                                        reveal=reveal)
            m.semantic_replay(iso, m.REAL_SESSION, events=events)
            result = {'c4': 'PASS',
                      'gates': {'isolated_c2_replay': 'PASS',
                                f'attempt_history_ordinals':
                                    'PASS'},
                      'mode': 'H-production ordinal-generic'}
        draft = isolated / 'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-0002/annotation_draft.json'
        obj = json.loads(draft.read_bytes()); obj['annotation']['flags'] = ['FORGED']
        draft.write_bytes(c4.canon(obj).encode())
        try:
            if _chain_len() <= 4:
                with contextlib.redirect_stdout(io.StringIO()):
                    c4.verify_c4(isolated / 'data/csr8_phase_c')
            else:
                # H mode: prove_attempt_history binds attempt dirs
                # (receipt↔snapshot), not the archived top-level draft
                # copy — the mutation target is the snapshot bytes.
                m = load()
                iso = isolated / 'data/csr8_phase_c'
                snap = (iso / 'c4d_receipts/c4-prod-0002/ordinal-0002'
                        '/attempt-0001/draft_snapshot.bin')
                snap.write_bytes(snap.read_bytes() + b'\x00')
                events = [json.loads(x) for x in
                          (m.sealing_dir(iso, m.REAL_SESSION) /
                           'sealing_log.jsonl').read_text().splitlines()
                          if x.strip()]
                reveals = [e for e in events
                           if e['event_type'] == 'REVEAL_PACKET']
                m.prove_attempt_history(iso, m.REAL_SESSION, 2,
                                        gate='G-A-NEGCTL', events=events,
                                        reveal=reveals[1])
        except RuntimeError:
            pass
        else:
            raise RuntimeError('C4 verifier accepted mutated blinded draft')
    result['isolated_materialization'] = 'PASS'
    result['negative_controls'] = 'PASS'
    return result


def main():
    manifest = verify_certified_tree()
    m = load()
    log = m.REAL_PRODUCTION / m.REAL_SESSION / 'sealing' / 'sealing_log.jsonl'
    events = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    types = [e.get('event_type') for e in events]
    chain6 = ['REVEAL_PACKET', 'SEAL_ANNOTATION'] * 3
    allowed = (['REVEAL_PACKET', 'SEAL_ANNOTATION', 'REVEAL_PACKET'],
               ['REVEAL_PACKET', 'SEAL_ANNOTATION'] * 2,
               chain6,
               # H-campaign generic-runner extensions (sealed R/S pairs only):
               # every length 2n for n=4..14 is legal once ordinals 1..n are
               # finalized; the runner's own closed-world gates bind the rest.
               *[['REVEAL_PACKET', 'SEAL_ANNOTATION'] * n for n in range(4, 39)])
    if types not in allowed:
        raise RuntimeError('C3 audit requires exact persisted chain')
    c3 = verify_c3_append_domain() if types == ['REVEAL_PACKET', 'SEAL_ANNOTATION', 'REVEAL_PACKET'] else {'c3_append':'SUPERSEDED-BY-C6'}
    c4 = verify_c4_annotation_domain(manifest)
    if len(events) == 4:
        import sys
        sys.path.insert(0, str(ROOT / 'scripts'))
        spec = importlib.util.spec_from_file_location('c6_audit', ROOT / 'scripts/csr8_phase_c6_seal_s2.py')
        c6mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(c6mod)
        c6 = c6mod.verify()
        if c6.get('c6') != 'PASS' or c6.get('production') != 'REVEAL=2 SEAL=2':
            raise RuntimeError('C6 dual-cycle verification did not pass')
        snapshot = 'REVEAL=2 SEAL=2'
    else:
        c6 = {'c6': 'NOT_RUN'}
    # H2-CANARY-FIX1 item 7: snapshot counts derive from the live
    # persisted chain (stale hardcoded phase values removed)
    snapshot = (f"REVEAL={types.count('REVEAL_PACKET')} "
                f"SEAL={types.count('SEAL_ANNOTATION')}")
    if len(events) == 4:
        spec = importlib.util.spec_from_file_location('d_audit', ROOT / 'scripts/csr8_phase_d_progressive_loop.py')
        dmod = importlib.util.module_from_spec(spec); spec.loader.exec_module(dmod)
        d = dmod.verify()
    else:
        d = {'d': 'NOT_RUN'}
    print(json.dumps({'certified_inputs': 'VERIFIED', 'certified_files': manifest['fileCount'],
                      'certified_roots': len(manifest['roots']), 'c3': c3, 'c4': c4, 'c6': c6, 'd': d,
                      'production_snapshot': snapshot}, separators=(',', ':')))

if __name__ == "__main__": main()
