'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 const context=await browser.newContext({viewport:{width:1440,height:950},timezoneId:'America/New_York',reducedMotion:'reduce'});
 await context.route('**/*',r=>{
   const u=new URL(r.request().url());
   if(r.request().url().startsWith(base)){
     const relative=decodeURIComponent(u.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
     const file=path.resolve(relative);
     if(file.startsWith(process.cwd()+path.sep)&&fs.existsSync(file)&&fs.statSync(file).isFile())return r.fulfill({path:file});
     return r.fulfill({status:404,body:'Not found'});
   }
   return r.abort();
 });
 const page=await context.newPage(), errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
   await page.goto(base,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.GPPlayerStats&&window.GPMatchupComparisons);
   const dataset=JSON.parse(fs.readFileSync('data/defense-players.json','utf8'));
   const player=Object.values(dataset.players).find(p=>p.name==='Patrick Mahomes');
   assert.ok(player,'Test player missing');
   await page.evaluate(p=>GPPlayerStats.open({name:p.name,id:p.id,team:p.team,position:p.position}),player);
   await page.locator('#detail-overlay.open .gp-h2h-root .gc-unified-graph').waitFor({timeout:30000});
   const compact=page.locator('link[href*="player-profile-compact.css"]');
   assert.equal(await compact.count(),1,'Compact profile sheet must be loaded');
   const sizing=()=>page.evaluate(()=>{
     const root=document.querySelector('#detail-overlay.open');
     const info=root.querySelector('#detail-body > div:first-child');
     const title=info.querySelector('.modal-title');
     const matchup=root.querySelector('.gp-h2h-head');
     const intro=root.querySelector('.gc-player-intro');
     const rect=root.querySelector('.modal').getBoundingClientRect();
     return {
       playerHeaderHeight:Math.round(info.getBoundingClientRect().height),
       playerNameFont:Math.round(parseFloat(getComputedStyle(title).fontSize)),
       matchupHeight:Math.round(matchup.getBoundingClientRect().height),
       introHeight:Math.round(intro.getBoundingClientRect().height),
       popupWidth:Math.round(rect.width),
       plotCount:root.querySelectorAll('.gc-unified-graph').length,
       seriesCount:root.querySelectorAll('.gc-unified-graph .gc-triple-week').length,
       horizontalOverflow:document.documentElement.scrollWidth>innerWidth+3
     };
   });
   await compact.evaluate(el=>el.disabled=true);
   const before=await sizing();
   await compact.evaluate(el=>el.disabled=false);
   const after=await sizing();
   assert.ok(after.playerHeaderHeight<=before.playerHeaderHeight*0.70,
      'Player name/info header was not reduced enough: '+JSON.stringify({before,after}));
   assert.ok(after.introHeight<before.introHeight,'Matchup description should be tighter');
   assert.equal(after.plotCount,1,'One large graph must remain');
   assert.ok(after.popupWidth>=1440*0.91,'Do not narrow the wide player popup');
   await page.screenshot({path:'compact-player-desktop.png'});
   for(const width of [1024,390,320]){
     await page.setViewportSize({width,height:850});
     const dims=await sizing();checks.push({width,...dims});
     assert.ok(!dims.horizontalOverflow,'Page overflows at '+width);
     assert.equal(dims.plotCount,1,'Graph disappeared at '+width);
     assert.ok(dims.popupWidth>=width*0.90,'Popup became too narrow at '+width);
     if(width===390)await page.screenshot({path:'compact-player-mobile.png'});
   }
   assert.ok(!errors.some(e=>/SyntaxError|ReferenceError|TypeError/.test(e)),errors.join('; '));
   const report={passed:true,before,after,ratio:Number((after.playerHeaderHeight/before.playerHeaderHeight).toFixed(3)),checks,errors};
   fs.writeFileSync('compact-player-verification.json',JSON.stringify(report,null,2));
   console.log(JSON.stringify(report,null,2));
 }catch(error){
   fs.writeFileSync('compact-player-verification.json',JSON.stringify({passed:false,error:String(error),checks,errors},null,2));
   throw error;
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
