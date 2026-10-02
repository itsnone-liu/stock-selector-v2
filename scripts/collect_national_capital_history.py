#!/usr/bin/env python3
"""Collect historical top-10 floating shareholders for frozen CSR cases.

Raw-first, resumable collector. It deliberately does not invent publication dates:
report_period is observed from the response; publication/availability remain UNKNOWN
until an announcement-date source is joined.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "output/research/csr/08_pilot_cases/phase_a/sample_selection.json"
RAW = ROOT / "data/csr8_national_capital/raw/holdings"
OUT = ROOT / "output/research/csr/national_capital"
ENDPOINT = "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDLTGD"
REPORT_PERIODS = [
    f"{y}-{m:02d}-{d}"
    for y in range(2021, 2027)
    for m, d in ((3,31),(6,30),(9,30),(12,31))
    if (y < 2026 or m <= 6)
]

def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def codes():
    d=json.loads(SAMPLE.read_text())
    return sorted({x["code"] for g in d["groups"].values() for x in g["chosen"]})
def key(code, period): return f"{code.replace('.', '_')}__{period}"
def valid(path: Path):
    meta=path.with_suffix('.meta.json')
    if not path.exists() or not meta.exists(): return False
    try:
        m=json.loads(meta.read_text()); return m.get('outcome') in ('SUCCESS_NONEMPTY','SUCCESS_EMPTY') and sha(path.read_bytes())==m.get('sha256')
    except Exception: return False

def fetch(code, period, session):
    bare=code.split('.',1)[1]; market=code.split('.',1)[0].upper()
    params={'code':f'{market}{bare}','date':period}
    stem=key(code,period); fp=RAW/f'{stem}.json'; mp=RAW/f'{stem}.meta.json'
    if valid(fp): return 'SKIP'
    started=now()
    try:
        r=session.get(ENDPOINT,params=params,timeout=30)
        body=r.content; parsed=r.json() if r.ok else None
        rows=(parsed or {}).get('sdltgd') if isinstance(parsed,dict) else None
        outcome='SUCCESS_NONEMPTY' if isinstance(rows,list) and len(rows)>0 else ('SUCCESS_EMPTY' if r.ok else 'FAILED')
        rec={'http_status':r.status_code,'url':r.url,'response':parsed if parsed is not None else r.text[:2000]}
        raw=json.dumps(rec,ensure_ascii=False,separators=(',',':')).encode()
        fp.parent.mkdir(parents=True,exist_ok=True); fp.write_bytes(raw)
        mp.write_text(json.dumps({'retrieved_at':started,'finished_at':now(),'outcome':outcome,'sha256':sha(raw),'endpoint':ENDPOINT,'request':params,'collector':'collect_national_capital_history.py','source':'Eastmoney PageSDLTGD','report_period_requested':period},ensure_ascii=False,indent=2)+'\n')
        return outcome
    except Exception as e:
        mp.write_text(json.dumps({'retrieved_at':started,'finished_at':now(),'outcome':'FAILED','error':f'{type(e).__name__}: {e}','endpoint':ENDPOINT,'request':params,'collector':'collect_national_capital_history.py','report_period_requested':period},ensure_ascii=False,indent=2)+'\n')
        return 'FAILED'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--sleep',type=float,default=.15); args=ap.parse_args()
    RAW.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    ss=requests.Session(); ss.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://emweb.securities.eastmoney.com/'})
    cs=codes(); stats={}
    for i,c in enumerate(cs,1):
        for p in REPORT_PERIODS:
            s=fetch(c,p,ss); stats[s]=stats.get(s,0)+1
            if s!='SKIP': time.sleep(args.sleep)
        print(f'[{i}/{len(cs)}] {c} {stats}',flush=True)
    manifest={'generated_at':now(),'sample_selection_sha256':sha(SAMPLE.read_bytes()),'codes':cs,'report_periods':REPORT_PERIODS,'endpoint':ENDPOINT,'stats':stats,'pit_note':'publication_date and available_date intentionally unresolved; no report_period-as-availability inference'}
    (OUT/'national_holdings_raw_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
