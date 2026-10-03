#!/usr/bin/env python3
"""CSR-8 ledger Recovery Epoch 2 and guarded append writer.

Epoch 2 is an explicit boundary: it never reconstructs or links the lost
legacy byte chain.  Its genesis has prev_review_hash=null and its checkpoint
binds a frozen recovery manifest.
"""
import fcntl, hashlib, json, os, tempfile, errno
from pathlib import Path

GENESIS = 'RECOVERY_GENESIS'
CHECKPOINT = 'RECOVERY_CHECKPOINT'

def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p): return sha_bytes(Path(p).read_bytes())

def row_hash(row):
    body = dict(row); body.pop('review_hash', None)
    return sha_bytes(canon(body).encode())

def read_rows(path):
    p=Path(path)
    if not p.exists(): return []
    return [json.loads(x) for x in p.read_bytes().splitlines() if x.strip()]

def validate_rows(rows):
    for i, r in enumerate(rows):
        if r.get('epoch_id') != 2 or r.get('sequence') != i:
            raise ValueError('epoch-2 sequence drift')
        if r.get('review_hash') != row_hash(r):
            raise ValueError('epoch-2 review hash mismatch')
        expected = None if i == 0 else rows[i-1]['review_hash']
        if r.get('prev_review_hash') != expected:
            raise ValueError('epoch-2 previous hash mismatch')
    return rows

def _lock_path(path): return Path(str(path) + '.lock')

def append_row(path, row, expected_head=None, expected_epoch=2):
    """Append exactly one canonical row without ever opening the ledger for w."""
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    lock=_lock_path(path)
    with lock.open('a+') as lf:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('ledger writer lock conflict')
        before = path.read_bytes() if path.exists() else b''
        rows=validate_rows(read_rows(path))
        if rows and rows[-1].get('epoch_id') != expected_epoch:
            raise ValueError('unexpected ledger epoch')
        head = rows[-1]['review_hash'] if rows else None
        if expected_head is not None and head != expected_head:
            raise ValueError('stale expected head')
        if row.get('epoch_id') != expected_epoch or row.get('sequence') != len(rows):
            raise ValueError('row sequence/epoch mismatch')
        row=dict(row); row['prev_review_hash']=head; row['review_hash']=row_hash(row)
        line=(canon(row)+'\n').encode()
        fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        try:
            os.write(fd,line); os.fsync(fd)
        finally: os.close(fd)
        after=path.read_bytes()
        if len(after) != len(before)+len(line) or after[:len(before)] != before:
            raise RuntimeError('ledger prefix changed during append')
        validate_rows(read_rows(path))
        update_checkpoint(path, len(after), sha_bytes(after), row['review_hash'])
        return row

def update_checkpoint(path, byte_length, file_sha256, head):
    cp=Path(str(path)+'.checkpoint.json')
    data={'epoch_id':2,'sequence':None,'byte_length':byte_length,'head_review_hash':head,'file_sha256':file_sha256}
    rows=read_rows(path); data['sequence']=len(rows)-1
    raw=canon(data).encode(); tmp=cp.with_suffix('.tmp')
    fd=os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    try: os.write(fd,raw); os.fsync(fd)
    finally: os.close(fd)
    os.replace(tmp,cp); os.chmod(cp,0o600)

def initialize_epoch(path, manifest_path, manifest_sha256):
    path=Path(path)
    if path.exists() and path.stat().st_size: raise ValueError('epoch ledger already initialized')
    g={'epoch_id':2,'sequence':0,'operation':GENESIS,'prev_review_hash':None,
       'manifest_sha256':manifest_sha256,'reason':'PREFIX_BYTES_UNRECOVERABLE','state':'APPROVE'}
    g['review_hash']=row_hash(g)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((canon(g)+'\n').encode()); os.chmod(path,0o600)
    c={'epoch_id':2,'sequence':1,'operation':CHECKPOINT,'manifest_path':str(manifest_path),
       'manifest_sha256':manifest_sha256,'resume_ordinal':50,'resume_stage':'SEAL',
       'state':'APPROVE'}
    append_row(path,c,expected_head=g['review_hash'])
    validate_rows(read_rows(path)); return read_rows(path)
