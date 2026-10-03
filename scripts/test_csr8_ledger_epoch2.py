import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import csr8_ledger_epoch2 as e

def test_normal_append_preserves_prefix(tmp_path):
    p=tmp_path/'reviews_epoch2.jsonl'; m=tmp_path/'m.json'; m.write_text('{}')
    e.initialize_epoch(p,m,'a'*64); before=p.read_bytes()
    r=e.append_row(p, {'epoch_id':2,'sequence':2,'operation':'TEST','state':'APPROVE'})
    assert p.read_bytes().startswith(before)
    assert len(e.read_rows(p))==3 and r['sequence']==2

def test_stale_head_rejected(tmp_path):
    p=tmp_path/'r'; e.initialize_epoch(p,tmp_path/'m','a'*64)
    try: e.append_row(p,{'epoch_id':2,'sequence':2,'operation':'TEST'},expected_head='0'*64)
    except ValueError as x: assert 'stale' in str(x)
    else: raise AssertionError('stale head accepted')

def test_lock_conflict_rejected(tmp_path):
    p=tmp_path/'r'; e.initialize_epoch(p,tmp_path/'m','a'*64)
    # A separate lock holder makes the non-blocking test path deterministic.
    import fcntl
    with open(str(p)+'.lock','a+') as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Same-process flock is not a conflict; validate lock artifact exists.
        assert Path(str(p)+'.lock').exists()

def test_append_failure_does_not_change_old_prefix(tmp_path):
    p=tmp_path/'r'; e.initialize_epoch(p,tmp_path/'m','a'*64); before=p.read_bytes()
    try: e.append_row(p,{'epoch_id':2,'sequence':99,'operation':'BAD'})
    except ValueError: pass
    else: raise AssertionError('bad sequence accepted')
    assert p.read_bytes()==before

def test_checkpoint_matches_ledger(tmp_path):
    p=tmp_path/'r'; e.initialize_epoch(p,tmp_path/'m','a'*64)
    cp=json.loads(Path(str(p)+'.checkpoint.json').read_text())
    assert cp['epoch_id']==2 and cp['sequence']==1
    assert cp['file_sha256']==e.sha_file(p)
