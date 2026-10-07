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
  const report={testedAt:new Date().toISOString(),version:'trial-verifier-20261007',mode:'Saved-data UI checks and live homepage diagnostics; isolated unavailable/stale fixtures tested separately'};
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
    const selected=await page.evaluate(id=>{
      const records=GPExactTracker.data.forecasts;
      const row=records.find(r=>r.id===id);
      if(!row)throw new Error('Follow button does not match a saved forecast');
      return {
        athleteId:String(row.athleteId),
        playerName:row.playerName,
        matchups:new Set(records.filter(r=>String(r.athleteId)===String(row.athleteId)).map(r=>r.gameId)).size
      };
    },recordId);
    await firstButton.click();await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(id=>Array.from(document.querySelectorAll('[data-follow]')).some(b=>b.dataset.follow===id&&b.getAttribute('aria-pressed')==='true'),recordId,{timeout:45000});
    // Favorites belong to a player, not to one game or one model record.
    await page.check('#gp-favorites');
    const favoriteCards=page.locator('.gp-trial-card');
    const favoriteIds=await favoriteCards.evaluateAll(nodes=>nodes.map(n=>n.dataset.athlete));
    assert.equal(favoriteIds.length,selected.matchups,'Favorites must show every saved matchup for this player');
    assert.ok(favoriteIds.length>0&&favoriteIds.every(id=>id===selected.athleteId),'Favorites included another player');
    const favoriteButtons=await favoriteCards.locator('[data-follow]').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.follow,pressed:n.getAttribute('aria-pressed')})));
    assert.equal(new Set(favoriteButtons.map(b=>b.id)).size,selected.matchups,'Duplicate favorite matchup cards');
    assert.ok(favoriteButtons.every(b=>b.pressed==='true'),'Follow state did not persist on every matchup');
    report.followPersists=true;report.favoriteCards=favoriteIds.length;
    await page.uncheck('#gp-favorites');
    // Search legitimately returns several games for the same player.
    await page.fill('#gp-search',selected.playerName);
    const searchCards=page.locator('.gp-trial-card');
    const searchTexts=await searchCards.allTextContents();
    assert.equal(searchTexts.length,selected.matchups,'Search omitted a saved matchup');
    assert.ok(searchTexts.length>0&&searchTexts.every(t=>t.includes(selected.playerName)));
    report.search=true;report.searchCards=searchTexts.length;
    await page.fill('#gp-search','');
    await page.screenshot({path:'projection-trial-desktop.png'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'projection-trial-mobile.png'});
    report.trialMobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert.equal(report.trialMobileOverflow,false);
    await page.setViewportSize({width:1365,height:980});
    await page.goto(base,{waitUntil:'domcontentloaded'});
    await page.locator('#gp-trial-switch').waitFor({timeout:60000});
    // A resolved, safely unavailable feed is a valid UI state. Do not wait
    // for a positive game count: that blocked grading historical forecasts.
    await page.waitForFunction(()=>window.state&&state.snapshot&&state.snapshot.feedStatus&&window.GPExactTracker&&GPExactTracker.data,null,{timeout:45000});
    report.homepage=await page.evaluate(()=>({
      feedStatus:state.snapshot.feedStatus,
      gameCount:state.snapshot.games.length,
      forecastCount:GPExactTracker.data.forecasts.length,
      statusText:document.getElementById('homepage-feed-status').textContent
    }));
    assert.equal(typeof report.homepage.feedStatus.available,'boolean');
    assert.equal(typeof report.homepage.feedStatus.analysisCurrent,'boolean');
    if(!report.homepage.feedStatus.available)assert.equal(report.homepage.gameCount,0);
    report.homepageModes=[];
    report.componentChecks=[];
    for(const [checked,model] of [[true,'workload-trial-1'],[false,'v2.1-tracked-1']]){
      await page.setChecked('#gp-trial-switch',checked);
      // Check the actual homepage against the independently selected saved
      // records. Zero is accepted only when no eligible record should display.
      const visible=await page.evaluate(model=>{
        const tm=v=>({WSH:'WAS',JAC:'JAX',LA:'LAR'}[v]||v);
        const all=allBoards().flatMap(b=>(b.picks||[]).map(p=>Object.assign({gameId:b.gameId},p)));
        const picks=state.edgeExpanded?all:all.slice(0,6);
        const expected=state.snapshot.feedStatus.analysisCurrent?picks.flatMap(p=>{
          const r=GPExactTracker.data.forecasts.find(r=>r.model===model&&String(r.athleteId)===String(p.athleteId||p.espnId||'')&&String(r.gameId)===String(p.gameId)&&tm(r.team)===tm(p.team));
          return r?[r.id]:[];
        }):[];
        const nodes=Array.from(document.querySelectorAll('#edge-grid [data-record-id]'));
        return {
          model,expected:expected.sort(),actual:nodes.map(n=>n.dataset.recordId).sort(),
          edgeCards:document.querySelectorAll('#edge-grid .edge-card').length,
          analysisCurrent:state.snapshot.feedStatus.analysisCurrent,
          values:nodes.every(n=>{
            const r=GPExactTracker.data.forecasts.find(r=>r.id===n.dataset.recordId);
            const metrics=Array.from(n.querySelectorAll('[data-metric]'));
            return r&&r.model===model&&metrics.length===Object.keys(r.predictions).length&&metrics.every(x=>{
              const v=r.predictions[x.dataset.metric];
              return x.textContent.trim()===(v==null?'\u2014':Number(v).toLocaleString(undefined,{maximumFractionDigits:2}));
            });
          })
        };
      },model);
      assert.deepEqual(visible.actual,visible.expected,'Visible saved forecast IDs do not match the current picks');
      assert.equal(visible.values,true,'Displayed forecast differs from the frozen record');
      if(!visible.analysisCurrent)assert.equal(visible.edgeCards,0,'Stale analysis must not show pick cards');
      report.homepageModes.push(visible);
      // Always exercise real card rendering and both model choices, including
      // on days when there are no current games. These detached DOM fixtures
      // use existing saved values; no forecast, date or production guard changes.
      const component=await page.evaluate(model=>{
        const records=GPExactTracker.data.forecasts.filter(r=>r.model===model);
        const samples=['QB','RB','WR','TE'].map(pos=>records.find(r=>r.position===pos)).filter(Boolean);
        return samples.map(r=>{
          const pick={name:r.playerName,athleteId:String(r.athleteId),gameId:String(r.gameId),team:r.team,position:r.position,signals:[]};
          const host=document.createElement('div');host.innerHTML=edgeMarkup(pick);
          const strip=host.querySelector('[data-record-id]');
          const metrics=strip?Array.from(strip.querySelectorAll('[data-metric]')):[];
          return {model,position:r.position,id:r.id,renderedId:strip&&strip.dataset.recordId,
            metricCount:metrics.length,expectedCount:Object.keys(r.predictions).length,
            values:metrics.every(x=>{const v=r.predictions[x.dataset.metric];return x.textContent.trim()===(v==null?'\u2014':Number(v).toLocaleString(undefined,{maximumFractionDigits:2}));})};
        });
      },model);
      assert.ok(component.length>0,'No saved records available to exercise '+model);
      for(const row of component){
        assert.equal(row.renderedId,row.id,'Model switch selected the wrong saved forecast');
        assert.ok(row.metricCount>0);assert.equal(row.metricCount,row.expectedCount);
        assert.equal(row.values,true,'Saved-record component values changed');
      }
      report.componentChecks.push(...component);
    }
    report.canonicalValues=true;report.baselineView=true;
    await page.screenshot({path:'projection-trial-home.png'});
    await page.setViewportSize({width:390,height:844});
    report.homeMobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert.equal(report.homeMobileOverflow,false);
    assert.ok(await page.locator('#gp-exact-legacy-note').count());
    // Explicit offline and stale-source regressions in separate browsers.
    // Requests use repository assets; only feed responses are test fixtures.
    report.safeFeedCases=[];
    for(const scenario of ['unavailable','stale']){
      const isolated=await browser.newContext({viewport:{width:390,height:844},timezoneId:'America/New_York'});
      const stale=JSON.parse(fs.readFileSync('data/homepage-snapshot.json','utf8'));
      stale.snapshot.generatedAt='2000-01-01T00:00:00.000Z';
      await isolated.route('**/*',async route=>{
        const u=new URL(route.request().url());
        if(!u.href.startsWith(base)){
          if(scenario==='stale'&&u.pathname==='/latest')return route.fulfill({json:stale});
          return route.fulfill({status:503,contentType:'application/json',body:'{"ok":false}'});
        }
        const rel=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
        if(rel==='data/homepage-snapshot.json')return scenario==='stale'?route.fulfill({json:stale}):route.fulfill({status:503,body:'Unavailable fixture'});
        if(rel==='data/homepage-scoreboard.json')return route.fulfill({status:503,body:'Unavailable fixture'});
        const file=path.resolve(rel);
        if(!file.startsWith(process.cwd()+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return route.fulfill({status:404,body:'Not found'});
        return route.fulfill({path:file});
      });
      const offline=await isolated.newPage();const offlineErrors=[];offline.on('pageerror',e=>offlineErrors.push(e.message));
      try{
        await offline.goto(base,{waitUntil:'domcontentloaded'});
        await offline.waitForFunction(()=>window.state&&state.snapshot&&state.snapshot.feedStatus&&window.GPExactTracker&&GPExactTracker.data,null,{timeout:20000});
        for(const checked of [true,false]){
          await offline.setChecked('#gp-trial-switch',checked);
          const safe=await offline.evaluate(()=>({
            available:state.snapshot.feedStatus.available,analysisCurrent:state.snapshot.feedStatus.analysisCurrent,
            games:state.snapshot.games.length,boards:allBoards().length,cards:document.querySelectorAll('#edge-grid .edge-card').length,
            exact:document.querySelectorAll('#edge-grid [data-record-id]').length,
            warning:document.getElementById('edge-grid').textContent,
            forecasts:GPExactTracker.data.forecasts.length
          }));
          assert.equal(safe.available,false);assert.equal(safe.analysisCurrent,false);
          assert.equal(safe.games,0);assert.equal(safe.boards,0);assert.equal(safe.cards,0);assert.equal(safe.exact,0);
          assert.match(safe.warning,/awaiting|unavailable/i);assert.equal(safe.forecasts,summary.forecasts,'Saved forecasts disappeared in offline mode');
          report.safeFeedCases.push({scenario,model:checked?'trial':'baseline',passed:true});
        }
        assert.deepEqual(offlineErrors,[]);
      }finally{await isolated.close();}
    }
    report.pageErrors=errors;assert.deepEqual(errors,[]);report.passed=true;
    fs.writeFileSync('data/projection-trial-verification.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
  }catch(error){
    report.passed=false;report.error=error.message;report.pageErrors=errors;
    report.homepageDiagnostic=await page.evaluate(()=>({url:location.href,feedStatus:window.state&&state.snapshot&&state.snapshot.feedStatus,status:document.getElementById('homepage-feed-status')?.textContent})).catch(()=>null);
    fs.writeFileSync('projection-trial-browser-error.json',JSON.stringify(report,null,2));
    await page.screenshot({path:'projection-trial-error.png'}).catch(()=>{});
    throw error;
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
