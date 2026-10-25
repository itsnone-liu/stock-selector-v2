import json,pathlib
root=pathlib.Path(__file__).parent/'.dsh-021-probe'
def rows(name): return [json.loads(s) for s in (root/name).read_text().splitlines()]
a=rows('incident.decoded.jsonl'); b=rows('baseline-fresh.decoded.jsonl')
def shape(rs): return [(r['type'],r.get('seq'),r.get('data',{}).get('removedCount')) for r in rs]
assert shape(a)==shape(b), 'Fresh baseline differs from incident timeline'
assert not any(r['type']=='turn/end' for r in b)
assert b[-1]['data']['removedCount']==1
cards=json.loads((root/'fixed/out-multiturn.json').read_text())
completed=[c for c in cards if c.get('card',{}).get('header',{}).get('title',{}).get('content','').startswith('✓ 完成')]
assert len(completed)==3, f'Expected three completed rounds, got {len(completed)}'
assert all('PROBE_OK' in json.dumps(c) for c in completed)
assert any(c.get('card',{}).get('header',{}).get('title',{}).get('content')=='新会话已就绪' for c in cards)
cards=json.loads((root/'fixed/out.json').read_text())
assert sum(c.get('card',{}).get('header',{}).get('title',{}).get('content','').startswith('✓ 完成') for c in cards)==2
assert 'agent resumed' in (root/'fixed/boot.log').read_text()
req=rows('fixed/requests.jsonl')
assert any(m.get('role')=='tool' and 'TOOL_OK' in str(m.get('content')) for r in req[-3:] for m in r['body'].get('messages',[])), 'No actual tool result'
print('PASS: identical incident timeline, fresh first+second+/new replies, restart resume, real tool round trip.')
