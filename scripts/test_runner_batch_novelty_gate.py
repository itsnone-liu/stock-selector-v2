#!/usr/bin/env python3
"""Pure batch-level Reviewer Independence v2 novelty gate.

The production batch orchestrator must call this executor-side check at every
8-ordinal boundary with the prior transcript/session id set and the newly
observed reviewer ids. Declared ids are only a novelty spot-check; this does
not claim transcript-anchored proof of platform session identity.
"""
import json, sys

def check(previous_ids, observed_ids, boundary_ordinal):
    if boundary_ordinal < 8 or boundary_ordinal % 8:
        raise ValueError('novelty gate is required at ordinal multiples of 8')
    if not observed_ids or len(observed_ids) != len(set(observed_ids)):
        raise ValueError('observed reviewer ids must be nonempty and distinct')
    overlap=set(previous_ids)&set(observed_ids)
    if overlap:
        raise ValueError('reviewer-id novelty failure: '+repr(sorted(overlap)))
    return {'status':'PASS','boundary_ordinal':boundary_ordinal,
            'attestation_level':'PLATFORM_OPAQUE_SUBAGENT',
            'checked_ids':len(observed_ids),'novelty':True}

def main():
    assert check(['s1','s2'],['s3','s4'],8)['status']=='PASS'
    try: check(['s1'],['s1'],8)
    except ValueError: pass
    else: raise AssertionError('overlap accepted')
    try: check([],[],8)
    except ValueError: pass
    else: raise AssertionError('empty ids accepted')
    print(json.dumps({'status':'PASS','positive_and_negative_controls':'PASS'},separators=(',',':')))
if __name__=='__main__':main()
