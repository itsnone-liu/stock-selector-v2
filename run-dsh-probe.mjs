import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
const root=path.resolve('.dsh-021-probe');
const label=process.argv[2]||'baseline';
const home=path.join(root,label);
let requests=0;
const server=http.createServer(async(req,res)=>{
 let raw=''; for await(const c of req) raw+=c;
 requests++;
 fs.appendFileSync(path.join(home,'requests.jsonl'),JSON.stringify({url:req.url,body:JSON.parse(raw)})+'\n');
 const body=JSON.parse(raw);
 const needTool=body.messages?.some(m=>m.role==='user'&&JSON.stringify(m.content).includes('PROBE_TOOL_TEST'))&&!body.messages?.some(m=>m.role==='tool');
 const bashTool=body.tools?.find(t=>t.function?.name==='bash');
 const toolCall=needTool&&bashTool?{id:'call_probe',type:'function',function:{name:'bash',arguments:JSON.stringify({command:'printf TOOL_OK',description:'Verify harmless isolated tool execution'})}}:null;
 const data={id:'probe-'+requests,object:'chat.completion',created:Math.floor(Date.now()/1000),model:'probe-model',choices:[{index:0,message:toolCall?{role:'assistant',content:null,tool_calls:[toolCall]}:{role:'assistant',content:'PROBE_OK'},finish_reason:toolCall?'tool_calls':'stop'}],usage:{prompt_tokens:10,completion_tokens:3,total_tokens:13}};
 if(body.stream){
  res.writeHead(200,{'Content-Type':'text/event-stream'});
  for(const delta of (toolCall?[{role:'assistant',tool_calls:[{index:0,...toolCall}]}]:[{role:'assistant',content:''},{content:'PROBE_OK'}])) res.write('data: '+JSON.stringify({id:data.id,object:'chat.completion.chunk',created:data.created,model:data.model,choices:[{index:0,delta,finish_reason:null}]})+'\n\n');
  res.write('data: '+JSON.stringify({id:data.id,object:'chat.completion.chunk',created:data.created,model:data.model,choices:[{index:0,delta:{},finish_reason:toolCall?'tool_calls':'stop'}],usage:data.usage})+'\n\n');
  res.end('data: [DONE]\n\n');
 }else{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));}
});
await new Promise(r=>server.listen(18791,'127.0.0.1',r));
const env={...process.env,DSH_HOME:home,DSH_PROBE_KEY:'non-secret-loopback-test',DSH_FEISHU_DATA_DIR:path.join(home,'feishu'),DSH_FEISHU_SCRIPT:path.join(home,'script.json'),DSH_FEISHU_OUT:path.join(home,'out.json'),DSH_FEISHU_LOG:'debug',DSH_FEISHU_TAIL_WAIT:'1000'};
if(process.env.DSH_PROBE_EXTERNAL==='1'){
 const source=fs.readFileSync('/etc/dsh.env','utf8');
 const match=source.match(/^GLM_API_KEY=(.*)$/m);
 if(!match) throw new Error('GLM credential unavailable');
 env.GLM_API_KEY=match[1].trim().replace(/^['"]|['"]$/g,'');
}
delete env.DSH_SESSION_ID;delete env.DSH_SESSION_JSONL;
const p=spawn('/root/.nvm/versions/node/v22.22.1/bin/node',[process.env.DSH_PROBE_BIN||'/opt/dsh-021/node_modules/@deepseek-ai/dsh/lib/bin.js','--profile','feishu','--verbose'],{cwd:path.join(home,'ws'),env,stdio:['ignore','pipe','pipe']});
const log=fs.createWriteStream(path.join(home,'boot.log'));
p.stdout.pipe(log);p.stderr.pipe(log);
const timeout=setTimeout(()=>p.kill('SIGTERM'),process.env.DSH_PROBE_EXTERNAL==='1'?90000:22000);
const code=await new Promise(r=>p.on('exit',(c,s)=>r({code:c,signal:s})));
clearTimeout(timeout);server.close();
console.log(JSON.stringify({label,...code,requests,out:fs.existsSync(path.join(home,'out.json'))}));
