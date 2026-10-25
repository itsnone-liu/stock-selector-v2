import pathlib, shutil, json
root=pathlib.Path('/root/project/workspace/stock-selector-v2/.dsh-021-probe')
lab=pathlib.Path('/root/.dsh-lab/home')
root.mkdir(exist_ok=True)
for label in ['baseline','fixed']:
 home=root/label
 prof=home/'profiles/feishu'; prof.mkdir(parents=True,exist_ok=True)
 for name in ['package.json','cordis.yml']:
  shutil.copy2(lab/'profiles/feishu'/name,prof/name)
 nm=prof/'node_modules'
 if nm.is_symlink(): nm.unlink()
 nm.mkdir(exist_ok=True)
 for entry in (lab/'profiles/feishu/node_modules').iterdir():
  if entry.name in ['@deepseek-ai','dsh-evolve']: continue
  dest=nm/entry.name
  if not dest.exists(): dest.symlink_to(entry,target_is_directory=entry.is_dir())
 scope=nm/'@deepseek-ai'; scope.mkdir(exist_ok=True)
 for entry in pathlib.Path('/opt/dsh-021/node_modules/@deepseek-ai').iterdir():
  dest=scope/entry.name
  if not dest.exists(): dest.symlink_to(entry,target_is_directory=entry.is_dir())
 ev=nm/'dsh-evolve'
 if not ev.exists(): shutil.copytree(lab/'profiles/feishu/node_modules/dsh-evolve',ev,symlinks=False)
 patch=(lab/'profiles/feishu/cordis.patch.yml').read_text()
 # Retain presets but use only a loopback provider with a non-secret test key.
 patch=patch[:patch.index('# llm-pi-ai providers')]
 patch+='''\n- id: llm-pi-ai
  config:
    providers:
      probe:
        apiKeyEnv: DSH_PROBE_KEY
        api: openai-completions
        baseURL: http://127.0.0.1:18791/v1
        defaultContextWindow: 64000
        models:
          - id: probe-model
            contextWindow: 64000
'''
 if label=='fixed':
  # Source patch intentionally performed separately after reading copied files.
  pass
 (prof/'cordis.patch.yml').write_text(patch)
 ws=home/'ws'; ws.mkdir(exist_ok=True)
 data=home/'feishu'; data.mkdir(exist_ok=True)
 cfg=dict(transport='mock',mockAgent=False,allowedOpenIds=['ou_mock_me'],defaultCwd=str(ws),allowedWorkspaces=[str(ws)],agentPreset='minimal',provider='probe',model='probe-model',approval='never',throttleMs=60,logFile=str(home/'bridge.log'))
 (data/'config.json').write_text(json.dumps(cfg))
 store=home/'storages';store.mkdir(exist_ok=True)
 shutil.copy2('/root/.dsh/storages/evolve_memory.json',store/'evolve_memory.json')
 script=[dict(text='升级后测试'),dict(wait=6000),dict(text='/status'),dict(wait=500)]
 (home/'script.json').write_text(json.dumps(script))
print('Prepared two independent homes; no Feishu credentials or production writes.')
