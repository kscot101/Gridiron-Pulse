'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const feed=JSON.parse(fs.readFileSync('data/player-yardage-outlook.json','utf8'));
 const record=JSON.parse(fs.readFileSync('data/yardage-model-record.json','utf8'));
 const byPos={QB:[],RB:[],WR:[],TE:[]};
 const primary={QB:'passingYards',RB:'scrimmageYards',WR:'receivingYards',TE:'receivingYards'};
 const format=v=>Number(v).toLocaleString('en-US',{maximumFractionDigits:1});
 Object.values(feed.players).forEach(p=>{if(byPos[p.position])byPos[p.position].push(p);});
 assert.ok(Object.values(byPos).every(items=>items.length>=20),'Missing offensive roster coverage');
 const browser=await chromium.launch({headless:true});
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 const results={positions:{},sourceN:Object.fromEntries(Object.entries(byPos).map(([p,items])=>[p,items.length])),sampled:[]};
 const errors=[];
 async function contextFor(options={}){
   const context=await browser.newContext({viewport:{width:1440,height:960},timezoneId:'America/New_York',locale:'en-US',reducedMotion:'reduce'});
   await context.route('**/*',route=>{
     const url=route.request().url();
     if(!url.startsWith(base))return route.abort();
     const u=new URL(url),rel=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
     if(rel==='data/yardage-model-record.json'&&options.recordUnavailable)
       return route.fulfill({status:503,body:'Record temporarily unavailable'});
     if(rel==='data/yardage-model-record.json'&&options.recordMismatch)
       return route.fulfill({contentType:'application/json',body:JSON.stringify({...record,modelVersion:'different-model-version'})});
     const filepath=path.resolve(rel);
     if(filepath.startsWith(process.cwd()+path.sep)&&fs.existsSync(filepath)&&fs.statSync(filepath).isFile())return route.fulfill({path:filepath});
     return route.fulfill({status:404,body:'Not available'});
   });
   return context;
 }
 async function startPage(context){
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.GPYardageOutlook&&window.GPMatchupComparisons&&window.GPPlayerStats,null,{timeout:30000});
   return page;
 }
 async function mountSmoke(page,player,metric){
   await page.evaluate(({player,metric})=>{
     document.querySelectorAll('.gp-yardage-smoke').forEach(el=>el.remove());
     const host=document.createElement('div');host.className='gp-h2h-root gp-yardage-smoke';
     host.innerHTML='<div class="gc-player-intro">Recent games</div><section class="gc-unified-graph" aria-label="Test chart anchor">Weekly chart</section>';
     document.body.appendChild(host);GPYardageOutlook.mount(host,player,{team:'BUF'},metric?{metric}:undefined);
   },{player,metric});
   const host=page.locator('.gp-yardage-smoke');
   await host.locator('.gp-yards-stat').first().waitFor({timeout:30000});return host;
 }
 async function assertOrder(host){
   const ordering=await host.evaluate(el=>{
     const history=el.querySelector('.gp-yards-outlook'),chart=el.querySelector('.gc-unified-graph'),support=el.querySelector('.gp-yards-support');
     return {historyBeforeChart:!!(history.compareDocumentPosition(chart)&Node.DOCUMENT_POSITION_FOLLOWING),
       chartBeforeEstimate:!!(chart.compareDocumentPosition(support)&Node.DOCUMENT_POSITION_FOLLOWING),estimateAfterChart:chart.nextElementSibling===support};
   });
   assert.deepEqual(ordering,{historyBeforeChart:true,chartBeforeEstimate:true,estimateAfterChart:true});
   assert.equal(await host.locator('.gc-unified-graph').count(),1,'Weekly graph must remain one full-width section');
   assert.equal(await host.locator('.gp-yards-prob-grid,.gp-yards-prob,[role="meter"]').count(),0,'Probability badges/meters must not be rendered');
   assert.ok(!/Chance above (season|career) average/.test(await host.innerText()),'Old probability labels remain visible');
 }
 function matchingRecord(key){
   return record.modelVersion===feed.model.version&&record.calibration[key]?.bias===feed.model.calibration[key]?.bias&&
     record.calibration[key]?.sigma===feed.model.calibration[key]?.sigma&&Object.keys(record.configuration).every(k=>record.configuration[k]===feed.model[k]);
 }
 async function assertRecord(host,key){
   const card=host.locator('.gp-yards-model-record');
   if(!matchingRecord(key)){
     await card.getByText('A matching historical model record is not currently available.').waitFor();
     assert.equal(await card.locator('[data-yards-baseline]').count(),0,'Mismatched historical results must not display as current');return false;
   }
   await card.locator('[data-yards-baseline="season"]').waitFor();
   const expected=record.categories[key].all;
   for(const name of ['season','last5']){
     const pair=card.locator('[data-yards-baseline="'+name+'"]'),comparison=expected.comparisons[name];
     assert.equal(await pair.locator('[data-record-model]').innerText(),format(comparison.modelMae)+' yd','Wrong paired model error '+key+' '+name);
     assert.equal(await pair.locator('[data-record-baseline]').innerText(),format(comparison.baselineMae)+' yd','Wrong baseline error '+key+' '+name);
     assert.equal(await pair.locator('.gp-yards-record-sample').innerText(),comparison.n+' matched forecasts','Wrong paired sample size '+key+' '+name);
   }
   const coverage=await card.locator('[data-record-coverage]').innerText();
   assert.ok(coverage.includes(format(expected.range.coverage*100)+'% of '+expected.range.n+' recorded outcomes.'),'Wrong interval coverage '+key);
   assert.ok(coverage.includes(expected.withheldN+' estimates were withheld.'),'Wrong withheld count '+key);
   assert.ok((await card.innerText()).includes(record.testedSeason+' · Weeks '+record.fromWeek+'–'+record.throughWeek),'Historical period must be explicit');
   assert.ok((await card.locator('.gp-yards-method').textContent()).includes('not forecasts saved before kickoff'),'Replay provenance must remain available');return true;
 }
 try{
   const context=await contextFor(),page=await startPage(context);
   for(const position of ['QB','RB','WR','TE']){
     const p=byPos[position].find(x=>x.metrics?.[primary[position]]?.career?.n>=5);assert.ok(p,'Missing tested career record for '+position);
     const host=await mountSmoke(page,p);assert.equal(await host.locator('.gp-yards-stat').count(),4,'Four averages for '+position);
     const chosen=await host.locator('[data-gp-yards-metric]').inputValue();assert.equal(chosen,primary[position]);
     assert.deepEqual(await host.locator('.gp-yards-stat small').allTextContents(),['Career average','Season average','Last 5 average','H2H vs BUF']);
     assert.equal(await host.locator('.gp-yards-stat').first().locator('strong').innerText(),format(p.metrics[chosen].career.value),'Career card must use verified source');
     const hasRange=await host.locator('[data-yards-projected]').count()===1;
     if(!hasRange)assert.equal(await host.locator('.gp-yards-support .gp-yards-limited').count(),1,'Unavailable estimate must explain why');
     await assertOrder(host);const hasRecord=await assertRecord(host,position+'_'+chosen);
     results.positions[position]={id:p.id,name:p.name,metric:chosen,withRange:hasRange,withRecord:hasRecord};
     const alternateMetrics=await host.locator('[data-gp-yards-metric] option').evaluateAll(options=>options.map(option=>option.value));
     for(const metric of alternateMetrics.filter(metric=>metric!==chosen)){
       await host.locator('[data-gp-yards-metric]').selectOption(metric);
       assert.equal(await host.locator('[data-gp-yards-metric]').inputValue(),metric);
       assert.equal(await host.locator('.gp-yards-support').getAttribute('data-metric'),metric);
       await assertRecord(host,position+'_'+metric);
     }
   }
   const guards=await page.evaluate(()=>{
     const m=GPYardageOutlook,result={historyN:5,forecast:80,season:70,career:65},calibration={sigma:40,bias:0},check={holdoutN:100,holdout2025Coverage80:.8};
     return {cdfZero:m.normalCDF(0),limited:m.predict({...result,historyN:4},calibration,check,true,true),
       noOpponent:m.predict(result,calibration,check,false,true),stale:m.predict(result,calibration,check,true,false),
       insufficientValidation:m.predict(result,calibration,{...check,holdoutN:79},true,true),badCoverage:m.predict(result,calibration,{...check,holdout2025Coverage80:.5},true,true)};
   });
   assert.ok(Math.abs(guards.cdfZero-.5)<.000001);
   for(const key of ['limited','noOpponent','stale','insufficientValidation','badCoverage'])assert.equal(guards[key],null,key+' gate must remain enforced');
   results.gatesPassed=true;
   for(const width of [390,320]){
     await page.setViewportSize({width,height:870});
     for(const section of ['.gp-yards-outlook','.gp-yards-support']){
       const size=await page.locator('.gp-yardage-smoke '+section).evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
       assert.ok(size.scroll<=size.client+3,'Section overflow at '+width+' '+section+': '+JSON.stringify(size));results.sampled.push({width,section,...size});
     }
   }
   const limited=Object.values(feed.players).find(p=>p.metrics?.[primary[p.position]]?.career?.n>0&&p.metrics[primary[p.position]].career.n<5);
   assert.ok(limited,'Need a real insufficient-history player for DOM check');
   const limitedHost=await mountSmoke(page,limited);assert.equal(await limitedHost.locator('.gp-yards-stat').count(),4,'Short histories must still show historical inputs');
   assert.equal(await limitedHost.locator('[data-yards-projected]').count(),0,'Short histories must not receive a range');
   assert.ok((await limitedHost.locator('.gp-yards-support .gp-yards-limited').innerText()).includes('fewer than five recorded appearances'));
   results.limitedHistoryPlayer={id:limited.id,name:limited.name};
   // Exercise the actual profile and both directions of yardage/chart selection.
   await page.setViewportSize({width:1440,height:960});
   const qb=byPos.QB.find(x=>x.name==='Patrick Mahomes')||byPos.QB.find(x=>x.metrics?.passingYards?.career?.n>=5);
   await page.evaluate(qb=>GPPlayerStats.open({name:qb.name,id:qb.id,team:qb.team,position:qb.position,espnId:qb.espnId}),qb);
   const profile=page.locator('#detail-overlay.open');
   await profile.locator('.gc-unified-graph').waitFor({timeout:30000});await profile.locator('.gp-yards-stat').first().waitFor({timeout:30000});await assertOrder(profile);
   assert.equal(await profile.locator('.gc-chart-reference').getAttribute('open'),null,'Duplicate chart reference values should start collapsed');
   assert.equal(await profile.locator('.gc-chart-reference [data-gc-summary]').count(),4,'Chart reference values must remain accessible');
   await profile.locator('[data-gp-yards-metric]').selectOption('rushingYards');
   await page.waitForFunction(()=>document.querySelector('#detail-overlay.open [data-gc-player-stat]')?.value==='rushingYards'&&document.querySelector('#detail-overlay.open .gp-yards-support')?.dataset.metric==='rushingYards');
   await assertRecord(profile,'QB_rushingYards');assert.equal(await profile.locator('[data-gc-metric="rushingYards"]').getAttribute('aria-pressed'),'true');
   await profile.locator('[data-gc-metric="passingYards"]').click();
   await page.waitForFunction(()=>document.querySelector('#detail-overlay.open [data-gp-yards-metric]')?.value==='passingYards'&&document.querySelector('#detail-overlay.open .gp-yards-support')?.dataset.metric==='passingYards');
   await assertRecord(profile,'QB_passingYards');await assertOrder(profile);results.profileIntegrated=true;results.metricSelectionSynced=true;
   await page.screenshot({path:'yardage-outlook-desktop.png'});
   for(const width of [390,320]){
     await page.setViewportSize({width,height:870});
     for(const section of ['.gp-yards-outlook','.gp-yards-support']){
       const size=await profile.locator(section).evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
       assert.ok(size.scroll<=size.client+3,'Profile overflow at '+width+' '+section+': '+JSON.stringify(size));results.sampled.push({width,section,profile:true,...size});
     }
     if(width===390)await page.screenshot({path:'yardage-outlook-mobile.png'});
   }
   // WR rushing is offered by the history selector and must also exist in the chart.
   await page.setViewportSize({width:1440,height:960});
   const wr=byPos.WR.find(x=>x.name==='Justin Jefferson')||byPos.WR.find(x=>x.metrics?.receivingYards?.career?.n>=5);
   await page.evaluate(wr=>GPPlayerStats.open({name:wr.name,id:wr.id,team:wr.team,position:wr.position,espnId:wr.espnId}),wr);
   await page.waitForFunction(()=>document.querySelector('#detail-overlay.open .gp-yards-support')?.dataset.metric==='receivingYards'&&
     !document.querySelector('#detail-overlay.open [data-gp-yards-metric] option[value="passingYards"]'));
   await assertRecord(profile,'WR_receivingYards');
   await profile.locator('[data-gp-yards-metric]').selectOption('rushingYards');
   await page.waitForFunction(()=>document.querySelector('#detail-overlay.open [data-gc-player-stat]')?.value==='rushingYards'&&
     document.querySelector('#detail-overlay.open .gp-yards-support')?.dataset.metric==='rushingYards');
   await assertRecord(profile,'WR_rushingYards');
   assert.equal(await profile.locator('[data-gc-metric="rushingYards"]').getAttribute('aria-pressed'),'true');
   await profile.locator('[data-gc-metric="receivingYards"]').click();
   await page.waitForFunction(()=>document.querySelector('#detail-overlay.open [data-gp-yards-metric]')?.value==='receivingYards'&&
     document.querySelector('#detail-overlay.open .gp-yards-support')?.dataset.metric==='receivingYards');
   await assertOrder(profile);results.wrRushingSynced=true;
   await context.close();
   // Optional evidence availability must not gate the history or valid estimate.
   for(const scenario of ['recordUnavailable','recordMismatch']){
     const optionalContext=await contextFor({[scenario]:true}),optionalPage=await startPage(optionalContext),host=await mountSmoke(optionalPage,qb);
     const expected=scenario==='recordUnavailable'?'Historical model record temporarily unavailable.':'A matching historical model record is not currently available.';
     await host.locator('.gp-yards-model-record').getByText(expected).waitFor();assert.equal(await host.locator('.gp-yards-stat').count(),4);
     assert.equal(await host.locator('[data-yards-projected]').count(),1,'Record availability must not gate a valid estimate');
     await assertOrder(host);results[scenario]=true;await optionalContext.close();
   }
   assert.equal(errors.filter(e=>/SyntaxError|ReferenceError|TypeError/.test(e)).length,0,errors.join('\n'));
   results.passed=true;results.errors=errors;fs.writeFileSync('yardage-outlook-verification.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
 }catch(e){fs.writeFileSync('yardage-outlook-verification.json',JSON.stringify({passed:false,error:String(e),...results,errors},null,2));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
