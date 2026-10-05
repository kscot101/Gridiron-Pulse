'use strict';
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async()=>{
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1365,height:900},timezoneId:'America/New_York'});
  const base='https://kscot101.github.io/Gridiron-Pulse/';
  await context.route(base+'**',async route=>{
    const url=new URL(route.request().url());
    let rel=decodeURIComponent(url.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
    const local=path.resolve(rel);
    if(!local.startsWith(process.cwd()+path.sep)||!fs.existsSync(local)||!fs.statSync(local).isFile())
      return route.fulfill({status:404,body:'Not found'});
    return route.fulfill({path:local});
  });
  const page=await context.newPage(),errors=[],consoleErrors=[],failed=[];
  page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.message);});
  page.on('console',m=>{if(m.type()==='error'){consoleErrors.push(m.text());console.log('CONSOLE ERROR',m.text());}});
  page.on('requestfailed',r=>{failed.push({url:r.url(),error:r.failure()?.errorText});});
  await page.goto(base+'?h2h-component-verification=1',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.GPPlayerStats&&typeof GPPlayerStats.attach==='function'&&typeof GPPlayerStats.link==='function',null,{timeout:30000});

  const player={name:'Patrick Mahomes',team:'KC',position:'QB'};

  // Search/profile path: the homepage profile function is what player search calls.
  const profileWire=await page.evaluate(()=>({
    hasOpenProfile:typeof window.openProfile==='function',
    source:typeof window.openProfile==='function'?String(window.openProfile):''
  }));
  assert.equal(profileWire.hasOpenProfile,true);
  assert.match(profileWire.source,/GPPlayerStats\.attach/);

  // Attach exactly as the homepage search/profile path does, without requiring
  // freshness-gated Player Edge or projection feeds.
  await page.evaluate((p)=>{
    const host=document.createElement('div');
    host.id='gp-h2h-test-host';
    host.innerHTML='<section class="modal-section"><h3>Profile content</h3></section>';
    document.body.appendChild(host);
    GPPlayerStats.attach(p,host);
  },player);
  const searchH2H=page.locator('#gp-h2h-test-host .gp-h2h-root:not([hidden])');
  await searchH2H.waitFor({timeout:45000});
  await page.waitForFunction(()=>{
    const el=document.querySelector('#gp-h2h-test-host .gp-h2h-root:not([hidden])');
    return el&&el.getAttribute('aria-busy')!=='true';
  },null,{timeout:45000});
  const searchText=(await searchH2H.innerText()).replace(/\s+/g,' ').trim();
  assert.match(searchText,/MATCHUP HISTORY \/ HEAD TO HEAD/i);
  assert.match(searchText,/vs\s+/i);
  assert.doesNotMatch(searchText,/temporarily unavailable/i);
  assert.equal(await page.locator('#gp-h2h-test-host .gp-h2h-root').count(),1,'Duplicate H2H sections rendered');
  assert.equal(await page.locator('#gp-h2h-test-host .gp-recent-root').count(),1,'Duplicate recent-game sections rendered');
  const recentKeys=await page.locator('#gp-h2h-test-host .gp-recent-root tbody tr').evaluateAll(rows=>rows.map(r=>Array.from(r.cells).slice(0,2).map(c=>c.innerText.replace(/\s+/g,' ').trim()).join('|')));
  assert.equal(new Set(recentKeys).size,recentKeys.length,'Duplicate recent-game rows rendered');

  // Direct clickable-name path: use the real GPPlayerStats link and click handler.
  await page.evaluate((p)=>{
    const holder=document.createElement('div');
    holder.id='gp-h2h-direct-link';
    holder.innerHTML=GPPlayerStats.link(p,p.name);
    document.body.appendChild(holder);
  },player);
  await page.locator('#gp-h2h-direct-link [data-gp-player]').click();
  const directH2H=page.locator('dialog.gp-player-dialog .gp-h2h-root:not([hidden]), #detail-body .gp-h2h-root:not([hidden])').last();
  await directH2H.waitFor({timeout:45000});
  await page.waitForFunction(()=>{
    const els=[...document.querySelectorAll('dialog.gp-player-dialog .gp-h2h-root:not([hidden]), #detail-body .gp-h2h-root:not([hidden])')];
    return els.some(el=>el.getAttribute('aria-busy')!=='true'&&/MATCHUP HISTORY \/ HEAD TO HEAD/i.test(el.textContent));
  },null,{timeout:45000});
  const directText=(await directH2H.innerText()).replace(/\s+/g,' ').trim();
  assert.match(directText,/MATCHUP HISTORY \/ HEAD TO HEAD/i);
  assert.match(directText,/vs\s+/i);
  assert.doesNotMatch(directText,/temporarily unavailable/i);
  const visibleProfileCounts=await page.evaluate(()=>({
    detail:document.querySelectorAll('#detail-body .gp-h2h-root:not([hidden])').length,
    dialogs:Array.from(document.querySelectorAll('dialog.gp-player-dialog')).filter(d=>d.open).length
  }));
  assert.ok(visibleProfileCounts.detail + visibleProfileCounts.dialogs <= 1,'More than one player profile presentation is visible');
  const directRows=await directH2H.locator('tbody tr').evaluateAll(rows=>rows.map(r=>Array.from(r.cells).slice(0,2).map(c=>c.innerText.replace(/\s+/g,' ').trim()).join('|')));
  assert.equal(new Set(directRows).size,directRows.length,'Duplicate H2H game rows rendered');

  await page.setViewportSize({width:390,height:844});
  await directH2H.scrollIntoViewIfNeeded();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
  assert.equal(overflow,false);

  const fatalErrors=errors.filter(x=>/SyntaxError|ReferenceError|TypeError/i.test(x));
  assert.deepEqual(fatalErrors,[]);
  const report={
    testedAt:new Date().toISOString(),
    player:player,
    searchProfileWiredToSharedPlayerStats:true,
    searchH2H:searchText.slice(0,500),
    directNameH2H:directText.slice(0,500),
    recentGames:true,
    duplicateSections:false,
    duplicateRecentRows:false,
    duplicateH2HRows:false,
    mobileOverflow:overflow,
    pageErrors:errors,
    consoleErrors:consoleErrors,
    failedRelevantRequests:failed.filter(x=>/player-recent|espn|homepage-scoreboard/i.test(x.url)).slice(0,20),
    passed:true
  };
  fs.writeFileSync('data/player-h2h-verification.json',JSON.stringify(report,null,2));
  await page.screenshot({path:'player-h2h-mobile.png',fullPage:false});
  console.log(JSON.stringify(report,null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
