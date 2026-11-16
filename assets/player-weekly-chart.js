/* A single grouped weekly plot. Input values come from the existing comparison model. */
(function(root){
  'use strict';
  function number(v){if(v==null||v===''||typeof v==='boolean')return null;var n=Number(v);return Number.isFinite(n)?n:null;}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function fmt(v){return number(v)===null?'Unavailable':Number(v).toLocaleString(undefined,{maximumFractionDigits:1});}
  function day(v){var d=new Date(String(v).length===10?v+'T12:00:00Z':v);return Number.isFinite(d.getTime())?d.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}):'Date unavailable';}
  function axis(values){
    var ns=values.map(number).filter(function(v){return v!==null;});
    var min=Math.min.apply(null,[0].concat(ns)),max=Math.max.apply(null,[0].concat(ns));
    var raw=Math.max(1,max-min)/5,power=Math.pow(10,Math.floor(Math.log10(raw))),ratio=raw/power;
    var step=(ratio<=1?1:ratio<=2?2:ratio<=5?5:10)*power;
    var low=min<0?Math.floor(min*1.12/step)*step:0;
    var high=Math.max(step,Math.ceil(Math.max(0,max)*1.12/step)*step);
    return {low:low,high:high,step:step};
  }
  function render(rows,seasonValue,h2hValue,metricLabel,code,compatible){
    rows=Array.isArray(rows)?rows:[];
    var values=[seasonValue,h2hValue];rows.forEach(function(r){values.push(r.playerValue,r.defenseValue);});
    var domain=axis(values),W=Math.max(1100,rows.length*190+92),H=484,L=68,R=W-24,T=40,B=326;
    var pw=R-L,ph=B-T,pitch=pw/Math.max(1,rows.length),barWidth=Math.min(34,pitch/5),gap=10;
    function y(v){return B-(v-domain.low)/(domain.high-domain.low)*ph;}
    var zero=y(0),h2h=number(h2hValue);
    var grid='';
    for(var tick=domain.low;tick<=domain.high+domain.step/10;tick+=domain.step){
      var ty=y(tick);grid+='<line class="gc-wide-gridline" x1="'+L+'" x2="'+R+'" y1="'+ty+'" y2="'+ty+'"/>'+
        '<text class="gc-wide-tick" x="'+(L-12)+'" y="'+(ty+5)+'" text-anchor="end">'+esc(fmt(tick))+'</text>';
    }
    var series=[['player','Player actual'],['season','Season average'],['defense',(code?code+' ':'')+'allowed to position']];
    var allGroups=rows.map(function(row,i){
      var cx=L+pitch*(i+.5),week=Number.isFinite(Number(row.week))?'Week '+row.week:'Game '+(i+1);
      var p=row.playerGame,d=row.defenseGame;
      var pText=p?('Player '+(p.team||'')+' vs '+(p.opponent||'?')).trim():'Player: no recorded game';
      var dText=d?(code+' defense '+(d.home?'vs ':'@ ')+(d.opponent||'?')).trim():'Defense: no recorded game';
      var vals=[row.playerValue,seasonValue,row.defenseValue];
      var bars=series.map(function(s,k){
        var value=number(vals[k]),x=cx+(k-1)*(barWidth+gap)-barWidth/2;
        var pos=value===null?zero:y(value),top=Math.min(zero,pos),height=value===null?0:Math.abs(pos-zero);
        var valueY=value!==null&&value<0?pos+18:pos-9;
        var label=week+', '+s[1]+': '+(value===null?'Unavailable':fmt(value))+' '+metricLabel;
        return '<g class="gc-triple-level gc-wide-series gc-wide-'+s[0]+'" data-gc-level="'+s[0]+
          '" data-gc-week="'+esc(row.week)+'" data-value="'+(value===null?'':value)+'" tabindex="0" role="img" aria-label="'+esc(label)+'">'+
          '<title>'+esc(label)+'; '+esc(pText)+'; '+esc(dText)+'</title>'+
          (value===null?'<text class="gc-wide-missing" x="'+(x+barWidth/2)+'" y="'+(zero-10)+'" text-anchor="middle">&#8212;</text>':
            value===0?'<line class="gc-wide-zero-value" x1="'+x+'" x2="'+(x+barWidth)+'" y1="'+zero+'" y2="'+zero+'"/>':
              '<rect class="gc-wide-bar" x="'+x+'" y="'+top+'" width="'+barWidth+'" height="'+height+'" rx="2"/>')+
          (value===null?'':'<text class="gc-wide-value" x="'+(x+barWidth/2)+'" y="'+valueY+'" text-anchor="middle">'+esc(fmt(value))+'</text>')+'</g>';
      }).join('');
      return '<g class="gc-triple-week gc-wide-week" data-gc-week-group="'+esc(row.week)+'">'+bars+
        '<text class="gc-wide-week-name" x="'+cx+'" y="366" text-anchor="middle">'+esc(week)+'</text>'+
        '<text class="gc-wide-context" x="'+cx+'" y="392" text-anchor="middle">'+esc(pText)+'</text>'+
        '<text class="gc-wide-date" x="'+cx+'" y="409" text-anchor="middle">'+esc(p?day(p.date):'Unavailable, not zero')+'</text>'+
        '<text class="gc-wide-context" x="'+cx+'" y="437" text-anchor="middle">'+esc(dText)+'</text>'+
        '<text class="gc-wide-date" x="'+cx+'" y="454" text-anchor="middle">'+esc(d?day(d.date):'Unavailable, not zero')+'</text></g>';
    }).join('');
    var hasDefense=rows.some(function(r){return !!r.defenseGame;});
    var svg='<svg xmlns="http://www.w3.org/2000/svg" class="gc-wide-weekly-chart" viewBox="0 0 '+W+' '+H+'" role="group" aria-label="'+esc(metricLabel)+' by NFL week; three grouped bars on one shared axis" data-axis-min="'+domain.low+'" data-axis-max="'+domain.high+'">'+
      '<title>Weekly player and opponent-defense comparison</title><desc>Blue is player actual, lime is season average, orange is full opposing-position allowance. A purple horizontal dashed line marks the available H2H average. Missing observations have no bar.</desc>'+
      grid+'<line class="gc-wide-baseline" x1="'+L+'" x2="'+R+'" y1="'+zero+'" y2="'+zero+'"/>'+
      (h2h===null?'':'<line class="gc-wide-h2h-line" data-reference-value="'+h2h+'" x1="'+L+'" x2="'+R+'" y1="'+y(h2h)+'" y2="'+y(h2h)+'"><title>H2H average '+esc(fmt(h2h))+'</title></line>')+allGroups+'</svg>';
    var table='<details class="gc-wide-data"><summary>View chart values as a table</summary><div class="gc-wide-table-scroll"><table><caption>'+esc(metricLabel)+' per NFL week</caption><thead><tr><th scope="col">Week</th><th scope="col">Player actual</th><th scope="col">Season average</th><th scope="col">Defense allowed</th></tr></thead><tbody>'+
      rows.map(function(r){return '<tr><th scope="row">'+esc(r.week)+'</th><td>'+esc(fmt(r.playerValue))+'</td><td>'+esc(fmt(seasonValue))+'</td><td>'+esc(fmt(r.defenseValue))+'</td></tr>';}).join('')+'</tbody></table></div></details>';
    return '<section class="gc-unified-graph gc-weekly-large" aria-label="Single weekly comparison chart">'+
      '<div class="gc-unified-head"><div><p class="gc-kicker">ONE CHART / WEEK BY WEEK</p><h4>'+esc(metricLabel)+'</h4><p>'+esc(hasDefense?'Upcoming opponent\'s last five completed games, aligned to the same NFL weeks.':'Latest available player games; opponent defense is unavailable.')+'</p></div><div class="gc-axis-range">One shared scale</div></div>'+
      '<div class="gc-triple-legend" aria-label="Chart legend"><span class="gc-legend-player">Player actual</span><span class="gc-legend-season">Season average</span><span class="gc-legend-defense">Defense allowed (whole position group)</span>'+
      (h2h===null?'<span>H2H unavailable</span>':'<span class="gc-legend-h2h">H2H average: <b data-gc-h2h-value="'+h2h+'">'+esc(fmt(h2h))+'</b></span>')+'</div>'+
      '<p class="gc-wide-swipe">Swipe or scroll sideways to compare every week.</p>'+
      (rows.length?'<div class="gc-wide-chart-scroll" tabindex="0" role="region" aria-label="Weekly bar chart; scroll horizontally on small screens">'+svg+'</div>':'<p class="gc-visual-empty">No verified weekly records are available for this matchup.</p>')+
      '<p class="gc-unified-caption">Three side-by-side bars per week, all using the same scale. The season average is the latest published baseline, repeated for comparison. The dashed line is the available H2H average. Player and defense figures are from <strong>different games in the same NFL week</strong>; defense allowance covers <strong>the entire opposing position group</strong>, not one player. Missing values are unavailable, not zero.</p>'+
      (!compatible?'<p class="gc-defense-disclosure">This position-specific defensive statistic is not available. Its bars stay blank; no different statistic has been substituted.</p>':'')+table+'</section>';
  }
  var api={render:render,axis:axis};root.GPWeeklyChart=api;
  if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
