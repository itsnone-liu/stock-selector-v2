import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import csr8_ledger_epoch2 as epoch2

HEX64 = 'a' * 64

def _init_campaign(root, ordinal=51):
    cid = 'hc-test'
    camp = root / 'h_campaign' / cid
    camp.mkdir(parents=True)
    (camp / 'reviews.jsonl').write_text('legacy-corrupt\n')
    epoch2.initialize_epoch(camp / 'reviews_epoch2.jsonl', root / 'm.json', 'a' * 64)
    return camp

def test_o51_reviewer_append_routes_to_epoch2(tmp_path, monkeypatch):
    camp = _init_campaign(tmp_path)
    monkeypatch.setattr('pathlib.Path.write_bytes', Path.write_bytes, raising=True)
    import _h3_reviewer_tool as tool
    tool.CAMPAIGN = camp
    tool.EPOCH2_LEDGER = camp / 'reviews_epoch2.jsonl'
    tool.LEDGER = camp / 'reviews.jsonl'
    tool.REVIEWS = camp / 'h49' / 'reviews'
    tool.REVIEWS.mkdir(parents=True)
    legacy_before = (camp / 'reviews.jsonl').read_bytes()
    seq = tool.append_review(51, {'campaign_id': 'hc-test', 'created_at': 't',
                                  'input_commitment_sha256': HEX64,
                                  'operation': 'NEXT_REVEAL', 'ordinal': 51,
                                  'reviewer_run_id': 'r1', 'reviewer_session_id': 's1',
                                  'state': 'APPROVE'})
    assert seq == 2
    assert (camp / 'reviews.jsonl').read_bytes() == legacy_before
    rows = epoch2.validate_rows(epoch2.read_rows(camp / 'reviews_epoch2.jsonl'))
    assert rows[-1]['operation'] == 'NEXT_REVEAL' and rows[-1]['epoch_id'] == 2

def test_o51_correction_routes_to_epoch2(tmp_path):
    camp = _init_campaign(tmp_path)
    import _h3_review_correction as corr
    corr.CAMPAIGN = camp
    corr.EPOCH2_LEDGER = camp / 'reviews_epoch2.jsonl'
    corr.LEDGER = camp / 'reviews.jsonl'
    legacy_before = (camp / 'reviews.jsonl').read_bytes()
    seq = corr.append_review(51, {'campaign_id': 'hc-test', 'created_at': 't',
                                  'input_commitment_sha256': HEX64,
                                  'operation': 'ANNOTATION_CORRECTION', 'ordinal': 51,
                                  'reviewer_run_id': 'r2', 'reviewer_session_id': 's2',
                                  'state': 'APPROVE'})
    assert seq == 2
    assert (camp / 'reviews.jsonl').read_bytes() == legacy_before
    rows = epoch2.read_rows(camp / 'reviews_epoch2.jsonl')
    assert rows[-1]['operation'] == 'ANNOTATION_CORRECTION'

def test_o51_five_ops_fixture_replays(tmp_path):
    camp = tmp_path / 'h_campaign' / 'hc-test2'
    camp.mkdir(parents=True)
    epoch2.initialize_epoch(camp / 'reviews_epoch2.jsonl', tmp_path / 'm2.json', 'b' * 64)
    p = camp / 'reviews_epoch2.jsonl'
    for op in ('NEXT_REVEAL', 'ANNOTATION', 'RECEIPT', 'SEAL', 'POST_SEAL'):
        epoch2.append_row(p, {'epoch_id': 2, 'sequence': len(epoch2.read_rows(p)),
                              'operation': op, 'ordinal': 51, 'state': 'APPROVE'})
    rows = epoch2.validate_rows(epoch2.read_rows(p))
    assert rows[0]['operation'] == 'RECOVERY_GENESIS'
    assert rows[1]['operation'] == 'RECOVERY_CHECKPOINT'
    assert [r['operation'] for r in rows[2:]] == ['NEXT_REVEAL', 'ANNOTATION', 'RECEIPT', 'SEAL', 'POST_SEAL']
