import {createRequire} from 'node:module';
const roots={old:'/root/.npm/_npx/1e7f6d9597241db0/node_modules',current:'/opt/dsh-021/node_modules'};
for(const [label,root] of Object.entries(roots)){
 const llm=await import(root+'/@deepseek-ai/dsh-llm/lib/index.js');
 const req=createRequire(root+'/@deepseek-ai/dsh-llm/package.json');
 const version=req('./package.json').version;
 console.log(JSON.stringify({label,version,developerMessage:typeof llm.createDeveloperMessage==='function',userSource:llm.createUserMessage({content:[{type:'text',text:'probe'}],source:{kind:'plugin:dsh-evolve',form:'notice'}}).source}));
}
