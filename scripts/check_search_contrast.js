'use strict';
// Production search markup and stylesheet order, with an isolated text fixture.
// This test makes no external requests and does not change football data.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const html=fs.readFileSync('index.html','utf8');
  const css=[];
  for(const m of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>|<link\b[^>]*rel=["']stylesheet["'][^>]*>/gi)){
    if(m[1]!==undefined){css.push(m[1]);continue;}
    const href=m[0].match(/href=["']([^"']+)["']/i)?.[1];
    if(!href||!href.startsWith('./assets/'))continue;
    const local=path.resolve(href.split('?')[0]);
    assert.ok(local.startsWith(process.cwd()+path.sep));
    css.push(fs.readFileSync(local,'utf8'));
  }
  const start=html.indexOf('<div class="overlay" id="search-overlay"');
  const end=html.indexOf('<div class="toast"',start);
  assert.ok(start>=0&&end>start,'Production search markup not found');
  const browser=await chromium.launch({headless:true});
  const report={testedAt:new Date().toISOString(),mode:'Production search markup and CSS with an isolated text fixture; no external services',checks:[],passed:false};
  try{
    const page=await browser.newPage({viewport:{width:1365,height:900}});
    await page.route('**/*',route=>route.abort());
    await page.setContent('<!doctype html><html><head><style>'+css.join('\n')+'</style></head><body>'+html.slice(start,end)+'</body></html>');
    await page.evaluate(()=>{
      document.getElementById('search-overlay').classList.add('open');
      document.getElementById('search-results').innerHTML='<button type="button" class="search-result" data-search-open="player"><span class="avatar">P</span><span><strong>Player visibility fixture</strong><small style="display:block;margin-top:5px">TEAM / QB</small></span><span>Open</span></button>';
    });
    const row=page.locator('.search-result');
    for(const width of [1365,390]){
      await page.setViewportSize({width,height:width===390?844:900});
      for(const state of ['normal','hover','focus']){
        if(state==='hover')await row.hover();
        if(state==='focus')await row.focus();
        const details=await row.evaluate(e=>{
          const n=getComputedStyle(e.querySelector('strong'));
          const b=getComputedStyle(e);
          return {color:n.color,textFill:n.webkitTextFillColor,opacity:n.opacity,cardOpacity:b.opacity,background:b.backgroundColor};
        });
        assert.equal(details.color,'rgb(0, 0, 0)','Search name must be black');
        assert.equal(details.textFill,'rgb(0, 0, 0)','Text fill must remain opaque black');
        assert.equal(details.opacity,'1');assert.equal(details.cardOpacity,'1');
        report.checks.push({width,state,...details});
      }
      const filters=await page.locator('[data-search-type]').evaluateAll(buttons=>buttons.map(e=>({label:e.textContent.trim(),color:getComputedStyle(e).color,fill:getComputedStyle(e).webkitTextFillColor})));
      assert.equal(filters.length,4);assert.ok(filters.every(b=>b.color==='rgb(0, 0, 0)'&&b.fill==='rgb(0, 0, 0)'));
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
    }
    report.searchFiltersReadable=true;report.mobileOverflow=false;report.passed=true;
    await page.screenshot({path:'search-black-mobile.png'});
  }finally{
    fs.writeFileSync('data/search-contrast-verification.json',JSON.stringify(report,null,2));
    await browser.close();
  }
  console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
