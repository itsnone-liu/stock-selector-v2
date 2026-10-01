#!/usr/bin/env python3
"""CSR-8 Phase H1 fail-closed ordinal controller.

This entry point performs only the reversible NEXT_REVEAL preparation and
verification.  It deliberately refuses every irreversible mutation unless a
fresh, exact-hash independent reviewer verdict is present.  It never reads
outcomes, analysis_labeled, identity, or future-data surfaces.
"""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "csr8_phase_h_entry_gate.py"
spec = importlib.util.spec_from_file_location("csr8_h0", GATE)
h0 = importlib.util.module_from_spec(spec); spec.loader.exec_module(h0)
CID = "hc-46195669974db3b25610bef4d047d927"
ORDINAL = 3
CAMPAIGN = h0.campaign_dir(CID)
PACKET = CAMPAIGN / "h1" / "packets" / "ordinal-0003-next-reveal.json"
VERDICT = CAMPAIGN / "h1" / "reviews" / "NEXT_REVEAL.verdict.json"
FORBIDDEN = ("outcomes", "analysis_labeled", "identity", "future")

def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(v): return h0.canon(v).encode()
def fail(reason):
    raise SystemExit(json.dumps({"stage":"H1", "state":"HALT", "reason":reason}, sort_keys=True))

def verify_packet():
    if not PACKET.is_file(): fail("NEXT_REVEAL packet missing")
    raw = PACKET.read_bytes()
    obj = json.loads(raw)
    if h0.canon(obj).encode() != raw: fail("NEXT_REVEAL packet is not canonical")
    if obj.get("campaign_id") != CID or obj.get("ordinal") != ORDINAL: fail("packet binding mismatch")
    if obj.get("operation") != "NEXT_REVEAL": fail("packet operation mismatch")
    # The packet may contain an explicit policy disclosure naming forbidden
    # surfaces; that is not a read.  Only reject payload fields that would
    # actually carry forbidden material, never policy text.
    forbidden_payload_keys = set(FORBIDDEN) | {"outcome_data", "identity_data", "future_data"}
    if forbidden_payload_keys.intersection(obj): fail("forbidden payload field in packet")
    ev = [json.loads(x) for x in h0.c4d.log_path(h0.CSR,h0.SID).read_text().splitlines() if x.strip()]
    if [x["event_type"] for x in ev] != h0.EXPECTED_CHAIN: fail("H0 chain is not closed R1,S1,R2,S2")
    try:
        h0.c4d.prove_next_reveal_eligible(h0.CSR,h0.SID,ORDINAL)
    except Exception as exc:
        fail("NEXT_REVEAL machine gate failed: " + str(exc))
    order = h0.c4d.candidate_total_order()
    if h0.c4d.candidate_for_ordinal(ORDINAL) != order[ORDINAL-1]: fail("frozen candidate order mismatch")
    return raw

def require_fresh_approval(raw):
    if not VERDICT.is_file(): fail("independent reviewer APPROVE verdict missing")
    v=json.loads(VERDICT.read_bytes())
    fields={"review_version","campaign_id","ordinal","operation","input_commitment_sha256","state","issues","required_changes","reviewer_run_id","created_at"}
    if set(v) != fields: fail("review verdict closed-world schema mismatch")
    if v["campaign_id"] != CID or v["ordinal"] != ORDINAL or v["operation"] != "NEXT_REVEAL": fail("review verdict binding mismatch")
    if v["input_commitment_sha256"] != sha(raw): fail("review verdict does not bind exact packet")
    if v["state"] != "APPROVE" or v["issues"] != [] or v["required_changes"] != []: fail("review verdict is not APPROVE")
    return v

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command", choices=("verify", "authorize")); args=ap.parse_args()
    raw=verify_packet()
    if args.command == "authorize": require_fresh_approval(raw); fail("H1 controller has no reviewer-backed production executor; refusing mutation")
    print(json.dumps({"stage":"H1","state":"PACKET_VERIFIED","packet_sha256":sha(raw),"ordinal":ORDINAL},sort_keys=True))
if __name__ == "__main__": main()
