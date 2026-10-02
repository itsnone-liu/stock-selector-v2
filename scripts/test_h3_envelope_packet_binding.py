#!/usr/bin/env python3
"""Regression for H3 envelope packet identity and receipt-gate inputs."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import csr8_phase_c_annotation_seal as c4d
from csr8_phase_h_review_envelope import annotation_envelope_sha256

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    base=ROOT/'data/csr8_phase_c'; cam=base/'h_campaign/hc-46195669974db3b25610bef4d047d927'; h=cam/'h3'; od=base/'c4d_receipts/c4-prod-0002/ordinal-0005'
    events=[json.loads(x) for x in (base/'production/c4-prod-0002/sealing/sealing_log.jsonl').read_text().splitlines() if x.strip()]
    r5=[e for e in events if e['event_type']=='REVEAL_PACKET'][4]
    side=json.loads((od/'national_ctx_v1.json').read_bytes())
    context=side['context_commitment_sha256']; support=sha(od/'context_support_map.json'); draft=sha(od/'annotation_draft.json')
    live=annotation_envelope_sha256(r5['payload']['packet_sha256'],context,support,draft)
    review_packet=annotation_envelope_sha256(sha(h/'packets/ordinal-0005-next-reveal.json'),context,support,draft)
    assert live=='1386ec3b4e555c8611f9474fb3046efdebe3214795f1b019809350b74e83895f',live
    assert review_packet=='76a50fa88ac241e0ef2e7e1fd46e4f621beb8b63796d8970b6989c551acf42a2',review_packet
    assert live != review_packet
    # The corrected active annotation verdict binds live, never review packet.
    v=json.loads((h/'reviews/ANNOTATION.corrected.verdict.json').read_bytes())
    assert v['input_commitment_sha256']==live
    print(json.dumps({'status':'PASS','live_c3_envelope':live,'review_packet_envelope':review_packet,'distinct':True,'active_verdict_binds_live':True},separators=(',',':')))
if __name__=='__main__':main()
