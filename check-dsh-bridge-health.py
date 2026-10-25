"""Fail-closed isolated message-health gate, not a process-liveness test.
Usage: python3 check-dsh-bridge-health.py HOME --rounds 3 --reply PROBE_OK
Exit 0 requires completed reply cards, no error cards and an idle status if present.
This is a mock-transport gate; it must not be labeled Feishu E2E.
"""
import argparse,json,pathlib,sys
p=argparse.ArgumentParser();p.add_argument('home',type=pathlib.Path);p.add_argument('--rounds',type=int,required=True);p.add_argument('--reply',required=True);a=p.parse_args()
try:
 out=json.loads((a.home/'out.json').read_text())
 assert isinstance(out,list),'Output must be a list'
 done=[]
 for item in out:
  card=item.get('card',{});title=card.get('header',{}).get('title',{}).get('content','')
  assert not title.startswith('✗'),'Error card: '+title
  if title=='桥状态':
   status='\n'.join(e.get('text',{}).get('content','') for e in card.get('elements',[]))
   assert 'agent 状态：**idle**' in status,'Agent did not settle idle'
  if title.startswith('✓ 完成'):
   # Verify response body, not prompt echoed in the title or reasoning block.
   bodies=[e.get('text',{}).get('content','').strip() for e in card.get('elements',[])]
   assert a.reply in bodies,'Expected exact response body not found'
   done.append(title)
 assert len(done)==a.rounds,f'Expected {a.rounds} completed rounds, got {len(done)}'
 print(json.dumps({'ok':True,'scope':'isolated-agent-to-bridge-output','completed':len(done),'reply':a.reply},ensure_ascii=False))
except Exception as e:
 print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
