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
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'?h2h-verification=1',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.state&&state.snapshot&&typeof allBoards==='function'&&allBoards().length>0,null,{timeout:60000});
  const chosen=await page.evaluate(()=>{
    const allowed=new Set(['QB','RB','WR','TE']);
    for(const board of allBoards()){
      for(const pick of (board.picks||[])){
        const p=String(pick.position||pick.positionGroup||'').toUpperCase();
        if(allowed.has(p)&&pick.name) return {name:pick.name,team:pick.team,position:p};
      }
    }
    return null;
  });
  assert.ok(chosen,'No offensive Player Edge player available for H2H verification');

  // Search path: open player from global search and confirm matchup history renders.
  await page.locator('#open-search').click();
  await page.locator('#search-input').fill(chosen.name);
  const searchResult=page.locator('[data-search-open="player"]').filter({hasText:chosen.name}).first();
  await searchResult.waitFor({timeout:15000});
  await searchResult.click();
  const h2h=page.locator('#detail-body .gp-h2h-root:not([hidden])').first();
  await h2h.waitFor({timeout:45000});
  await page.waitForFunction(()=> {
    const el=document.querySelector('#detail-body .gp-h2h-root:not([hidden])');
    return el && !el.getAttribute('aria-busy');
  },null,{timeout:45000});
  const searchText=(await h2h.innerText()).replace(/\s+/g,' ').trim();
  assert.match(searchText,/MATCHUP HISTORY \/ HEAD TO HEAD/i);
  assert.match(searchText,/vs\s+/i);
  assert.doesNotMatch(searchText,/temporarily unavailable/i);
  assert.ok(await page.locator('#detail-body .gp-recent-root').count(),'Recent games disappeared from player profile');
  await page.locator('#detail-overlay [data-close]').first().click();

  // Direct-name path: use the same clickable player-name system.
  const direct=page.locator('button.gp-player-name').filter({hasText:chosen.name}).first();
  await direct.waitFor({timeout:15000});
  await direct.click();
  const directH2H=page.locator('.gp-h2h-root:not([hidden])').first();
  await directH2H.waitFor({timeout:45000});
  await page.waitForFunction(()=> {
    const els=[...document.querySelectorAll('.gp-h2h-root:not([hidden])')];
    return els.some(el=>!el.getAttribute('aria-busy') && /MATCHUP HISTORY \/ HEAD TO HEAD/i.test(el.textContent));
  },null,{timeout:45000});
  const directText=(await directH2H.innerText()).replace(/\s+/g,' ').trim();
  assert.match(directText,/MATCHUP HISTORY \/ HEAD TO HEAD/i);
  assert.doesNotMatch(directText,/temporarily unavailable/i);

  // Mobile should retain the H2H section without horizontal page overflow.
  await page.setViewportSize({width:390,height:844});
  await directH2H.scrollIntoViewIfNeeded();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
  assert.equal(overflow,false);

  const report={
    testedAt:new Date().toISOString(),
    player:chosen,
    searchH2H:searchText.slice(0,400),
    directH2H:directText.slice(0,400),
    recentGames:true,
    mobileOverflow:overflow,
    pageErrors:errors,
    passed:errors.length===0
  };
  assert.deepEqual(errors,[]);
  fs.writeFileSync('data/player-h2h-verification.json',JSON.stringify(report,null,2));
  await page.screenshot({path:'player-h2h-mobile.png',fullPage:false});
  console.log(JSON.stringify(report,null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
