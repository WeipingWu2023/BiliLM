// Synthetic browser fixtures: no private sources, paid AI calls or server mutations.
const {chromium}=require(process.env.BILILM_PLAYWRIGHT||'playwright');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.setDefaultTimeout(10000); page.setDefaultNavigationTimeout(60000); page.on('pageerror',e=>errors.push(e.message));
 const assert=(condition,message)=>{if(!condition)throw Error(message)};
 const raw=[{start:0,end:4,text:'乒乓球运动员返振东今天归队。'}];
 let segments=[{...raw[0],text:'乒乓球运动员樊振东今天归队。'}],revision=1,phase='processing',summaryCalls=0,mapCalls=0,retries=0,imports=[];
 const video={id:'local:final-ui',title:'界面测试示例：自动生成学习笔记',creator:'合成夹具，非真实视频或人工真值',thumbnail:'',url:'local-file',duration:4,ready:1,segments:raw,readable:raw[0].text,revision:0,provenance:'fixture',runs:[{id:'final-ui-run',config:{model:'small'},created_at:'2026-10-18 00:00:00'}]};
 const artifact=kind=>({id:kind+'-'+revision,kind,mode:'llm',run_id:'final-ui-run',citations:segments,overview:'樊振东相关内容的合成总结。',items:[{text:segments[0].text,citations:[0]}],questions:['这份来源讲了什么？'],branches:[{text:'运动员',citations:[0],children:[{text:'樊振东',citations:[0]}]}],notice:'合成界面测试，不是真实 AI 结果。',cached:false});
 try{
  await page.addInitScript(()=>localStorage.setItem('bililm-ai-enabled','false'));
  await page.route('**/api/**',async route=>{
   const request=route.request(),endpoint=decodeURIComponent(new URL(request.url()).pathname),body=request.method()==='GET'?null:request.postDataJSON();let result;
   if(endpoint==='/api/videos')result=[video];
   else if(endpoint==='/api/jobs')result=[];
   else if(endpoint==='/api/health')result={status:'ok',ffmpeg:true,llm_configured:true};
   else if(endpoint==='/api/llm/settings')result={configured:true,key_saved:true,model:'fixture',auto_enabled:true};
   else if(endpoint==='/api/videos/'+video.id)result=video;
   else if(endpoint.endsWith('/finalize')){if(body.retry){retries++;phase='processing'}result=phase==='ready'?{status:'ready',message:'文稿已自动校对',run_id:'final-ui-run',revision,segments,readable:segments.map(s=>s.text).join('\n\n'),playback:false}:{status:phase,message:phase==='failed'?'文稿整理未完成，请重试。':'正在自动整理文稿…'};}
   else if(endpoint==='/api/runs/final-ui-run')result={proofread:segments};
   else if(endpoint.endsWith('/final/export')){assert(phase==='ready','Premature download');await route.fulfill({body:'# 合成测试\n\n'+segments[0].text,headers:{'Content-Disposition':'attachment; filename="bililm-final.md"'}});return;}
   else if(endpoint.endsWith('/final')&&request.method()==='PUT'){assert(body.revision===revision,'Stale editor');segments=segments.map((s,i)=>({...s,text:body.texts[i]}));revision++;result={status:'ready',message:'文稿已自动校对',run_id:'final-ui-run',revision,segments,readable:segments.map(s=>s.text).join('\n\n')};}
   else if(endpoint.endsWith('/learning/artifacts'))result=[{...artifact('summary'),id:'old-raw-result',stale:true,overview:raw[0].text}];
   else if(endpoint.endsWith('/learning')){assert(phase==='ready','Summary requested before proofreading');assert(body.final===true,'Learning must require final source');assert(body.external===true,'Saved AI must be automatic even with old browser preference');if(body.kind==='summary')summaryCalls++;else mapCalls++;result=artifact(body.kind);}
   else if(endpoint.endsWith('/ask')){assert(body.final,'Question used unfinalized source');result={mode:'llm',answer:segments[0].text,citations:segments};}
   else if(endpoint==='/api/asr/models')result=[];
   else if(endpoint==='/api/asr/hardware')result={hardware:{cpu_threads:4,ram_gib:16,available_ram_gib:8,cuda_devices:0},warnings:{}};
   else if(endpoint==='/api/imports'){imports.push(body);result={video_id:video.id,cached:true};}
   else throw Error('Unknown fixture URL '+endpoint);
   await route.fulfill({json:result});
  });
  await page.goto('http://127.0.0.1:3000');
  assert(await page.getByRole('checkbox',{name:/AI 校对|联网核对/}).count()===0,'Manual AI toggles remain');
  await page.locator('.video-card').first().click();await page.getByText('正在生成最终文稿，完成后自动总结…').waitFor();
  assert(summaryCalls===0,'Uncorrected summary generated');assert(!(await page.locator('body').innerText()).includes('返振东'),'Raw text leaked before ready');
  assert(await page.locator('.studio-export').getAttribute('href')===null,'Download enabled too early');
  phase='ready';await page.locator('.learning-summary li').first().waitFor();
  assert(summaryCalls>0,'Automatic summary missing');assert(!(await page.locator('body').innerText()).includes('返振东'),'Raw history leaked');
  await page.getByRole('tab',{name:'完整文稿',exact:true}).click();await page.locator('.final-ready').waitFor();
  assert(await page.getByRole('tab',{name:'原始稿',exact:true}).count()===0,'Raw version tab remains');
  assert(await page.getByRole('button',{name:/接受|AI 语境校对/}).count()===0,'Manual correction choices remain');
  assert((await page.locator('.final-readable').innerText()).includes('樊振东'),'Final transcript missing');
  const download=page.waitForEvent('download');await page.getByLabel('下载文稿',{exact:true}).click();const file=await download;const content=fs.readFileSync(await file.path(),'utf8');assert(content.includes('樊振东')&&!content.includes('返振东')&&!content.includes('[00:'),'Wrong download content');
  await page.getByRole('button',{name:'编辑文稿',exact:true}).click();await page.getByLabel('编辑片段 1',{exact:true}).fill('乒乓球运动员樊振东回到国家队。');await page.getByRole('button',{name:'保存修改',exact:true}).click();await page.getByRole('button',{name:'编辑文稿',exact:true}).waitFor();assert(revision===2,'Edit not shared');
  console.log('Final reading, download and edit passed'); const out=path.join(__dirname,'../docs/assets');fs.mkdirSync(out,{recursive:true});await page.locator('.final-workbench').screenshot({path:path.join(out,'final-transcript.png')});
  await page.getByRole('tab',{name:'来源问答',exact:true}).click();await page.locator('.studio-tool').filter({hasText:'思维导图'}).click();await page.locator('.studio-result').filter({hasText:'思维导图'}).waitFor();assert(mapCalls===1,'Map did not use final source');
  await page.locator('.studio-result').filter({hasText:'思维导图'}).click();await page.locator('.map-viewer').waitFor();await page.locator('.map-links path').first().waitFor({state:'attached'});await page.getByRole('button',{name:'关闭思维导图'}).click();
  console.log('Final map passed'); await page.getByLabel('向来源提问',{exact:true}).fill('讲了谁？');await page.getByRole('button',{name:'发送来源问题',exact:true}).click();await page.locator('.learning-turn').waitFor();
  await page.screenshot({path:path.join(out,'final-workspace-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow');
  phase='failed';await page.reload();await page.locator('.video-card').first().click();await page.getByRole('tab',{name:'完整文稿',exact:true}).click();await page.getByRole('button',{name:'重新处理',exact:true}).waitFor();const previous=summaryCalls;await page.waitForTimeout(3300);assert(retries===0&&summaryCalls===previous,'Failure silently retried or summarized raw');
  await page.getByRole('button',{name:'重新处理',exact:true}).click();assert(retries===1,'Explicit failure recovery missing');
  assert(!errors.length,errors.join('\n'));console.log(JSON.stringify({status:'passed',automatic:true,no_manual_proofreading:true,no_raw_ui:true,final_download:true,final_learning:true,edits:true,failure_recovery:true,mobile:true,fixture_only:true,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
