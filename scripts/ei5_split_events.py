#!/usr/bin/env python3
"""EI-5P 供数：送转/除权因子跳变事件表 data/r2/ei5/split_events.json。
修复口径（2026-10-09 裁定）：EI-5P 20日均量基线一律用 restated volume
  vol_restated_k = vol_raw_k * (f_now / f_k)   （f=adjust_factor_model_derived）
把事件前旧股本口径量折成当前股本口径，送转跳空不再稀释 auction_vol_ratio。
事件表按 code+date 去重累积（append 历史不删），每晚 A 之后刷新。"""
import json,gzip
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; OUT=ROOT/'data/r2/ei5/split_events.json'
def main(threshold=0.01):
 new=[]
 for p in sorted(D.glob('*.json.gz')):
  d=json.loads(gzip.decompress(p.read_bytes()))
  f=d.get('adjust_factor_model_derived') or []; ds=d['dates']
  if len(f)!=len(ds) or len(ds)<2: continue
  for k in range(1,len(ds)):
   if f[k-1]>0 and abs(f[k]/f[k-1]-1)>threshold:
    new.append({'code':p.name[:-8],'date':ds[k],'f_prev':f[k-1],'f_now':f[k],'jump':round(f[k]/f[k-1],4)})
 old=json.loads(OUT.read_text()) if OUT.exists() else []
 seen={(e['code'],e['date']) for e in old}
 merged=old+[e for e in new if (e['code'],e['date']) not in seen]
 OUT.write_text(json.dumps(merged,ensure_ascii=False,indent=1))
 big=[e for e in merged if e['jump']>1.05]
 print(json.dumps({'total_events':len(merged),'big_splits_gt5pct':len(big),'big_sample':big[-8:]},ensure_ascii=False))
if __name__=='__main__':main()
