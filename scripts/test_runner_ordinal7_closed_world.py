#!/usr/bin/env python3
"""Static/dry-run proof that runner ordinal 7 includes prior h4 artifacts."""
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    env=dict(os.environ,CSR8_H_ORDINAL='7')
    code="""import sys; sys.path.insert(0,'scripts'); import csr8_phase_h_runner as r
x=r._expected_historical_campaign_files()
assert 'h4/packets/ordinal-0006-next-reveal.json' in x
assert 'h4/reviews/POST_SEAL.verdict.json' in x
assert 'h3/packets/ordinal-0005-next-reveal.json' in x
assert 'h5/packets/ordinal-0007-next-reveal.json' in x
print({'status':'PASS','contains_h4':True,'contains_h3':True,'contains_current_h5':True,'count':len(x)})
"""
    p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
    if p.returncode: print(p.stderr); return p.returncode
    print(p.stdout.strip()); return 0
if __name__=='__main__':sys.exit(main())
