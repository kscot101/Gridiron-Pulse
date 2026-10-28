'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {select}=require('../assets/saved-picks.js');
const H=3600000,N=Date.parse('2026-10-28T20:00:00Z');
const fixture={trialOnly:true,forecasts:[{id:'123|456|v2.1-tracked-1',gameId:'123',athleteId:'456',team:'CAR',opponent:'GB',position:'QB',playerName:'Test Player',model:'v2.1-tracked-1',season:2026,week:8,kickoff:new Date(N+28*H).toISOString(),recordedAt:new Date(N-4*H).toISOString(),sourceGeneratedAt:new Date(N-4.1*H).toISOString(),forecastHash:'a'.repeat(64),predictions:{passing_yards:210.5,passing_tds:1.2}}]};
const mirror={ok:true,fetchedAt:new Date(N-4*H).toISOString(),scoreboard:{season:{year:2026,type:2},week:{number:8},events:[{id:'123',date:fixture.forecasts[0].kickoff,name:'CAR at GB',shortName:'CAR @ GB',status:{type:{state:'pre',completed:false,name:'STATUS_SCHEDULED'}},competitions:[{competitors:[{team:{abbreviation:'CAR'}},{team:{abbreviation:'GB'}}]}]}]}};
const clone=x=>JSON.parse(JSON.stringify(x));
let tests=0;
function expect(data,board,time,count){assert.equal(select(data,board,time,'v2.1-tracked-1').length,count);tests++;}
expect(fixture,mirror,N,1);
expect(fixture,mirror,N+28*H,0);
expect(fixture,mirror,N+74*H,0);
for(const [field,value] of [['gameId','999'],['opponent','DAL'],['week',7],['season',2025],['recordedAt',new Date(N+29*H).toISOString()],['forecastHash',''],['predictions',{passing_yards:null}]]){let d=clone(fixture);d.forecasts[0][field]=value;expect(d,mirror,N,0);}
for(const state of ['post','in']){let m=clone(mirror);m.scoreboard.events[0].status.type.state=state;expect(fixture,m,N,0);}
{let m=clone(mirror);m.scoreboard.events[0].status.type.name='STATUS_POSTPONED';expect(fixture,m,N,0);}
{let m=clone(mirror);m.scoreboard.events[0].date='invalid';expect(fixture,m,N,0);}
{let d=clone(fixture);d.forecasts.push(clone(d.forecasts[0]));expect(d,mirror,N,1);}
{let d=clone(fixture);d.forecasts[0].model='workload-trial-1';d.forecasts[0].id='123|456|workload-trial-1';let r=select(d,mirror,N,'v2.1-tracked-1');assert.equal(r[0].modelFallback,true);tests++;}
{let d=clone(fixture);d.outcomes={[d.forecasts[0].id]:{status:'INVALID_CAPTURE'}};expect(d,mirror,N,0);}
console.log('Saved-pick guard tests passed:',tests);
(async()=>{
  const {chromium}=require('playwright');
  const browser=await chromium.launch({headless:true});
  const base='https://kscot101.github.io/Gridiron-Pulse/';
  const report={testedAt:new Date().toISOString(),guardTests:tests,mode:'First-visit saved picks with all external services blocked; separate labeled synthetic time-boundary fixture'};
  const canonical=JSON.parse(fs.readFileSync('data/projection-trial.json','utf8'));
  const scoreboard=JSON.parse(fs.readFileSync('data/homepage-scoreboard.json','utf8'));
  async function check(useFixture){
    const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'America/New_York'});
    if(useFixture)await context.addInitScript(t=>{const Real=Date;window.Date=class extends Real{constructor(...v){super(...(v.length?v:[t]));}static now(){return t;}};},N);
    await context.route('**/*',async route=>{
      const u=new URL(route.request().url());
      if(!u.href.startsWith(base))return route.abort();
      const rel=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
      if(rel==='data/homepage-snapshot.json')return route.fulfill({status:503,body:'Analysis unavailable test'});
      if(useFixture&&rel==='data/projection-trial.json')return route.fulfill({json:{...canonical,...fixture}});
      if(useFixture&&rel==='data/homepage-scoreboard.json')return route.fulfill({json:mirror});
      const file=path.resolve(rel);
      if(!file.startsWith(process.cwd()+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return route.fulfill({status:404,body:'Not found'});
      return route.fulfill({path:file});
    });
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    const start=Date.now();await page.goto(base,{waitUntil:'domcontentloaded'});
    const data=useFixture?fixture:canonical,board=useFixture?mirror:scoreboard;
    const expected=select(data,board,useFixture?N:Date.now(),'v2.1-tracked-1');
    if(expected.length){
      await page.locator('#gp-saved-spotlight:not([hidden]) [data-saved-record]').first().waitFor({timeout:15000});
      const values=await page.locator('#gp-saved-spotlight [data-saved-record]').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.savedRecord,stats:[...n.querySelectorAll('[data-saved-metric]')].map(m=>({key:m.dataset.savedMetric,text:m.textContent}))})));
      for(const node of values){const r=data.forecasts.find(r=>r.id===node.id);assert.ok(r);assert.equal(node.stats.length,Object.keys(r.predictions).length);for(const m of node.stats)assert.equal(m.text,r.predictions[m.key].toLocaleString('en-US',{maximumFractionDigits:2}));}
      assert.equal(new Set(values.map(x=>x.id)).size,values.length);
      assert.equal(await page.locator('#spotlight-game').isVisible(),false);
      assert.ok(await page.locator('#gp-saved-picks [data-saved-record]').count()>0);

      if(!useFixture){
        await page.locator('[data-edge="qb"]').click();
        await page.waitForFunction(()=>{const cards=[...document.querySelectorAll('#gp-saved-picks [data-saved-record]')];return cards.length>0&&cards.every(c=>c.querySelector('small').textContent.includes('/ QB'));});
        await page.locator('[data-edge="favorites"]').click();
        await page.waitForFunction(()=>document.getElementById('gp-saved-picks').textContent.includes('No saved picks match this filter'));
        await page.locator('[data-edge="all"]').click();
        await page.waitForFunction(()=>document.querySelectorAll('#gp-saved-picks [data-saved-record]').length>0);
        report.positionFilter=true;report.favoriteEmptyState=true;
      }

      if(!useFixture){report.upcomingPlayerMatchups=expected.length;report.spotlightPlayers=values.map(n=>data.forecasts.find(r=>r.id===n.id).playerName);report.firstVisitorLoadMs=Date.now()-start;await page.screenshot({path:'durable-picks-mobile.png'});}
      for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false,'Horizontal overflow at '+width);}
      if(!useFixture)await page.screenshot({path:'durable-picks-desktop.png'});
      if(useFixture){await page.evaluate(t=>{Date.now=()=>t;GPSavedPicks.paint();},N+28*H);assert.equal(await page.locator('#gp-saved-spotlight').isVisible(),false);}
    }else{
      await page.locator('#gp-saved-empty').waitFor({timeout:15000});
      report.upcomingPlayerMatchups=0;
    }
    assert.deepEqual(errors,[]);await context.close();
  }
  try{await check(false);await check(true);report.syntheticOutageAndKickoff=true;report.pageErrors=[];report.passed=true;fs.writeFileSync('durable-picks-verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
