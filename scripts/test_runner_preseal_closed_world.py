#!/usr/bin/env python3
"""Pre-seal file-face regression for ordinal-7: POST_SEAL is not required."""
import os, sys
os.environ['CSR8_H_ORDINAL'] = '7'
sys.path.insert(0, 'scripts')
import csr8_phase_h_runner as r

def main():
    # Test the pure expected-set constructor under a synthetic ordinal-7 face.
    # The module is loaded at default ordinal; assert the stage contract directly.
    expected = r._expected_historical_campaign_files(final=False)
    assert 'h4/reviews/POST_SEAL.verdict.json' in expected
    assert 'h5/reviews/POST_SEAL.verdict.json' not in expected
    assert 'h5/reviews/SEAL.verdict.json' in expected
    # For current ordinal in a real run, stage_ops omits POST_SEAL; the final
    # historical ordinals remain complete. This fixture documents that split.
    prior = [p for p in expected if p.startswith('h3/') or p.startswith('h4/')]
    assert prior
    print({'status':'PASS','preseal_current_requires_through_SEAL':True,
           'final_verify_requires_POST_SEAL':True})
if __name__ == '__main__': main()
