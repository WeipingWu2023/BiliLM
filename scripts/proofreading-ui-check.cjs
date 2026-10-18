// Synthetic browser fixture only: never sends source text or keys to an external service.
const {chromium}=require(process.env.BILILM_PLAYWRIGHT||'playwright');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const assert=(v,s)=>{if(!v)throw Error(s)};
 const raw=[{start:0,end:4,text:'乒乓球运动员返振东今天归队。'}];
 const choice={id:'proof-ui-run',config:{model:'small'},provenance:'fixture',created_at:'2026-10-18 00:00:00'};
 const video={id:'local:proof-ui',title:'界面测试示例：乒乓球专名校对',creator:'合成夹具，非真实视频或人工真值',thumbnail:'',url:'local-file',duration:4,ready:1,segments:raw,readable:raw[0].text,revision:0,provenance:'fixture',runs:[choice]};
 let run={...choice,raw,proofread:structuredClone(raw),readable_segments:structuredClone(raw),readable:raw[0].text,proof_revision:0,readable_revision:0,mapped:1,audio:null,playback:null,metrics:{},corrections:[],change_log:[],proofreading:null};
 let jobs=[],submitted=false,undone=false;
 try{
  await page.addInitScript(()=>localStorage.setItem('bililm-ai-enabled','false'));
  await page.route('**/api/**',async route=>{
   const req=route.request(),url=decodeURIComponent(new URL(req.url()).pathname);let result;
   const body=req.method()==='GET'?null:req.postDataJSON();assert(!body?.external,'Unexpected external AI request');
   if(url==='/api/videos')result=[video];
   else if(url==='/api/jobs')result=jobs;
   else if(url==='/api/health')result={status:'ok',ffmpeg:true,llm_configured:true};
   else if(url==='/api/llm/settings')result={configured:true,key_saved:true,model:'fixture',auto_enabled:false};
   else if(url==='/api/videos/'+video.id)result=video;
   else if(url==='/api/runs/'+run.id)result=run;
   else if(url.endsWith('/proofread/pipeline')){
    assert(body.proof_revision===0&&body.use_search&&body.glossary.includes('樊振东'),'Wrong proofreading request');submitted=true;
    run={...run,proofread:[{...raw[0],text:'乒乓球运动员樊振东今天归队。'}],readable_segments:[{...raw[0],text:'乒乓球运动员樊振东今天归队。'}],readable:'乒乓球运动员樊振东今天归队。',proof_revision:1,readable_revision:1,
     corrections:[{id:'c1',segment_index:0,before_text:raw[0].text,after_text:'乒乓球运动员樊振东今天归队。',reason:'合成同音和标题规则示例，未听音验证',state:'auto-applied'}],
     proofreading:{status:'completed',model:'fixture',automatic_segments:1,pending_segments:0,batches:1,search_requested:true,search_queries:1,warnings:[],sources:[],rejected:[]}};
    jobs=[{id:'proof-ui-job',video_id:video.id,status:'completed',stage:'AI校对与可读稿已生成（非听音验证）',progress:100}]; result={job_id:'proof-ui-job'};
   }else if(url.endsWith('/proofread/undo')){undone=true;run={...run,proofread:structuredClone(raw),readable_segments:structuredClone(raw),readable:raw[0].text,proof_revision:2,readable_revision:2,proofreading:null,corrections:[]};result={ok:true};}
   else if(url.endsWith('/learning/artifacts'))result=[];
   else if(url.endsWith('/learning'))result={kind:'summary',mode:'local-extractive',run_id:run.id,citations:run.proofread,cached:false,overview:'界面夹具，非 AI 结果。',items:[{text:run.proofread[0].text,citations:[0]}],questions:[],notice:'本地提要，不是 AI。'};
   else if(url==='/api/asr/models')result=[{model:'small',usable:true,runtime_ready:true,cached:true,state:'ready'}];
   else if(url==='/api/asr/hardware')result={hardware:{cpu_threads:4,ram_gib:16,available_ram_gib:8,cuda_devices:0},warnings:{}};
   else throw Error('Unknown fixture URL '+url);
   await route.fulfill({json:result});
  });
  await page.goto('http://127.0.0.1:3000');await page.locator('.video-card').first().click();
  await page.getByRole('tab',{name:'文稿核对',exact:true}).click();await page.getByRole('tab',{name:'校对稿',exact:true}).click();
  await page.getByLabel('校对主题',{exact:true}).fill('乒乓球');await page.getByLabel('校对专名词表',{exact:true}).fill('樊振东、王励勤');
  await page.locator('.ai-proofreading input[type=checkbox]').check();await page.getByRole('button',{name:'AI 语境校对并生成可读稿',exact:true}).click();
  await page.getByText('自动修改 1 段 · 待复核 0 段',{exact:true}).waitFor();
  assert(submitted&&await page.locator('.corrected-text ins').innerText().then(s=>s.includes('樊振东')),'Corrected version not refreshed after queued job');
  const out=path.join(__dirname,'../docs/assets');fs.mkdirSync(out,{recursive:true});await page.locator('.ai-proofreading').screenshot({path:path.join(out,'proofreading-panel.png')});
  await page.getByRole('tab',{name:'可读稿',exact:true}).click();assert(await page.locator('.version-workbench .segment p').first().innerText().then(s=>s.includes('樊振东')),'Readable not generated from corrected version');
  await page.getByRole('button',{name:'撤销最近 AI 校对',exact:true}).click();await page.locator('.ai-proofreading-report').waitFor({state:'detached'});
  assert(undone&&raw[0].text.includes('返振东'),'Undo or raw preservation failed');
  await page.goto('http://127.0.0.1:3000');await page.locator('.quality-controls summary').click();
  const auto=page.getByRole('checkbox',{name:'转录后自动 AI 校对，再生成可读稿',exact:true}),search=page.getByRole('checkbox',{name:'同时联网核对专名拼写（最多 3 次检索）',exact:true});
  assert(await search.isDisabled(),'Search must require automatic proofreading');await auto.check();await search.check();await auto.uncheck();assert(await search.isDisabled()&&!await search.isChecked(),'Disabling AI must also disable search');
  assert(!errors.length,errors.join('\n'));console.log(JSON.stringify({status:'passed',queued_refresh:true,corrected_readable:true,undo:true,raw_unchanged:true,import_options:true,external_requests:0,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
