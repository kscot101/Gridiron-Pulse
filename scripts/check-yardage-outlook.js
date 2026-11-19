'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const feed=JSON.parse(fs.readFileSync('data/player-yardage-outlook.json','utf8'));
 const byPos={QB:[],RB:[],WR:[],TE:[]};
 Object.values(feed.players).forEach(p=>{if(byPos[p.position])byPos[p.position].push(p);});
 assert.ok(Object.values(byPos).every(items=>items.length>=20),'Missing roster coverage for offensive positions');
 const browser=await chromium.launch({headless:true});
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 const context=await browser.newContext({viewport:{width:1440,height:960},timezoneId:'America/New_York',reducedMotion:'reduce'});
 await context.route('**/*',route=>{
   const url=route.request().url();
   if(url.startsWith(base)){
     const u=new URL(url);
     const rel=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
     const filepath=path.resolve(rel);
     if(filepath.startsWith(process.cwd()+path.sep)&&fs.existsSync(filepath)&&fs.statSync(filepath).isFile())
       return route.fulfill({path:filepath});
     return route.fulfill({status:404,body:'Not available'});
   }
   return route.abort();
 });
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const results={positions:{},sourceN:Object.fromEntries(Object.entries(byPos).map(([p,items])=>[p,items.length])),sampled:[]};
 try{
   await page.goto(base,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.GPYardageOutlook && window.GPMatchupComparisons && window.GPPlayerStats,{timeout:30000});
   for(const position of ['QB','RB','WR','TE']){
     const p=byPos[position].find(x=>(x.metrics||{})[(position==='QB'?'passingYards':position==='RB'?'scrimmageYards':'receivingYards')]?.career?.n>=5);
     assert.ok(p,'Missing tested career record for '+position);
     await page.evaluate(p=>{
       document.querySelectorAll('.gp-yardage-smoke').forEach(el=>el.remove());
       const host=document.createElement('div');
       host.className='gp-h2h-root gp-yardage-smoke';
       host.innerHTML='<div class="gc-player-intro"></div>';
       document.body.appendChild(host);
       GPYardageOutlook.mount(host,p,{team:'BUF'});
     },p);
     const host=page.locator('.gp-yardage-smoke');
     await host.locator('.gp-yards-outlook .gp-yards-stat').first().waitFor({timeout:30000});
     assert.equal(await host.locator('.gp-yards-stat').count(),4,'Four averages for '+position);
     const counts=await host.locator('.gp-yards-stat').evaluateAll(nodes=>nodes.map(node=>node.textContent.trim()));
     assert.ok(counts.join(' ').includes('Career average'),'Missing career benchmark '+position);
     assert.ok(counts.join(' ').includes('Season average'),'Missing season benchmark '+position);
     assert.ok(counts.join(' ').includes('Last 5'),'Missing last-five benchmark '+position);
     assert.ok(counts.join(' ').includes('H2H'),'Missing opponent history '+position);
     const chosen=await host.locator('[data-gp-yards-metric]').inputValue();
     assert.ok(p.metrics[chosen],'Yardage metric does not map to verified source '+position);
     const visibleCareer=await host.locator('.gp-yards-stat').first().locator('strong').innerText();
     const expectCareer=p.metrics[chosen].career.value;
     assert.equal(visibleCareer,expectCareer==null?'—':Number(expectCareer).toLocaleString(undefined,{maximumFractionDigits:1}));
     const probPanel=await host.locator('.gp-yards-prob-grid').count();
     if(probPanel){
       const values=await host.locator('[role="meter"]').evaluateAll(nodes=>nodes.map(el=>Number(el.getAttribute('aria-valuenow'))));
       assert.ok(values.every(v=>v>=0&&v<=100));
       assert.equal(values.length,p.metrics[chosen].season&&p.metrics[chosen].season.value!=null?2:1,
         'Season probabilities are unavailable when season average is missing: '+position);
     }else{
       assert.equal(await host.locator('.gp-yards-limited').count(),1,'Insufficient history must show reason');
     }
     results.positions[position]={id:p.id,name:p.name,metric:chosen,withRange:Boolean(probPanel)};
     if(position==='RB'){
       await host.locator('[data-gp-yards-metric]').selectOption('rushingYards');
       assert.equal(await host.locator('[data-gp-yards-metric]').inputValue(),'rushingYards');
     }
     if(position==='QB')await page.screenshot({path:'yardage-outlook-desktop.png'});
   }
   const selectors=await page.evaluate(()=>{
     const m=GPYardageOutlook;
     return {cdfZero:m.normalCDF(0),limited:m.predict(
       {historyN:4},{sigma:40,bias:0},{holdoutN:100,holdout2025Coverage80:.8},true,true)};
   });
   assert.ok(Math.abs(selectors.cdfZero-.5)<.000001);
   assert.equal(selectors.limited,null,'Fewer than 5 appearances must not get probability');
   for(const width of [390,320]){
     await page.setViewportSize({width,height:870});
     const size=await page.locator('.gp-yardage-smoke .gp-yards-outlook').evaluate(el=>({
       client:el.clientWidth,scroll:el.scrollWidth
     }));
     assert.ok(size.scroll<=size.client+3,'Yardage card overflow at '+width+': '+JSON.stringify(size));
     results.sampled.push({width,...size});
     if(width===390)await page.screenshot({path:'yardage-outlook-mobile.png'});
   }
   // Confirm integration in the same player profile used by every page, not
   // exclusively with the Featured Picks component.
   await page.setViewportSize({width:1440,height:960});
   const qb=byPos.QB.find(x=>x.name==='Patrick Mahomes')||byPos.QB[0];
   await page.evaluate(qb=>GPPlayerStats.open({name:qb.name,id:qb.id,team:qb.team,position:qb.position,espnId:qb.espnId}),qb);
   await page.locator('#detail-overlay.open .gc-unified-graph').waitFor({timeout:30000});
   await page.locator('#detail-overlay.open .gp-yards-outlook').waitFor({timeout:30000});
   assert.equal(await page.locator('#detail-overlay.open .gc-unified-graph').count(),1,'Weekly chart must remain intact');
   results.profileIntegrated=true;
   assert.equal(errors.filter(e=>/SyntaxError|ReferenceError|TypeError/.test(e)).length,0,errors.join('\n'));
   results.passed=true;results.errors=errors;
   fs.writeFileSync('yardage-outlook-verification.json',JSON.stringify(results,null,2));
   console.log(JSON.stringify(results,null,2));
 }catch(e){
   fs.writeFileSync('yardage-outlook-verification.json',JSON.stringify({passed:false,error:String(e),...results,errors},null,2));
   throw e;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
