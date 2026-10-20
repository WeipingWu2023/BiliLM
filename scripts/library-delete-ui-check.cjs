// Browser-only fixtures. Never deletes a user's real notes or calls an AI provider.
const {chromium}=require(process.env.BILILM_PLAYWRIGHT||'playwright');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(10000);page.setDefaultNavigationTimeout(60000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const assert=(value,message)=>{if(!value)throw Error(message)};
 const notes=[{id:'local:delete-fixture',title:'界面测试示例：整理完成的学习笔记',creator:'合成夹具，非私人来源',thumbnail:'',duration:120,ready:1,provenance:'fixture'},{id:'local:keep-fixture',title:'界面测试示例：另一份笔记',creator:'合成夹具',thumbnail:'',duration:60,ready:1,provenance:'fixture'}];
 let trashed=false,fail=false,deletes=0,restores=0,opened=0;
 try{
  await page.route('**/api/**',async route=>{
   const req=route.request(),url=new URL(req.url()),endpoint=decodeURIComponent(url.pathname);let result;
   if(endpoint==='/api/videos')result=url.searchParams.get('trash')==='true'?(trashed?[notes[0]]:[]):notes.filter((_,i)=>i!==0||!trashed);
   else if(endpoint==='/api/videos/'+notes[0].id&&req.method()==='DELETE'){
    deletes++;if(fail){await route.fulfill({status:500,json:{detail:'模拟删除失败，笔记未改变'}});return;}trashed=true;result={ok:true};
   }else if(endpoint==='/api/videos/'+notes[0].id+'/restore'){restores++;trashed=false;result={ok:true};}
   else if(endpoint==='/api/jobs')result=[];
   else if(endpoint==='/api/health')result={status:'ok',ffmpeg:true,llm_configured:false};
   else if(endpoint==='/api/asr/models')result=[];
   else if(endpoint==='/api/asr/hardware')result={hardware:{cpu_threads:4,ram_gib:16,cuda_devices:0},warnings:{}};
   else{opened++;throw Error('Unexpected fixture URL '+endpoint)}
   await route.fulfill({json:result});
  });
  await page.goto('http://127.0.0.1:3000');await page.locator('.video-card').nth(1).waitFor();
  const remove=()=>page.getByRole('button',{name:'删除笔记：'+notes[0].title,exact:true});
  page.once('dialog',async dialog=>{assert(dialog.message().includes(notes[0].title),'Confirmation must identify the note');await dialog.dismiss()});await remove().click();assert(deletes===0,'Cancel still deleted note');
  page.once('dialog',dialog=>dialog.accept());await remove().click();await page.getByRole('button',{name:'撤销删除',exact:true}).waitFor();assert(await page.locator('.video-card').count()===1,'Card was not removed');assert(opened===0,'Delete opened the note');
  await page.getByRole('button',{name:'撤销删除',exact:true}).click();await page.locator('.video-card').nth(1).waitFor();assert(restores===1,'Undo failed');
  page.once('dialog',dialog=>dialog.accept());await remove().click();await page.getByRole('button',{name:'关闭删除提示',exact:true}).click();
  await page.reload();await page.locator('.video-card').first().waitFor();assert(await page.locator('.video-card').count()===1,'Deleted note reappeared on reload');
  await page.getByRole('button',{name:'回收站',exact:true}).click();await page.getByRole('button',{name:'恢复笔记：'+notes[0].title,exact:true}).waitFor();assert(await page.locator('.video-card').count()===1,'Trash mixed active notes');
  await page.getByRole('button',{name:'恢复笔记：'+notes[0].title,exact:true}).click();await page.getByRole('heading',{name:'回收站为空',exact:true}).waitFor();
  await page.getByRole('button',{name:'返回资料库',exact:true}).click();await page.locator('.video-card').nth(1).waitFor();
  fail=true;page.once('dialog',dialog=>dialog.accept());await remove().click();await page.getByText('模拟删除失败，笔记未改变',{exact:true}).waitFor();assert(await page.locator('.video-card').count()===2,'Failure removed a card');await page.getByRole('alert').getByRole('button',{name:'关闭',exact:true}).click();
  const out=path.join(__dirname,'../docs/assets');fs.mkdirSync(out,{recursive:true});await page.locator('.library-section').screenshot({path:path.join(out,'library-delete.png')});
  await page.getByRole('button',{name:'切换深色',exact:true}).click();assert(await remove().isVisible(),'Delete action hidden in dark mode');
  for(const width of [390,320]){await page.setViewportSize({width,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow '+width);assert(await remove().isVisible(),'Delete hidden on mobile');}
  assert(!errors.length,errors.join('\n'));console.log(JSON.stringify({status:'passed',confirmation:true,cancel:true,undo:true,trash:true,restore:true,reload:true,error_recovery:true,mobile:true,fixture_only:true,deletes,restores,opened,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
