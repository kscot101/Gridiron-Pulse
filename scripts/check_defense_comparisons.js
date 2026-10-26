'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 const defense=JSON.parse(fs.readFileSync('data/team-defense.json','utf8'));
 const players=JSON.parse(fs.readFileSync('data/defense-players.json','utf8'));
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'America/New_York',reducedMotion:'reduce'});
 await context.route('**/*',async r=>{
  const u=new URL(r.request().url());
  if(r.request().url().startsWith(base)){
   const file=path.resolve(decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html');
   if(file.startsWith(process.cwd()+path.sep)&&fs.existsSync(file)&&fs.statSync(file).isFile())return r.fulfill({path:file});
   return r.fulfill({status:404,body:'Not found'});
  }
  return r.abort();
 });
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const report={mode:'Controlled browser test of unchanged downloaded statistical inputs; external APIs blocked',testedAt:new Date().toISOString(),through:defense.through};
 try{
  await page.goto(base+'team.html?team=KC',{waitUntil:'domcontentloaded'});
  await page.locator('[data-defense-metric="passYards"]').waitFor();
  assert.match(await page.locator('#team-title').innerText(),/Kansas City/);
  for(const key of ['overview','pass','run','qb','rb','wr','te','disruption','recent']){
   await page.locator('[data-defense-tab="'+key+'"]').click();
   assert.equal(await page.locator('[role="tab"][aria-selected=true]').getAttribute('data-defense-tab'),key);
   const checks=await page.locator('[data-defense-metric]').evaluateAll((cards,source)=>cards.every(card=>{
    const key=card.dataset.defenseMetric;
    return Array.from(card.querySelectorAll('[data-series]')).every(row=>{
     const series=row.dataset.series,s=series==='league'?source.league[key]:source.teams.KC.averages[series][key];
     const raw=row.querySelector('[data-value]').dataset.value;
     return s.value==null?raw==='':Math.abs(Number(raw)-s.value)<.00001;
    });
   }),defense);
   assert.equal(checks,true,'Rendered bars must match stored numerical summaries');
  }
  report.teamTabs=9;report.exactTeamValues=true;
  await page.locator('[data-defense-tab="overview"]').click();
  await page.screenshot({path:'defense-team-desktop.png'});
  for(const code of Object.keys(defense.teams)){
   await page.selectOption('#team-select',code);
   assert.equal(await page.locator('.gc-defense').getAttribute('data-team'),code);
  }
  report.teamSelector=32;await page.selectOption('#team-select','KC');
  report.widths=[];
  for(const width of [1440,1024,768,390,320]){
   await page.setViewportSize({width,height:900});
   const size=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));report.widths.push(size);
   assert.ok(size.scrollWidth<=width+2,'Team page overflow '+JSON.stringify(size));
   if(width===390)await page.screenshot({path:'defense-team-mobile.png'});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.GPPlayerStats&&window.GPMatchupComparisons);
  const p=Object.values(players.players).find(p=>p.name==='Patrick Mahomes');assert.ok(p);
  await page.evaluate(p=>GPPlayerStats.open({name:p.name,id:p.id,team:p.team,position:p.position}),p);
  await page.locator('.gc-player select').waitFor({timeout:30000});
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.gc-player [data-series="season"] [data-value]')).some(n=>n.dataset.value!==''));
  assert.equal(await page.locator('.gc-player').count(),1);
  const season=Number(await page.locator('.gc-player [data-series="season"] [data-value]').getAttribute('data-value'));
  assert.ok(Math.abs(season-p.averages.season.passingYards.value)<.00001);
  assert.equal(await page.locator('.gc-player select').inputValue(),'passingYards');
  await page.locator('.gc-player select').selectOption('passingTD');
  assert.ok(Math.abs(Number(await page.locator('.gc-player [data-series="season"] [data-value]').getAttribute('data-value'))-p.averages.season.passingTD.value)<.00001);
  await page.locator('.gc-player select').selectOption('passingYards');
  const openProfiles=await page.evaluate(()=>document.querySelectorAll('dialog.gp-player-dialog[open],#detail-overlay.open').length);
  assert.equal(openProfiles,1);assert.equal(await page.locator('.gp-recent-root').count(),1);
  report.playerBars=true;report.exactPlayerValues=true;report.singlePopup=true;
  await page.screenshot({path:'defense-player-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
  await page.screenshot({path:'defense-player-mobile.png'});await page.keyboard.press('Escape');
  await page.evaluate(()=>{document.getElementById('detail-body').innerHTML='';GPMatchupComparisons.mountTeam({abbreviation:'KC'},document.getElementById('detail-body'));openOverlay('detail-overlay');});
  await page.locator('#detail-body [data-defense-metric="passYards"]').waitFor();
  assert.equal(await page.locator('#detail-body .gc-defense').count(),1);
  assert.equal(await page.locator('#detail-body .gc-page-link').getAttribute('href'),'team.html?team=KC');
  report.teamProfile=true;await page.keyboard.press('Escape');
  const bars=await page.evaluate(()=>GPMatchupComparisons.bars([{label:'Negative',value:-2},{label:'Zero',value:0},{label:'Missing',value:null},{label:'Positive',value:10}],'test','yds'));
  assert.match(bars,/data-value="-2"/);assert.match(bars,/data-value="0"/);assert.match(bars,/data-value=""/);assert.match(bars,/Unavailable/);assert.doesNotMatch(bars,/NaN|Infinity/);
  report.missingAndNegative=true;report.pageErrors=errors;assert.deepEqual(errors,[]);report.passed=true;
 }catch(e){report.passed=false;report.error=e.message;report.pageErrors=errors;await page.screenshot({path:'defense-error.png'}).catch(()=>{});throw e;
 }finally{fs.writeFileSync('defense-verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
