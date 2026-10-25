// Read-only Feishu API verification for the isolated test bot, never production.
import fs from 'node:fs';
const root='.dsh-021-probe/testbot';
const s=fs.readFileSync('/root/.dsh-lab/run/start-lab-bridge.sh','utf8');
const app_id=s.match(/^export FEISHU_APP_ID=(.*)$/m)?.[1]?.trim();
const app_secret=s.match(/^export FEISHU_APP_SECRET=(.*)$/m)?.[1]?.trim();
if(app_id!=='cli_aaa9c8edbaf9dbeb')throw Error('Wrong bot identity');
const auth=await fetch('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({app_id,app_secret})}).then(r=>r.json());
if(auth.code!==0)throw Error('Test bot auth failed '+auth.code);
const log=fs.readFileSync(root+'/bridge.log','utf8');
const chats=[...log.matchAll(/msg in chat=(\S+)/g)];const chat=chats.at(-1)?.[1];
if(!chat)throw Error('No test chat inbound');
const url=new URL('https://open.feishu.cn/open-apis/im/v1/messages');
for(const [k,v] of Object.entries({container_id_type:'chat',container_id:chat,page_size:'20',sort_type:'ByCreateTimeDesc'}))url.searchParams.set(k,v);
const response=await fetch(url,{headers:{Authorization:'Bearer '+auth.tenant_access_token}}).then(r=>r.json());
if(response.code!==0)throw Error('Read delivery failed '+response.code+' '+response.msg);
fs.writeFileSync(root+'/delivery.json',JSON.stringify(response,null,2));
console.log(JSON.stringify({code:response.code,messages:response.data?.items?.map(m=>({id:m.message_id,type:m.msg_type,senderType:m.sender?.sender_type,time:m.create_time,body:m.body?.content}))}));
