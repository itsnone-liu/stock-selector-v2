"""Summarize real isolated bot's durable turns without exposing message bodies.
Not a substitute for Feishu API delivery or human receipt confirmation.
"""
import pathlib,json,subprocess,sys
r=pathlib.Path(__file__).parent/'.dsh-021-probe';h=r/'testbot'
files=list((h/'sessions').glob('**/session.v4.jsonl.zstd')) if (h/'sessions').exists() else []
summary=[]
for i,p in enumerate(files):
 dst=r/f'testbot-evidence-{i}.jsonl'
 run=subprocess.run(['node','/root/dsh-lab/repo/tools/decode-session.mjs',str(p),str(dst)],capture_output=True,text=True)
 if run.returncode: raise RuntimeError('Decode failed: '+run.stderr)
 rows=[json.loads(l) for l in dst.read_text().splitlines() if l.strip()]
 starts=[e for e in rows if e.get('type')=='turn/start'];ends=[e for e in rows if e.get('type')=='turn/end']
 summary.append({'sessionId':p.parent.name,'starts':len(starts),'ends':len(ends),'reasons':[e.get('data',{}).get('reason',{}).get('kind') for e in ends]})
log=(h/'bridge.log').read_text();live=log[log.rfind('bridge starting'):]
inbound=sum('msg in chat=' in l for l in live.splitlines())
print(json.dumps({'latestProcessInbound':inbound,'sessions':summary,'scope':'real-testbot-session-not-receipt-confirmation'},ensure_ascii=False))
sys.exit(0 if inbound and any(s['ends'] for s in summary) else 2)
