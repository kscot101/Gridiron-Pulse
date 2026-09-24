'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1365,height:900},timezoneId:'America/New_York'});
  const base='https://kscot101.github.io/Gridiron-Pulse/';
  // Serve staged repository files at the real site's origin. All external API
  // calls remain real network calls; no sports data or predictions are mocked.
  await context.route(base+'**',async route=>{
    const url=new URL(route.request().url());
    let rel=decodeURIComponent(url.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
    const local=path.resolve(rel);
    if(!local.startsWith(process.cwd()+path.sep)||!fs.existsSync(local)||!fs.statSync(local).isFile())return route.fulfill({status:404,body:'Not found'});
    return route.fulfill({path:local});
  });
  const page=await context.newPage(),errors=[],messages=[];
  page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.message);});
  page.on('console',m=>{if(m.type()==='error'){messages.push(m.text());console.log('BROWSER ERROR',m.text());}});
  page.on('requestfailed',r=>console.log('REQUEST FAILED',r.url().split('?')[0],r.failure()?.errorText));
  const report={testedAt:new Date().toISOString(),testMode:'staged files at production origin; live external data'};
  try{
    await page.goto(base+'?homepage-safety-test',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.state&&state.snapshot&&state.snapshot.feedStatus&&state.snapshot.games.length>0,null,{timeout:45000});
    Object.assign(report,await page.evaluate(()=>({
      season:state.snapshot.season,feedStatus:state.snapshot.feedStatus,
      gameCount:allGames().length,spotlight:spotlightGame()?.shortName,
      oldWeekOneGameInCurrentSlate:allGames().some(g=>g.id==='401872931'),
      expiredPregame:allGames().some(g=>g.status.state==='pre'&&Date.parse(g.date)<Date.now()-6*3600000),
      recentFinalGames:state.snapshot.recentGames.length,
      finalScoreRows:document.querySelectorAll('#results-list > .result-row').length,
      archiveVisible:!!document.querySelector('#results-list details'),
      archiveCollapsed:!document.querySelector('#results-list details')?.open,
      currentEdgeBoards:allBoards().length
    })));
    console.log('HOME REPORT',JSON.stringify(report));
    assert.equal(report.oldWeekOneGameInCurrentSlate,false);
    assert.equal(report.expiredPregame,false);
    assert.ok(report.gameCount>0);
    assert.equal(report.feedStatus.available,true);
    if(!report.feedStatus.analysisCurrent)assert.equal(report.currentEdgeBoards,0);
    await page.screenshot({path:'homepage-current-desktop.png'});
    await page.locator('#results').scrollIntoViewIfNeeded();
    await page.screenshot({path:'homepage-current-results.png'});
    await page.locator('#score-track [data-game]').first().click();
    await page.locator('#detail-overlay.open').waitFor();
    await page.keyboard.press('Escape');
    report.gameHubOpens=true;
    await page.setViewportSize({width:390,height:844});
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:'homepage-current-mobile.png'});
    report.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
    assert.equal(report.mobileOverflow,false);
    await page.goto(base+'projections-2026.html',{waitUntil:'domcontentloaded'});
    await page.locator('[data-proj-follow]').first().waitFor({timeout:60000});
    const b=page.locator('[data-proj-follow]').first(),key=await b.getAttribute('data-proj-follow');
    await b.click();
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(k=>Array.from(document.querySelectorAll('[data-proj-follow]')).some(b=>b.dataset.projFollow===k&&b.getAttribute('aria-pressed')==='true'),key,{timeout:60000});
    report.projectionFollowPersists=true;
    report.pageErrors=errors;
    assert.deepEqual(errors,[]);
    report.passed=true;
    fs.writeFileSync('data/homepage-safety-verification.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
  }catch(error){
    report.passed=false;report.error=error.message;report.pageErrors=errors;report.consoleErrors=messages;
    report.pageState=await page.evaluate(()=>({url:location.href,heading:document.getElementById('connection-label')?.textContent,status:document.getElementById('homepage-feed-status')?.textContent,snapshot:window.state?.snapshot,hasHelper:!!window.GPHomepageFeed})).catch(()=>null);
    fs.writeFileSync('homepage-browser-error.json',JSON.stringify(report,null,2));
    await page.screenshot({path:'homepage-current-error.png'}).catch(()=>{});
    console.log('DIAGNOSTIC',JSON.stringify(report));
    throw error;
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
