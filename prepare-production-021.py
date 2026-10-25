import pathlib,shutil,json,datetime,os
W=pathlib.Path('/root/project/workspace/stock-selector-v2')
D=pathlib.Path('/root/dsh-deploy-021');H=pathlib.Path('/root/.dsh-feishu-021')
if D.exists() or H.exists():raise SystemExit('Deployment destination exists; inspect before reuse')
D.mkdir(mode=0o700);H.mkdir(mode=0o700)
# Immutable bridge source snapshot, leave production repo and old Web untouched.
shutil.copytree('/root/dsh-ws/dsh-feishu',D/'bridge',ignore=shutil.ignore_patterns('node_modules','.git','.codegraph'))
N=D/'bridge/node_modules';N.mkdir();lab=pathlib.Path('/root/dsh-lab/repo/node_modules')
for e in lab.iterdir():
 if e.name=='@deepseek-ai':continue
 (N/e.name).symlink_to(e,target_is_directory=e.is_dir())
S=N/'@deepseek-ai';S.mkdir()
for e in pathlib.Path('/opt/dsh-021/node_modules/@deepseek-ai').iterdir():(S/e.name).symlink_to(e,target_is_directory=e.is_dir())
p=H/'profiles/feishu';p.mkdir(parents=True)
fixed=W/'.dsh-021-probe/fixed/profiles/feishu'
for n in ['package.json','cordis.yml']:shutil.copy2(fixed/n,p/n)
nm=p/'node_modules';nm.mkdir();labnm=fixed/'node_modules'
for e in labnm.iterdir():
 if e.name=='dsh-evolve':continue
 (nm/e.name).symlink_to(e.resolve(),target_is_directory=e.is_dir())
shutil.copytree(fixed/'node_modules/dsh-evolve',nm/'dsh-evolve')
patch=pathlib.Path('/root/.dsh/patches/feishu-021.yml').read_text()
patch=patch.replace('/root/dsh-ws/dsh-feishu/src/index.js',str(D/'bridge/src/index.js')).replace('/root/dsh-lab/repo/src/index.js',str(D/'bridge/src/index.js'))
(p/'cordis.patch.yml').write_text(patch)
# Backup service configuration, credentials, config and old plugin before any cutover.
bk=D/'backup';bk.mkdir(mode=0o700)
shutil.copy2('/etc/systemd/system/dsh-bridge.service',bk/'dsh-bridge.service')
shutil.copytree('/etc/systemd/system/dsh-bridge.service.d',bk/'dsh-bridge.service.d')
for n in ['settings.yaml','.credentials.yaml']:
 s=pathlib.Path('/root/.dsh')/n
 if s.exists():shutil.copy2(s,bk/n)
shutil.copytree('/root/.dsh/profiles/feishu',bk/'old-profile',ignore=shutil.ignore_patterns('node_modules'))
shutil.copytree('/root/.dsh/profiles/feishu/node_modules/dsh-evolve',bk/'old-evolve')
for n in ['check-dsh-bridge-health.py','check-feishu-delivery.mjs']:
 shutil.copy2(W/n,D/n)
manifest={'preparedAt':datetime.datetime.now().isoformat(),'home':str(H),'oldHome':'/root/.dsh','bridge':str(D/'bridge'),'backup':str(bk),'oldVersion':'0.1.0-rc.7','newVersion':'0.2.1-rc.3'}
(D/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Prepared independent deployment and backed up service/config/plugin; production untouched.')
