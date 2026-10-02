#!/usr/bin/env python3
import json
from csr8_batch_h_orchestrator import reviewer_id_novelty_spot_check

def main():
    assert reviewer_id_novelty_spot_check(7, ['s1'], ['s2'], [])['batch_end'] == 14
    try: reviewer_id_novelty_spot_check(7, ['s1'], ['s1'], [])
    except ValueError: pass
    else: raise AssertionError('overlap accepted')
    try: reviewer_id_novelty_spot_check(7, [], ['future-id-X'], ['tool args future-id-X'])
    except ValueError: pass
    else: raise AssertionError('premature transcript id accepted')
    try: reviewer_id_novelty_spot_check(7, [], ['x','x'], [])
    except ValueError: pass
    else: raise AssertionError('duplicate ids accepted')
    try: reviewer_id_novelty_spot_check(7, [], [], [])
    except ValueError: pass
    else: raise AssertionError('empty ids accepted')
    print(json.dumps({'status':'PASS','transcript_positive_and_premature_negative_and_duplicate_empty':'PASS'},separators=(',',':')))
if __name__=='__main__': main()
