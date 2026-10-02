'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'America/New_York',reducedMotion:'reduce'});
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 const snapshot=JSON.parse(fs.readFileSync('data/homepage-snapshot.json','utf8'));
 const report={mode:'Deterministic browser layout test using unchanged saved repository data; external services blocked',sourceGeneratedAt:snapshot.snapshot.generatedAt,testedAt:new Date().toISOString()};
 await context.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(route.request().url().startsWith(base)){
   const rel=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html',local=path.resolve(rel);
   if(local.startsWith(process.cwd()+path.sep)&&fs.existsSync(local)&&fs.statSync(local).isFile())return route.fulfill({path:local});
   return route.fulfill({status:404,body:'Not found'});
  }
  if(u.hostname==='grid-pulse-agent.kadescott97.workers.dev'&&u.pathname==='/latest')return route.fulfill({path:'data/homepage-snapshot.json',contentType:'application/json'});
  return route.abort();
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.clock.setFixedTime(new Date(Date.parse(snapshot.snapshot.generatedAt)+60000));
 try{
  await page.goto(base+'pick-tracker.html',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.GPPickTracker&&GPPickTracker.data&&GPPickTracker.groups.length>0);
  const total=await page.evaluate(()=>GPPickTracker.groups.length);
  assert.equal(await page.locator('.pt-pick').count(),Math.min(total,12));
  assert.equal(Number(await page.locator('#pt-total').innerText()),total);
  report.savedPlayerGamePicks=total;report.initialVisiblePicks=await page.locator('.pt-pick').count();
  if(total>12){await page.locator('#pt-load-more').click();assert.equal(await page.locator('.pt-pick').count(),Math.min(total,24));}
  for(const [p,title] of [['QB','Quarterbacks'],['RB','Running Backs'],['WR','Wide Receivers'],['TE','Tight Ends'],['all','All Picks']]){
   await page.locator('[data-pt-position="'+p+'"]').click();assert.equal(await page.locator('#pt-page-title').innerText(),title);
   if(p!=='all')assert.equal(await page.locator('.pt-pick:not([data-position="'+p+'"])').count(),0);
  }
  report.positionSwitching=true;
  assert.equal(await page.locator('#pt-trend-chart').count(),1);assert.equal(await page.locator('#pt-comparison-chart').count(),1);
  report.chartState=await page.locator('#pt-trend-chart').getAttribute('aria-label');
  await page.screenshot({path:'sites-v8-tracker-desktop.png'});
  await page.locator('#pt-search').fill('Mahomes');
  const card=page.locator('.pt-pick').first();assert.ok(await card.count());
  await card.locator('[data-pt-detail]').click();assert.notEqual(await card.locator('details').getAttribute('open'),null);
  report.savedValuesMatch=await card.evaluate(node=>{
   const [season,game,athlete]=node.dataset.pickKey.split('|');
   const rows=GPPickTracker.data.forecasts.filter(r=>String(r.season)===season&&String(r.gameId)===game&&String(r.athleteId)===athlete);
   return rows.length>0&&rows.every(r=>Object.entries(r.predictions).every(([k,v])=>{
    if(v===null||v===undefined)return true;
    const cell=node.querySelector('[data-stat="'+k+'"] [data-model="'+r.model+'"]');
    return cell&&Math.abs(Number(cell.textContent.replace(/,/g,''))-Number(v))<0.006;
   }));
  });assert.equal(report.savedValuesMatch,true);
  await card.locator('[data-pt-follow]').click();await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>GPPickTracker.data&&GPPickTracker.groups.length>0);
  await page.locator('#pt-favorites').check();assert.ok(await page.locator('.pt-pick').count());
  assert.ok((await page.locator('.pt-player h3').allTextContents()).every(x=>x.includes('Mahomes')));report.followPersists=true;
  await page.locator('.pt-pick .gp-player-name').first().click();
  await page.locator('dialog[open] .gp-h2h-root').waitFor({state:'visible',timeout:20000});
  report.playerProfileH2HComponent=true;await page.keyboard.press('Escape');await page.locator('.pt-reset').click();
  report.trackerWidths=[];
  for(const width of [1440,1200,1024,980,768,390,320]){
   await page.setViewportSize({width,height:900});
   const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));report.trackerWidths.push(size);
   assert.ok(size.scroll<=width+2,'Tracker overflow '+JSON.stringify(size));
   if(width===390)await page.screenshot({path:'sites-v8-tracker-mobile.png'});
  }
  await page.setViewportSize({width:1440,height:1000});await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.state&&state.snapshot&&state.snapshot.games.length>0);
  assert.equal(await page.locator('#home-section-links .home-section-link').count(),10);
  assert.equal(await page.locator('.home-section-rail').isVisible(),true);
  await page.screenshot({path:'sites-v8-home-desktop.png'});
  for(const id of ['games','player-edge','results','top']){
   await page.locator('#home-section-links [data-home-section="'+id+'"]').click();
   await page.waitForFunction(id=>document.querySelector('#home-section-links [data-home-section="'+id+'"]').getAttribute('aria-current')==='location',id);
   await page.waitForTimeout(400);
  }
  report.homeSectionNavigation=true;
  await page.locator('#open-search').click();await page.locator('#search-input').fill('Mahomes');
  await page.locator('[data-search-open="player"]').first().click();
  await page.locator('#detail-body .gp-h2h-root').waitFor({state:'visible'});
  await page.locator('#detail-body .gp-recent-root .gp-log-table').waitFor({state:'visible',timeout:20000});
  report.homeSearchRecentGames=true;await page.keyboard.press('Escape');
  report.homeWidths=[];
  for(const width of [1440,1200,1181,1180,1024,768,390,320]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>window.scrollTo(0,0));
   const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));report.homeWidths.push(size);
   assert.ok(size.scroll<=width+2,'Homepage overflow '+JSON.stringify(size));
   if(width===390){
    await page.screenshot({path:'sites-v8-home-mobile.png'});
    await page.locator('#home-sections-toggle').click();assert.equal(await page.locator('#home-sections-drawer').getAttribute('aria-hidden'),'false');
    await page.screenshot({path:'sites-v8-mobile-menu.png'});
    await page.locator('#home-drawer-links [data-home-section="results"]').click();assert.equal(await page.locator('#home-sections-toggle').getAttribute('aria-expanded'),'false');
   }
  }
  report.mobileDrawer=true;report.pageErrors=errors;assert.deepEqual(errors,[]);report.passed=true;
  fs.writeFileSync('sites-v8-browser-verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }catch(e){
  report.passed=false;report.error=e.message;report.pageErrors=errors;
  report.diagnostics=await page.evaluate(()=>({url:location.href,wide:Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth+2&&e.getBoundingClientRect().width>0).slice(0,10).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right}))})).catch(()=>null);
  fs.writeFileSync('sites-v8-browser-verification.json',JSON.stringify(report,null,2));await page.screenshot({path:'sites-v8-error.png'}).catch(()=>{});console.log(JSON.stringify(report,null,2));throw e;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
