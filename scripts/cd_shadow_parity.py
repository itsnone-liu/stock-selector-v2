#!/usr/bin/env python3
"""Historical G-SHADOW-PARITY gate for selected frozen reference days."""
import argparse, json
from pathlib import Path
from scripts.cd_shadow_runtime import parity_check

def run(reference_path: Path, actual_path: Path) -> dict:
    ref=json.loads(reference_path.read_text()); actual=json.loads(actual_path.read_text())
    return parity_check(ref,actual)
def main():
    p=argparse.ArgumentParser(); p.add_argument('reference'); p.add_argument('actual'); a=p.parse_args()
    out=run(Path(a.reference),Path(a.actual)); print(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit(0 if out['status']=='PARITY_PASS' else 2)
if __name__=='__main__': main()
