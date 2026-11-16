'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const chart=require('../assets/player-weekly-chart.js');

(async()=>{
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1600,height:1000},reducedMotion:'reduce'});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const report={mode:'Synthetic geometry/edge-case fixture; real data are checked separately by check_defense_comparisons.js',sizes:[],passed:false};
  try{
    const rows=[-5,0,200,null,320].map((v,i)=>({week:i+5,playerValue:v,defenseValue:i===1?null:200+i*12,
      playerGame:{team:'BUF',opponent:'NYJ',date:'2026-10-25'},
      defenseGame:{opponent:'KC',home:true,date:'2026-10-26'}}));
    const out=chart.render(rows,200,245.5,'Passing yards','MIA',true);
    assert.doesNotMatch(out,/NaN|Infinity/);
    const domain=chart.axis([-5,0,320,245.5]);assert.ok(domain.low<=-5&&domain.high>=320&&domain.step>0);
    const empty=chart.render([],null,null,'Receptions','',false);
    assert.match(empty,/No verified weekly records/);assert.doesNotMatch(empty,/NaN|Infinity/);
    const escaped=chart.render(rows,200,null,'<script>bad</script>','<bad>',true);
    assert.doesNotMatch(escaped,/<script>/);
    await page.setContent('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div class="gp-h2h-root"><div class="gp-compare gc-player">'+out+'</div></div></body></html>');
    await page.addStyleTag({content:'*{box-sizing:border-box}body{margin:0;background:#07110d;color:#fff;font-family:system-ui}.gp-h2h-root{width:calc(100% - 24px);margin:12px auto!important;min-width:0}'});
    for(const path of ['assets/player-game-log.css','assets/matchup-comparisons.css','assets/player-comparison-v2.css','assets/player-weekly-chart.css'])await page.addStyleTag({path});
    assert.equal(await page.locator('.gc-unified-graph').count(),1);
    assert.equal(await page.locator('svg.gc-wide-weekly-chart').count(),1);
    assert.equal(await page.locator('.gc-triple-week').count(),5);
    assert.equal(await page.locator('.gc-triple-level').count(),15);
    assert.equal(await page.locator('.gc-triple-weeks,.gc-triple-stack,.gc-triple-track').count(),0);
    assert.equal(await page.locator('.gc-wide-h2h-line').count(),1);
    assert.equal(await page.locator('.gc-wide-h2h-line').getAttribute('data-reference-value'),'245.5');
    const geo=await page.evaluate(()=>{
      const baseline=Number(document.querySelector('.gc-wide-baseline').getAttribute('y1'));
      return {baseline,series:Array.from(document.querySelectorAll('.gc-triple-level')).map(n=>{
        const r=n.querySelector('rect');return {week:Number(n.dataset.gcWeek),level:n.dataset.gcLevel,value:n.dataset.value,
          hasRect:!!r,x:r?Number(r.getAttribute('x')):null,y:r?Number(r.getAttribute('y')):null,height:r?Number(r.getAttribute('height')):null};
      }),weeks:Array.from(document.querySelectorAll('.gc-wide-week-name')).map(n=>({x:Number(n.getAttribute('x')),y:Number(n.getAttribute('y'))}))};
    });
    assert.ok(geo.weeks.every((w,i)=>i===0||w.x>geo.weeks[i-1].x));
    assert.ok(geo.weeks.every(w=>w.y===geo.weeks[0].y));
    geo.series.forEach(s=>{
      const row=rows.find(r=>r.week===s.week);const expected=s.level==='player'?row.playerValue:s.level==='season'?200:row.defenseValue;
      assert.equal(s.value,expected===null?'':String(expected));
      if(expected===null||expected===0)assert.equal(s.hasRect,false);
      else if(expected>0)assert.ok(Math.abs(s.y+s.height-geo.baseline)<1e-8);
      else assert.equal(s.y,geo.baseline);
    });
    const equal=geo.series.filter(s=>s.value==='200');assert.ok(equal.every(s=>Math.abs(s.height-equal[0].height)<1e-8));
    report.onePlot=true;report.threeBarsPerWeek=true;report.oneH2HReference=true;report.exactValues=true;report.negativeZeroAndMissing=true;report.commonBaseline=true;
    for(const width of [1600,1366,1024,768,390,320]){
      await page.setViewportSize({width,height:1000});
      const s=await page.evaluate(()=>{const scroll=document.querySelector('.gc-wide-chart-scroll');return {width:innerWidth,page:document.documentElement.scrollWidth,chartViewport:scroll.clientWidth,chartWidth:scroll.scrollWidth,plots:document.querySelectorAll('svg.gc-wide-weekly-chart').length};});
      assert.ok(s.page<=width+2,'No document overflow: '+JSON.stringify(s));
      assert.equal(s.plots,1);if(width<=768)assert.ok(s.chartWidth>s.chartViewport,'Small screens scroll a single chart');
      report.sizes.push(s);
      if(width===1600)await page.screenshot({path:'weekly-wide-desktop.png',fullPage:true});
      if(width===390){
        await page.screenshot({path:'weekly-wide-mobile.png',fullPage:true});
        await page.locator('.gc-wide-chart-scroll').evaluate(n=>{n.scrollLeft=n.scrollWidth;});
        assert.ok(await page.locator('.gc-wide-chart-scroll').evaluate(n=>n.scrollLeft>0));
      }
    }
    await page.locator('.gc-wide-chart-scroll').focus();assert.ok(await page.locator('.gc-wide-chart-scroll').evaluate(n=>document.activeElement===n));
    await page.locator('.gc-wide-data summary').click();assert.equal(await page.locator('.gc-wide-data tbody tr').count(),5);
    assert.deepEqual(errors,[]);report.errors=errors;report.passed=true;
  }catch(error){report.error=String(error);report.errors=errors;throw error;}
  finally{fs.writeFileSync('weekly-wide-verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
