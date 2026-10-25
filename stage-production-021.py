import pathlib,shutil,json,subprocess,os
D=pathlib.Path('/root/dsh-deploy-021');H=pathlib.Path('/root/.dsh-feishu-021');old=pathlib.Path('/root/.dsh')
for n in ['feishu','storages','sessions','skills','evolve-workspace']:
 if (old/n).exists():shutil.copytree(old/n,H/n,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','*.lock','*.sqlite*'))
for n in ['.credentials.yaml']:
 if (old/n).exists():shutil.copy2(old/n,H/n)
cfg=json.loads((H/'feishu/config.json').read_text());cfg['logFile']=str(H/'feishu/bridge.log');(H/'feishu/config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
# Native upgrade can migrate flat credentials, but never sees old settings.yaml.
# Repair only copied bound histories. Never rewrite old shared home.
bindings=json.loads((H/'feishu/bindings.json').read_text())
for b in bindings.values():
 sid=b.get('sessionId');matches=list((H/'sessions').glob('*/'+sid)) if sid else []
 for folder in matches:subprocess.run(['python3','/root/dsh-lab/migrate-v0-sessions.py',str(folder)],check=True,stdout=subprocess.DEVNULL)
# Probe home shares immutable plugin tree, uses private data and snapshots.
P=D/'preflight';(P/'profiles').mkdir(parents=True,exist_ok=True)
(P/'profiles/feishu').symlink_to(H/'profiles/feishu',target_is_directory=True)
for n in ['storages','skills']:shutil.copytree(H/n,P/n,dirs_exist_ok=True) if (H/n).exists() else None
(P/'feishu').mkdir(exist_ok=True);probe=dict(cfg);probe.update(transport='mock',allowedOpenIds=['ou_mock_me'],defaultCwd=str(P),allowedWorkspaces=[str(P)],logFile=str(P/'bridge.log'),audit={'enabled':False})
(P/'feishu/config.json').write_text(json.dumps(probe))
(P/'script.json').write_text(json.dumps([{'text':'升级预检，只回复 PROD_UPGRADE_READY，不调用工具。'},{'wait':40000},{'text':'/status'}]))
# Preserve effective production environment without printing secrets.
pid=subprocess.check_output(['systemctl','show','dsh-bridge.service','-p','MainPID','--value'],text=True).strip()
env=dict(s.split('=',1) for s in pathlib.Path('/proc/'+pid+'/environ').read_text().split('\0') if '=' in s)
env.update(DSH_HOME=str(P),DSH_FEISHU_DATA_DIR=str(P/'feishu'),DSH_FEISHU_TRANSPORT='mock',DSH_FEISHU_SCRIPT=str(P/'script.json'),DSH_FEISHU_OUT=str(P/'out.json'),DSH_FEISHU_TAIL_WAIT='1500')
for n in ['DSH_SESSION_ID','DSH_SESSION_JSONL']:env.pop(n,None)
with (P/'boot.log').open('w') as log:
 run=subprocess.run(['/root/.nvm/versions/node/v22.22.1/bin/node','/opt/dsh-021/node_modules/@deepseek-ai/dsh/lib/bin.js','--profile','feishu','--verbose'],cwd=D/'bridge',env=env,stdout=log,stderr=log,timeout=80)
 if run.returncode:raise SystemExit('Preflight process failed')
subprocess.run(['python3',str(D/'check-dsh-bridge-health.py'),str(P),'--rounds','1','--reply','PROD_UPGRADE_READY'],check=True)
(D/'PRECHECK_OK').write_text('production config, real model, repaired plugin passed\n')
print('Preflight passed; production still old version.')
