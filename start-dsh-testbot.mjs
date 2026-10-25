// Isolated test bot only. Never reads or modifies production service state.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
const home=path.resolve('.dsh-021-probe/testbot');
const source=fs.readFileSync('/root/.dsh-lab/run/start-lab-bridge.sh','utf8');
const appId=source.match(/^export FEISHU_APP_ID=(.*)$/m)?.[1]?.trim();
const appSecret=source.match(/^export FEISHU_APP_SECRET=(.*)$/m)?.[1]?.trim();
if(appId!=='cli_aaa9c8edbaf9dbeb'||!appSecret) throw new Error('Isolated bot identity check failed');
const credential=fs.readFileSync('/etc/dsh.env','utf8').match(/^GLM_API_KEY=(.*)$/m)?.[1]?.trim().replace(/^['"]|['"]$/g,'');
if(!credential) throw new Error('Model credential unavailable');
const env={...process.env,DSH_HOME:home,FEISHU_APP_ID:appId,FEISHU_APP_SECRET:appSecret,GLM_API_KEY:credential,DSH_FEISHU_DATA_DIR:path.join(home,'feishu'),DSH_FEISHU_LOG:'debug'};
for(const k of ['DSH_SESSION_ID','DSH_SESSION_JSONL','DSH_FEISHU_SCRIPT','DSH_FEISHU_OUT','DSH_FEISHU_TRANSPORT','FEISHU_TRANSPORT']) delete env[k];
const p=spawn('/root/.nvm/versions/node/v22.22.1/bin/node',['/opt/dsh-021/node_modules/@deepseek-ai/dsh/lib/bin.js','--profile','feishu','--verbose'],{cwd:path.join(home,'ws'),env,stdio:['ignore','pipe','pipe']});
p.stdout.pipe(process.stdout);p.stderr.pipe(process.stderr);
fs.writeFileSync(path.join(home,'pid'),String(p.pid));
const t=setTimeout(()=>p.kill('SIGTERM'),180000);
process.on('SIGTERM',()=>p.kill('SIGTERM'));
await new Promise(r=>p.on('exit',r));clearTimeout(t);
