'use strict';
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1600,height:980},timezoneId:'America/New_York',reducedMotion:'reduce'});
 const base='https://kscot101.github.io/Gridiron-Pulse/';
 await context.route('**/*',async route=>{
   const url=route.request().url();
   if(url.startsWith(base)){
     const parsed=new URL(url);
     const rel=decodeURIComponent(parsed.pathname.slice('/Gridiron-Pulse/'.length))||'index.html';
     const local=path.resolve(rel);
     if(local.startsWith(process.cwd()+path.sep)&&fs.existsSync(local)&&fs.statSync(local).isFile())
       return route.fulfill({path:local});
     return route.fulfill({status:404,body:'Unavailable'});
   }
   return route.abort();
 });
 const page=await context.newPage();
 const errors=[],sizes=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
   await page.goto(base,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.GPPlayerStats && typeof GPPlayerStats.attach==='function',{timeout:30000});
   await page.evaluate(()=>{
     const body=document.getElementById('detail-body');
     body.innerHTML='<div style="padding:12px"><h2>Player profile width trial</h2></div><section class="modal-section"></section>';
     GPPlayerStats.attach({name:'Patrick Mahomes',team:'KC',position:'QB',id:'00-0033873',espnId:'3139477'},body);
     openOverlay('detail-overlay');
   });
   await page.locator('#detail-overlay.open .gp-h2h-root').waitFor();
   for(const width of [1600,1366,1024,390,320]){
     await page.setViewportSize({width,height:940});
     const size=await page.evaluate(()=>{
       const overlay=document.getElementById('detail-overlay');
       const modal=overlay.querySelector('.modal');
       const graph=overlay.querySelector('.gc-matchup-layout');
       const rect=modal.getBoundingClientRect();
       const st=getComputedStyle(modal),os=getComputedStyle(overlay);
       return {viewport:innerWidth,width:Math.round(rect.width),modalCSS:st.width,modalFlex:st.flex,modalMax:st.maxWidth,overlayCSS:os.display,selectorMatch:overlay.matches('#detail-overlay.open:has(.gp-h2h-root)'),cssLoaded:[...document.styleSheets].some(x=>x.href&&x.href.includes('player-comparison-v2.css')),modalOverflow:modal.scrollWidth>modal.clientWidth+3,
         pageOverflow:document.documentElement.scrollWidth>innerWidth+3,hasAnalysis:!!overlay.querySelector('.gp-h2h-root'),
         chartColumns:graph?getComputedStyle(graph).gridTemplateColumns:'pending'};
     });
     sizes.push(size);
     assert.ok(size.hasAnalysis,'Player analysis not present');
     assert.ok(size.width>width*0.91,'Skinny profile at '+width+': '+JSON.stringify(size));
     assert.equal(size.pageOverflow,false,'Horizontal page overflow at '+width);
     assert.equal(size.modalOverflow,false,'Horizontal player popup overflow at '+width);
     if(width===1600)await page.screenshot({path:'player-width-desktop.png'});
     if(width===390)await page.screenshot({path:'player-width-mobile.png'});
   }
   assert.deepEqual(errors.filter(x=>/SyntaxError|ReferenceError|TypeError/.test(x)),[]);
   const report={passed:true,sizes,errors};fs.writeFileSync('player-width-verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }catch(e){
   fs.writeFileSync('player-width-verification.json',JSON.stringify({passed:false,sizes,error:String(e),errors},null,2));
   throw e;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
