'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:960},timezoneId:'America/New_York',reducedMotion:'reduce'});
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 const snapshot=JSON.parse(fs.readFileSync('data/homepage-snapshot.json','utf8')).snapshot;
 const report={mode:'Controlled browser fixture: saved pick values with test-only healthy-feed metadata, plus an unavailable-feed case. Not live service verification. No production guards or data files modified.',testedAt:new Date().toISOString(),snapshotGeneratedAt:snapshot.generatedAt};
 await context.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(route.request().url().startsWith(base)){
   const local=path.resolve(decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html');
   return local.startsWith(process.cwd()+path.sep)&&fs.existsSync(local)&&fs.statSync(local).isFile()?route.fulfill({path:local}):route.fulfill({status:404,body:'Not found'});
  }
  if(u.hostname==='grid-pulse-agent.kadescott97.workers.dev'&&u.pathname==='/latest')return route.fulfill({path:'data/homepage-snapshot.json',contentType:'application/json'});
  return route.abort();
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.clock.setFixedTime(new Date(Date.parse(snapshot.generatedAt)+60000));
 try{
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.state&&state.snapshot&&window.GPExactTracker&&GPExactTracker.data&&window.GPPlayerStats,null,{timeout:30000});
  await page.evaluate(source=>{
   // Raw Worker data does not contain the client adapter's feedStatus. Supply
   // explicit fixture metadata, never mutate source files or the real adapter.
   state.snapshot=Object.assign({},source,{feedStatus:{available:true,analysisCurrent:true,mode:'current',gamesCheckedAt:source.generatedAt,analysisGeneratedAt:source.generatedAt}});
   renderAll();
  },snapshot);
  report.sectionOrder=await page.locator('main > section[id]').evaluateAll(ns=>ns.map(n=>n.id));
  assert.deepEqual(report.sectionOrder,['top','player-edge','my-pulse','season-outlook','availability','games','live','power-pulse','model-record','results']);
  assert.equal(await page.locator('#edge-grid').count(),1);assert.equal(await page.locator('#player-edge').count(),1);
  assert.equal((await page.locator('#daily-picks-heading').textContent()).trim(),'Picks of the Day');
  const total=await page.evaluate(()=>allBoards().reduce((n,b)=>n+(b.picks||[]).length,0));assert.ok(total>0);
  assert.equal(await page.locator('#edge-grid .edge-card').count(),Math.min(6,total));
  report.firstSixPicks=Math.min(6,total);report.sourcePicks=total;
  await page.screenshot({path:'home-picks-top-desktop.png'});
  await page.locator('#gp-picks-shortcut').click();
  await page.waitForFunction(()=>{const y=document.getElementById('player-edge').getBoundingClientRect().top;return y>=0&&y<150;});
  await page.waitForFunction(()=>document.querySelector('#home-section-links [data-home-section="player-edge"]').getAttribute('aria-current')==='location');
  report.headerShortcut=true;await page.screenshot({path:'home-picks-desktop.png'});
  if(total>6){await page.locator('[data-edge-expand="all"]').click();assert.equal(await page.locator('#edge-grid .edge-card').count(),total);await page.locator('[data-edge-expand="less"]').click();assert.equal(await page.locator('#edge-grid .edge-card').count(),6);report.showAllAndFewer=true;}
  await page.locator('[data-edge="qb"]').click();
  const qbs=await page.evaluate(()=>allBoards().flatMap(b=>b.picks||[]).filter(p=>p.spotlightRole==='QB IMPACT').length);
  assert.equal(await page.locator('#edge-grid .edge-card').count(),Math.min(qbs,6));await page.locator('[data-edge="all"]').click();report.positionFilter=true;
  const details=page.locator('#edge-grid .edge-details').first();
  if(await details.count()){await details.locator('summary').click();assert.notEqual(await details.getAttribute('open'),null);report.expandableSignals=true;}
  const exact=await page.locator('#edge-grid [data-record-id]').evaluateAll(ns=>ns.map(n=>{const r=GPExactTracker.data.forecasts.find(r=>r.id===n.dataset.recordId);return !!r&&Array.from(n.querySelectorAll('[data-metric]')).every(x=>Number(x.textContent.replace(/,/g,''))===r.predictions[x.dataset.metric]);}));
  assert.ok(exact.every(Boolean));report.exactForecastsVerified=exact.length;
  const name=page.locator('#edge-grid [data-profile-kind="player"]').first();const playerName=(await name.textContent()).trim();await name.click();await page.locator('#detail-overlay.open').waitFor();
  assert.equal(await page.locator('#detail-body .gp-recent-root').count(),1);assert.equal(await page.locator('#detail-body .gp-h2h-root').count(),1);report.playerProfilePreserved=true;await page.keyboard.press('Escape');
  await page.locator('#open-search').click();await page.locator('#search-input').fill(playerName);const result=page.locator('[data-search-open="player"]').first();await result.waitFor();
  report.searchColor=await result.locator('strong').evaluate(n=>getComputedStyle(n).color);assert.equal(report.searchColor,'rgb(7, 16, 13)');await page.keyboard.press('Escape');
  for(const id of ['my-pulse','games','player-edge','results','top']){await page.locator('#home-section-links [data-home-section="'+id+'"]').click();await page.waitForFunction(id=>document.querySelector('#home-section-links [data-home-section="'+id+'"]').getAttribute('aria-current')==='location',id);await page.waitForTimeout(100);}
  report.sidebarScrollHighlight=true;report.widths=[];
  for(const width of [1440,1280,1181,1180,1024,768,390,320]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>window.scrollTo(0,0));
   const size=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));report.widths.push(size);assert.ok(size.scrollWidth<=width+2,'Horizontal overflow '+JSON.stringify(size));
   assert.equal(await page.locator('#gp-picks-shortcut').isVisible(),true);
   if(width===390){
    await page.screenshot({path:'home-picks-mobile-header.png'});await page.locator('#gp-picks-shortcut').click();
    await page.waitForFunction(()=>{const y=document.getElementById('player-edge').getBoundingClientRect().top;return y>=0&&y<150;});await page.screenshot({path:'home-picks-mobile.png'});
    await page.locator('#home-sections-toggle').click();const order=await page.locator('#home-drawer-links [data-home-section]').evaluateAll(ns=>ns.map(n=>n.dataset.homeSection));assert.equal(order[1],'player-edge');
    await page.locator('#home-drawer-links [data-home-section="player-edge"]').click();assert.equal(await page.locator('#home-sections-toggle').getAttribute('aria-expanded'),'false');report.mobilePicksShortcutAndDrawer=true;
   }
  }
  await page.evaluate(()=>{state.snapshot=GPHomepageFeed.compose(null,[],null,null,Date.now());renderAll();});
  assert.equal(await page.locator('#edge-grid .edge-card').count(),0);
  assert.equal(await page.locator('#daily-picks-heading').count(),1);
  report.unavailableFeedWithholdsCards=true;
  assert.deepEqual(errors,[]);report.pageErrors=errors;report.passed=true;
 }catch(e){report.passed=false;report.error=e.message;report.pageErrors=errors;report.diagnostics=await page.evaluate(()=>({url:location.href,wide:Array.from(document.querySelectorAll('body *')).filter(n=>n.getBoundingClientRect().right>innerWidth+2&&n.getBoundingClientRect().width>0).slice(0,12).map(n=>({tag:n.tagName,cls:n.className,right:n.getBoundingClientRect().right}))})).catch(()=>null);await page.screenshot({path:'home-picks-error.png'}).catch(()=>{});throw e;
 }finally{fs.writeFileSync('home-picks-browser-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
