import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def test_epoch2_routing_50_and_51(tmp_path):
    # The routing contract is selected by ordinal, not by legacy ledger health.
    (tmp_path/'reviews_epoch2.jsonl').write_text('{}\n')
    import csr8_phase_h_runner as runner
    assert runner.active_reviewer_ledger_for(50, tmp_path)[0].name == 'reviews_epoch2.jsonl'
    assert runner.active_reviewer_ledger_for(51, tmp_path)[0].name == 'reviews_epoch2.jsonl'
    assert runner.active_reviewer_ledger_for(49, tmp_path)[0].name == 'reviews.jsonl'

def test_epoch2_chain_accepts_o50_and_o51_ops(tmp_path):
    import csr8_ledger_epoch2 as e
    p=tmp_path/'r'; e.initialize_epoch(p,tmp_path/'m','a'*64)
    for op in ('SEAL','POST_SEAL','NEXT_REVEAL','ANNOTATION','RECEIPT','SEAL','POST_SEAL'):
        e.append_row(p, {'epoch_id':2,'sequence':len(e.read_rows(p)), 'operation':op, 'ordinal':50 if len(e.read_rows(p))<4 else 51, 'state':'APPROVE'})
    rows=e.validate_rows(e.read_rows(p))
    assert len(rows)==9 and [x['operation'] for x in rows[-5:]] == ['NEXT_REVEAL','ANNOTATION','RECEIPT','SEAL','POST_SEAL']
