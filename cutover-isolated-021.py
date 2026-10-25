import pathlib,subprocess,shutil,json,time,os,sys,datetime
D=pathlib.Path('/root/dsh-deploy-021');H=pathlib.Path('/root/.dsh-feishu-021');O=pathlib.Path('/root/.dsh');drop=pathlib.Path('/etc/systemd/system/dsh-bridge.service.d/90-isolated-021.conf')
def cmd(*a):return subprocess.run(a,check=True,capture_output=True,text=True).stdout.strip()
def note(s):
 with (D/'cutover.log').open('a') as f:f.write(datetime.datetime.now().isoformat()+' '+s+'\n')
def rollback(reason):
 note('ROLLBACK '+reason);cmd('systemctl','stop','dsh-bridge.service')
 if drop.exists():drop.unlink()
 cmd('systemctl','daemon-reload');cmd('systemctl','start','dsh-bridge.service');(D/'ROLLED_BACK').write_text(reason);sys.exit(1)
if not (D/'PRECHECK_OK').exists():raise SystemExit('Missing precheck')
if drop.exists():raise SystemExit('Drop-in exists; refusing overwrite')
time.sleep(12) # let initiating reply finish
try:
 note('STOP_OLD');cmd('systemctl','stop','dsh-bridge.service')
 # Old Web keeps its home. New bridge owns a separate home; rollback simply removes drop-in.
 for n in ['feishu','storages','sessions','skills','evolve-workspace']:
  if (O/n).exists():shutil.copytree(O/n,H/n,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','*.lock','*.sqlite*'))
 for n in ['settings.yaml','.credentials.yaml']:
  if (O/n).exists():shutil.copy2(O/n,D/'backup'/('cutover-'+n))
 shutil.copy2(O/'.credentials.yaml',H/'.credentials.yaml')
 cfg=json.loads((H/'feishu/config.json').read_text());cfg['logFile']=str(H/'feishu/bridge.log');(H/'feishu/config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
 # Backup exact binding before selecting clean canary chat session. Old sessions retained for /resume.
 bindings=H/'feishu/bindings.json';shutil.copy2(bindings,D/'backup/bindings-before-cutover.json')
 data=json.loads(bindings.read_text())
 for b in data.values():b['sessionId']=None
 bindings.write_text(json.dumps(data,ensure_ascii=False,indent=2))
 note('SNAPSHOT_READY old sessions preserved; clean production canary session')
 drop.write_text('[Service]\nWorkingDirectory=/root/dsh-deploy-021/bridge\nEnvironment="DSH_HOME=/root/.dsh-feishu-021"\nEnvironment="DSH_FEISHU_DATA_DIR=/root/.dsh-feishu-021/feishu"\nExecStart=\nExecStart=/opt/dsh-021/node_modules/.bin/dsh --profile feishu --verbose\n')
 cmd('systemctl','daemon-reload');cmd('systemctl','start','dsh-bridge.service')
 start=time.time();(D/'STARTED').write_text(str(start));note('NEW_STARTED waiting real production message, maximum 300 seconds')
 deadline=start+300
 while time.time()<deadline:
  time.sleep(5)
  if cmd('systemctl','is-active','dsh-bridge.service')!='active':rollback('unit inactive')
  log=cmd('journalctl','-u','dsh-bridge.service','--since','@'+str(int(start)),'--no-pager')
  if any(e in log for e in ['fatal load failure','plugin tree failed','producer-owned source kind','NO_ADAPTER']):rollback('runtime error')
  # Require real input and completed durable turn in NEW home; never use process liveness as success.
  for p in (H/'sessions').glob('**/session.v4.jsonl.zstd'):
   if p.stat().st_mtime<start:continue
   out=D/'acceptance-session.jsonl'
   r=subprocess.run(['node','/root/dsh-lab/repo/tools/decode-session.mjs',str(p),str(out)],capture_output=True,text=True)
   if r.returncode:continue
   rows=[json.loads(s) for s in out.read_text().splitlines() if s.strip()]
   recent=[e for e in rows if e.get('time',0)>=start*1000]
   ok=any(e.get('type')=='turn/end' and e.get('data',{}).get('reason',{}).get('kind')=='completed' for e in recent)
   if ok and 'msg in chat=' in log:
    result={'status':'TURN_COMPLETED_PENDING_DELIVERY_CHECK','session':p.parent.name,'time':time.time(),'home':str(H)}
    (D/'TURN_COMPLETED').write_text(json.dumps(result));note('REAL_PRODUCTION_TURN_COMPLETED')
    # Supervisor leaves time for caller to verify actual Feishu API delivery and set ACCEPTED.
  if (D/'ACCEPTED').exists():note('ACCEPTED production delivery verified');sys.exit(0)
 rollback('no verified production delivery within 300s')
except Exception as e:
 rollback(type(e).__name__+': '+str(e))
