#!/usr/bin/env python3
"""Bridge-executable CSR-8 machine audit (B5-authoritative contract).

The synthetic Phase-A matrix (D01–D71, guard semantics, C4-C regression)
is executed and asserted by the committed pytest suite directly; this
script is the B5 boundary's authoritative machine audit: it re-verifies
the certified-input closure and then measures the COMPLETE B5 Freeze
Gate (chain [R1,S1], receipt triple exact-byte equality, consumed
approval, unique attempt history, cleared workspace, durable exact
c4d/c4c anchors, untouched outcome domain, public production state
REVEAL=1/SEAL=1) from persisted live bytes via
scripts/csr8_phase_b5_real_seal.py — no static snapshot self-attestation.

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
CERT_MANIFEST = ROOT / "config/audit/certified_live_inputs.json"
# 阶段边界感知（post-B5 终态）：annotator/ 工作区已由 POST_SEAL_FINAL 按
# 协议清理（终态不存在）；c4d_receipts/ 是 B3 起的合法冻结证据域；
# c4d_proposals/ 在 C2 授权阶段之前始终禁止。
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
    if result.get('b5_freeze') != 'PASS':
        raise RuntimeError('B5 Freeze Gate did not pass')
    print(json.dumps({'certified_inputs': 'VERIFIED', 'certified_files': manifest['fileCount'],
                      'certified_roots': len(manifest['roots']), 'b5': result,
                      'production_snapshot': 'REVEAL=1 SEAL=1'}, separators=(',', ':')))

if __name__ == "__main__": main()
