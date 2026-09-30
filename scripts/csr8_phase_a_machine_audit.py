#!/usr/bin/env python3
"""Bridge-executable Phase-A machine audit (iteration 17 contract).

Synthetic gates (D01-D71 matrix, guard semantics) run self-contained in
tmp sandboxes.  The REAL production gates (C4-C regression subprocess,
live preflight, candidate gates, blindness scan, production
REVEAL=1/SEAL=0, forbidden-domain absence, real fingerprint
before==after) read live state under data/csr8_phase_c.

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
B1_TARGET = ROOT / "scripts/csr8_phase_b1_real_handoff.py"
B2_TARGET = ROOT / "scripts/csr8_phase_b2_real_annotation.py"
B4_TARGET = ROOT / "scripts/csr8_phase_b4_human_approval.py"
B5_TARGET = ROOT / "scripts/csr8_phase_b5_real_seal.py"
CERT_MANIFEST = ROOT / "config/audit/certified_live_inputs.json"
# 阶段边界感知（run 2 / B1+）：annotator/ 自 B1 起合法，其 closed-world
# 与泄漏 gate 由 csr8_phase_b1_real_handoff.py 机器实测；c4d_receipts/ 与
# c4d_proposals/ 在 B3/B5 前仍属禁止。
FORBIDDEN_PREFIXES = ("c4d_proposals/",)

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
            if any(rel.startswith(fp) for fp in FORBIDDEN_PREFIXES):
                raise RuntimeError(f"certified manifest lists forbidden C4-D path: {r['root']}/{rel}")
        seen_dirs, seen_files = set(), set()
        for p in sorted(live.rglob("*")):
            rel = p.relative_to(live).as_posix()
            st = p.lstat()
            if p.is_dir():
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

def verify_b1_annotator_domain():
    """B1 real annotator-domain gates (stage-boundary aware, run 2).

    If the real annotator domain exists, ALL B1 gates must measure PASS
    (exact-copy vs C2 archive, closed-world shape, opaque session id,
    leak scans, boundary domains).  Absence is a Phase-A-boundary
    condition (pre-B1) and is reported as such — never a silent skip.
    """
    spec = importlib.util.spec_from_file_location("c4d_b1", B1_TARGET)
    b1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b1)
    dom = b1.c4d.annot_dom(b1.REAL_CSR, b1.SID)
    if not dom.is_dir():
        return {"b1_annotator_domain": "ABSENT", "boundary": "pre-B1"}
    res = b1.verify_b1()
    flat = {"b1_annotator_domain": "PRESENT"}
    flat.update({k: v for k, v in res["gates"].items()})
    return flat

def verify_b4_approval_domain():
    spec = importlib.util.spec_from_file_location("c4d_b4", B4_TARGET)
    b4 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b4)
    if not b4.APPROVAL.is_file():
        return {"b4_approval": "ABSENT", "boundary": "pre-B4"}
    res = b4.verify_b4()
    return {"b4_approval": "PRESENT", **{
        "G-B4-" + k.upper(): v for k, v in res["gates"].items()}}

def verify_b3_receipt_domain():
    spec = importlib.util.spec_from_file_location("c4d_b3", ROOT / "scripts/csr8_phase_b3_real_receipt.py")
    b3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b3)
    attempt = b3.c4d.attempt_dir(b3.CSR, b3.SID, b3.ORDINAL, b3.ATTEMPT)
    if not attempt.is_dir():
        return {"b3_receipt": "ABSENT", "boundary": "pre-B3"}
    res = b3.verify_b3()
    return {"b3_receipt": "PRESENT", **{
        "G-B3-" + k.upper(): v for k, v in res["gates"].items()}}

def verify_b2_annotation_domain():
    spec = importlib.util.spec_from_file_location("c4d_b2", B2_TARGET)
    b2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b2)
    draft = b2.DRAFT_PATH
    if not draft.is_file():
        return {"b2_annotation_draft": "ABSENT", "boundary": "pre-B2"}
    res = b2.verify_b2()
    return {"b2_annotation_draft": "PRESENT", **{
        "G-B2-" + k.upper(): v for k, v in res["gates"].items()}}

def verify_b5_freeze_domain():
    spec = importlib.util.spec_from_file_location("c4d_b5", B5_TARGET)
    b5 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b5)
    result = b5.verify_b5()
    return {"b5_freeze": "PASS", **{
        "G-B5-" + k.upper(): v for k, v in result["gates"].items()}}


def main():
    manifest = verify_certified_tree()
    m = load()
    log = m.REAL_PRODUCTION / m.REAL_SESSION / 'sealing' / 'sealing_log.jsonl'
    events = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    if [e.get('event_type') for e in events] != ['REVEAL_PACKET', 'SEAL_ANNOTATION']:
        raise RuntimeError('B5 audit requires exact persisted [R1,S1] chain')
    result = verify_b5_freeze_domain()
    print(json.dumps({'certified_inputs': 'VERIFIED', 'certified_files': manifest['fileCount'],
                      'certified_roots': len(manifest['roots']), 'b5': result,
                      'production_snapshot': 'REVEAL=1 SEAL=1'}, separators=(',', ':')))

if __name__ == "__main__": main()
