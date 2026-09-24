'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1365,height:980},timezoneId:'America/New_York'});
  const base='https://kscot101.github.io/Gridiron-Pulse/';
  await context.route(base+'**',async route=>{
    const u=new URL(route.request().url());
    const rel=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
    const file=path.resolve(rel);
    if(!file.startsWith(process.cwd()+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return route.fulfill({status:404,body:'Not found'});
    return route.fulfill({path:file});
  });
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.message)});
  const report={testedAt:new Date().toISOString(),mode:'staged repository files; external services not mocked'};
  try{
    await page.goto(base+'projection-trial.html',{waitUntil:'domcontentloaded'});
    await page.locator('.gp-trial-card').first().waitFor({timeout:45000});
    const summary=await page.evaluate(()=>{
      const d=GPExactTracker.data;
      return {forecasts:d.forecasts.length,trial:d.forecasts.filter(r=>r.model==='workload-trial-1').length,baseline:d.forecasts.filter(r=>r.model==='v2.1-tracked-1').length,pairedComparisons:d.pairedComparisons.length,first:d.forecasts[0],noBackfill:d.forecasts.every(r=>Date.parse(r.recordedAt)<Date.parse(r.kickoff)-5*60000)};
    });
    assert.ok(summary.trial>0);assert.equal(summary.noBackfill,true);
    report.trialForecasts=summary.trial;report.baselineForecasts=summary.baseline;report.noBackfill=true;
    await page.selectOption('#gp-position','TE');
    const teText=await page.locator('.gp-trial-card').allTextContents();
    assert.ok(teText.length>0);assert.ok(teText.every(t=>t.includes('/ TE')));report.positionFilter=true;
    await page.selectOption('#gp-position','all');
    const firstButton=page.locator('[data-follow]').first();
    const recordId=await firstButton.getAttribute('data-follow');
    await firstButton.click();await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(id=>Array.from(document.querySelectorAll('[data-follow]')).some(b=>b.dataset.follow===id&&b.getAttribute('aria-pressed')==='true'),recordId,{timeout:45000});
    await page.check('#gp-favorites');assert.equal(await page.locator('.gp-trial-card').count(),1);report.followPersists=true;
    await page.uncheck('#gp-favorites');
    await page.fill('#gp-search','Mahomes');assert.ok((await page.locator('.gp-trial-card').textContent()).includes('Patrick Mahomes'));report.search=true;
    await page.fill('#gp-search','');
    await page.screenshot({path:'projection-trial-desktop.png'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'projection-trial-mobile.png'});
    report.trialMobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert.equal(report.trialMobileOverflow,false);
    await page.setViewportSize({width:1365,height:980});
    await page.goto(base,{waitUntil:'domcontentloaded'});
    await page.locator('#gp-trial-switch').waitFor({timeout:60000});
    await page.waitForFunction(()=>window.state&&state.snapshot&&state.snapshot.games.length>0,null,{timeout:60000});
    await page.check('#gp-trial-switch');
    await page.locator('#edge-grid [data-record-id]').first().waitFor({timeout:20000});
    report.canonicalValues=await page.evaluate(()=>{
      const nodes=Array.from(document.querySelectorAll('#edge-grid [data-record-id]'));
      return nodes.length>0&&nodes.every(n=>{
        const r=GPExactTracker.data.forecasts.find(r=>r.id===n.dataset.recordId);
        return r&&r.model==='workload-trial-1'&&Array.from(n.querySelectorAll('[data-metric]')).every(x=>Number(x.textContent.replace(/,/g,''))===r.predictions[x.dataset.metric]);
      });
    });
    assert.equal(report.canonicalValues,true);
    await page.screenshot({path:'projection-trial-home.png'});
    await page.uncheck('#gp-trial-switch');
    report.baselineView=await page.evaluate(()=>Array.from(document.querySelectorAll('#edge-grid [data-record-id]')).every(n=>n.dataset.recordId.endsWith('|v2.1-tracked-1')));
    assert.equal(report.baselineView,true);
    await page.setViewportSize({width:390,height:844});
    report.homeMobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert.equal(report.homeMobileOverflow,false);
    assert.ok(await page.locator('#gp-exact-legacy-note').count());
    report.pageErrors=errors;assert.deepEqual(errors,[]);report.passed=true;
    fs.writeFileSync('data/projection-trial-verification.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
  }catch(error){
    report.passed=false;report.error=error.message;report.pageErrors=errors;
    fs.writeFileSync('projection-trial-browser-error.json',JSON.stringify(report,null,2));
    await page.screenshot({path:'projection-trial-error.png'}).catch(()=>{});
    throw error;
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
