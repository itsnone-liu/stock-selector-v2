#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frozen ANNOTATION review envelope (H2-CANARY-FIX1 item 3).

The H2 ordinal-4 canary review found that the ANNOTATION verdict bound
only draft_sha256, leaving the NATIONAL_CTX sidecar and the context
support map outside the reviewer's exact-hash commitment.  From
ordinal-5 onward the ANNOTATION verdict's input_commitment_sha256 MUST
be the composite envelope defined here:

    sha256(canon({
        "version": "csr8-annotation-review-envelope-v1",
        "packet_sha256":            <sha256 of revealed pool packet bytes>,
        "context_commitment_sha256":<sidecar context_commitment_sha256>,
        "support_map_sha256":       <sha256 of support map file bytes>,
        "draft_sha256":             <sha256 of draft file bytes>
    }))

where canon(x) = json.dumps(x, ensure_ascii=False, sort_keys=True,
separators=(',', ':')).  The reviewer must recompute the envelope from
the four live artifacts and refuse to APPROVE on any mismatch; the
executor gates the receipt stage on the same value.

This module is the single frozen definition; executors, reviewers and
audits must import it rather than re-implementing the rule.
"""
import hashlib
import json

ANNOTATION_REVIEW_ENVELOPE_VERSION = 'csr8-annotation-review-envelope-v1'


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def annotation_envelope_sha256(packet_sha256, context_commitment_sha256,
                               support_map_sha256, draft_sha256):
    for name, v in (('packet_sha256', packet_sha256),
                    ('context_commitment_sha256',
                     context_commitment_sha256),
                    ('support_map_sha256', support_map_sha256),
                    ('draft_sha256', draft_sha256)):
        if not isinstance(v, str) or len(v) != 64 or \
                any(c not in '0123456789abcdef' for c in v):
            raise ValueError(f'{name} must be a lowercase sha256 hex')
    obj = {
        'version': ANNOTATION_REVIEW_ENVELOPE_VERSION,
        'packet_sha256': packet_sha256,
        'context_commitment_sha256': context_commitment_sha256,
        'support_map_sha256': support_map_sha256,
        'draft_sha256': draft_sha256,
    }
    return hashlib.sha256(canon(obj).encode()).hexdigest()


def _self_test():
    # deterministic reference vector (stable across refactors)
    v = annotation_envelope_sha256(
        '00' * 32, '11' * 32, '22' * 32, '33' * 32)
    assert len(v) == 64
    v2 = annotation_envelope_sha256(
        '00' * 32, '11' * 32, '22' * 32, '33' * 32)
    assert v == v2, 'envelope not deterministic'
    try:
        annotation_envelope_sha256('short', '11' * 32, '22' * 32,
                                   '33' * 32)
    except ValueError:
        pass
    else:
        raise AssertionError('envelope accepted malformed hash')
    print(json.dumps({
        'self_test': 'PASS',
        'reference_vector': v,
        'version': ANNOTATION_REVIEW_ENVELOPE_VERSION}))


if __name__ == '__main__':
    _self_test()
