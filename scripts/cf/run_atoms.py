#!/usr/bin/env python3
"""Run CF-1 atom replay and emit side-by-side Capital Weather (no aggregation)."""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from stock_selector.cf.atoms import INSUFFICIENT,replay_l1,replay_l4,replay_margin


def dump_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    tmp.replace(path)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--asof');ap.add_argument('--tdx-root',default='/root/tdx_data');args=ap.parse_args()
    raw=ROOT/'data/cf/raw';live=ROOT/'data/cl_radar/r6_equityflow';derived=ROOT/'data/cf/derived/atoms';universe=ROOT/'docs/cf/cf1a_probes/l1_broad_etf_universe_v1.json'
    atoms={'L1':replay_l1(raw,universe,live),'M':replay_margin(raw,live),'L4':replay_l4(Path(args.tdx_root))}
    if args.asof:
        key=args.asof.replace('-','');atoms={k:[r for r in v if r['date']<=key] for k,v in atoms.items()}
    for k,rows in atoms.items():dump_jsonl(derived/f'{k.lower()}_history.jsonl',rows)
    latest={k:(v[-1] if v else {'atom':k,'state':INSUFFICIENT,'reason':'no_data'}) for k,v in atoms.items()}
    dates={v.get('date') for v in latest.values() if v.get('date')};asof=max(dates) if dates else None
    weather={'schema':'capital_weather_v0.1','generated_at':datetime.now().isoformat(timespec='seconds'),
             'asof':asof,'aggregation':'FORBIDDEN','market_regime':'NON_OPERATIVE','atoms':latest,
             'note':'Atom states are displayed side by side; no composite score or direction forecast.'}
    out=ROOT/'data/cf/derived/capital_weather/latest.json';out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(weather,ensure_ascii=False,indent=2));tmp.replace(out)
    summary={k:{'rows':len(v),'supported':sum(r['state']!=INSUFFICIENT for r in v),'latest':latest[k].get('date'),'state':latest[k]['state']} for k,v in atoms.items()}
    print(json.dumps({'output':str(out),'summary':summary},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
