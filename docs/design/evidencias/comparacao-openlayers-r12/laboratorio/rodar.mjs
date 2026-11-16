import {chromium} from '/workspace/Raiz-mapa-integrado/front/globo/node_modules/playwright/index.mjs';import fs from 'node:fs';import path from 'node:path';
const dir='/tmp/raiz-comparacao-openlayers-corrigida';const mode=process.argv[2]||'functional';const out=dir+'/'+mode;fs.mkdirSync(out,{recursive:true});const executablePath='/tmp/raiz-chrome157/chrome-linux64/chrome';
const flags=['--no-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'];
const order=['ml','ol','ol','ml','ml','ol','ol','ml'];const runs=mode.startsWith('functional')?[['com','ml',360],['com','ol',360],['sem','ml',360],['sem','ol',360],['com','ml',960],['com','ol',960],['sem','ml',960],['sem','ol',960]]:['com','sem'].flatMap(c=>order.map((e,i)=>[c,e,360,i]));
for(const [caseName,engine,width,ordinal=0] of runs){const tag=`${caseName}-${width}-${String(ordinal).padStart(2,'0')}-${engine}`;const begin=new Date().toISOString();const browser=await chromium.launch({executablePath,headless:true,args:flags});const context=await browser.newContext({viewport:{width,height:740},deviceScaleFactor:1});const page=await context.newPage();const cdp=await context.newCDPSession(page);const bad=[],requests=[],errors=[],cancellations=[];let result;
 try{
  page.on('response',r=>{requests.push({url:r.url(),status:r.status()});if(r.status()>=400)bad.push({url:r.url(),status:r.status()})});page.on('requestfailed',r=>{const item={url:r.url(),error:r.failure()?.errorText,type:r.resourceType()};if(item.error==='net::ERR_ABORTED'&&['image','fetch'].includes(item.type)&&item.url.startsWith('http://127.0.0.1:8765/tiles/')&&fs.existsSync(dir+'/dist'+new URL(item.url).pathname))cancellations.push(item);else bad.push(item)});page.on('pageerror',e=>errors.push(e.message));
  await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});await cdp.send('Performance.enable');
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:1600000/8,uploadThroughput:750000/8});
  await page.goto(`http://127.0.0.1:8765/?engine=${engine}&case=${caseName}`,{waitUntil:'domcontentloaded',timeout:90000});
  await page.waitForFunction(()=>window.__ready||window.__failed,{},{timeout:90000});
  const state=await page.evaluate(()=>({failed:window.__failed,errors:window.__errors,mapErrors:window.__mapErrors||[],marks:window.lab?.marks,tests:window.lab?.testResults,points:window.lab?.controlPoints,info:window.lab?.info}));
  if(state.failed||state.errors.length||state.mapErrors.length)throw new Error(JSON.stringify(state));
  if(state.tests.some(t=>t.expected!==t.actual))throw new Error('Hit-test divergente: '+JSON.stringify(state.tests));
  const resources=await page.evaluate(()=>performance.getEntriesByType('resource').map(r=>({name:r.name,transferSize:r.transferSize,encodedBodySize:r.encodedBodySize,decodedBodySize:r.decodedBodySize,start:r.startTime,end:r.responseEnd})));
  if(mode.startsWith('functional')){
   await page.screenshot({path:out+'/'+tag+'-normal.png'});
   const id=await page.evaluate(()=>window.lab.scenario.target);await page.evaluate(id=>window.lab.hover(id),id);await page.screenshot({path:out+'/'+tag+'-hover.png'});await page.evaluate(()=>window.lab.hover(null));
   await page.evaluate(id=>window.lab.select(id),id);await page.screenshot({path:out+'/'+tag+'-selected.png'});await page.locator('#mapa').focus();await page.keyboard.press('Escape');const cleared=await page.evaluate(()=>window.lab.settle());if(cleared.selected!==null)throw new Error('Escape não limpou seleção');await page.keyboard.press('Enter');const entered=await page.evaluate(()=>window.lab.settle());if(entered.selected!==id)throw new Error('Enter não selecionou imóvel');await page.evaluate(()=>window.lab.reset());
   const smokeInteractions=mode!=='functional'&&width===360?await page.evaluate(()=>window.lab.run()):null;result={begin,caseName,engine,width,ordinal,state,resources,requests,bad,errors,cancellations,smokeInteractions,limits:'Ensaio funcional, excluído das métricas pré-fixadas'};
  }else{
   const interaction=await page.evaluate(()=>window.lab.run());const performanceMetrics=await cdp.send('Performance.getMetrics');
   result={begin,caseName,engine,width,ordinal,state,interaction,performanceMetrics,resources,requests,bad,errors,cancellations};
  }
  const finalErrors=await page.evaluate(()=>({page:window.__errors,source:window.__mapErrors||[]}));result.finalErrors=finalErrors;if(bad.length||errors.length||finalErrors.page.length||finalErrors.source.length)throw new Error(JSON.stringify({bad,errors,finalErrors}));
  fs.writeFileSync(out+'/'+tag+'.json',JSON.stringify(result,null,2));console.log(tag,'ok',Math.round(state.marks.complete-state.marks.start));
 }catch(e){fs.writeFileSync(out+'/'+tag+'-FALHA.json',JSON.stringify({begin,caseName,engine,width,ordinal,error:e.stack,bad,requests,errors,result},null,2));throw e}finally{await browser.close()}
}
