/* Pre-game yardage outlook for every verified QB/RB/WR/TE profile.
   Career, season, five-game and opponent inputs share the same source.
   Percentages are estimates from an explicitly labeled experimental model. */
(function(root){
  'use strict';
  if(root.GPYardageOutlook)return;
  var src=document.currentScript.src;
  var cache=null,pending=null;
  var ALIAS={LA:'LAR',STL:'LAR',WSH:'WAS',JAC:'JAX',SD:'LAC',OAK:'LV'};
  var METRICS={
    QB:[['passingYards','Passing yards'],['rushingYards','Rushing yards']],
    RB:[['scrimmageYards','Rushing + receiving yards'],['rushingYards','Rushing yards'],['receivingYards','Receiving yards']],
    WR:[['receivingYards','Receiving yards'],['rushingYards','Rushing yards']],
    TE:[['receivingYards','Receiving yards']]
  };
  function tm(v){v=String(v||'').toUpperCase();return ALIAS[v]||v;}
  function norm(v){return String(v||'').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,'');}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function n(v){if(v==null||v===''||typeof v==='boolean')return null;var x=Number(v);return Number.isFinite(x)?x:null;}
  function fmt(v){return n(v)==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:1});}
  function pct(v){return n(v)==null?'—':Math.round(100*v)+'%';}
  function avg(v){return v&&n(v.value)!==null?v.value:null;}
  function nowSeason(){var d=new Date();return d.getUTCFullYear()-(d.getUTCMonth()<2?1:0);}
  function normalCDF(z){
    // Abramowitz-Stegun 7.1.26 approximation, max abs error ~7.5e-8.
    var x=Math.abs(z),t=1/(1+.2316419*x);
    var d=.3989422804014327*Math.exp(-x*x/2);
    var q=d*t*(.319381530+t*(-.356563782+t*(1.781477937+t*(-1.821255978+t*1.330274429))));
    return z>=0?1-q:q;
  }
  function fetchFeed(){
    if(cache)return Promise.resolve(cache);
    if(pending)return pending;
    pending=fetch(new URL('../data/player-yardage-outlook.json',src).href+'?v='+Math.floor(Date.now()/1800000),{cache:'no-cache'})
      .then(function(r){if(!r.ok)throw Error('Yardage model not available');return r.json();})
      .then(function(d){if(!d||d.ok!==true||d.schemaVersion!==1||!d.players||!d.model)throw Error('Invalid yardage source');cache=d;return d;})
      .finally(function(){pending=null;});
    return pending;
  }
  function resolve(d,source){
    var items=source.players,id=String(d.id||d.player_id||'');
    if(items[id])return items[id];
    var eid=String(d.espnId||d.athleteId||'');
    if(eid){var got=Object.values(items).filter(function(p){return p.espnId&&String(p.espnId)===eid;});if(got.length===1)return got[0];}
    if(/^00-\d+$/.test(id)||eid)return null;
    var matches=Object.values(items).filter(function(p){
      return norm(p.name)===norm(d.name)&&(!d.position||p.position===d.position);
    });
    if(matches.length>1&&d.team)matches=matches.filter(function(p){return tm(p.team)===tm(d.team);});
    return matches.length===1?matches[0]:null;
  }
  function compute(metric, opponent, model){
    if(!metric||!metric.career||!metric.career.n||!n(metric.career.value))return null;
    var prior=avg(metric.priorCareer),season=avg(metric.season),career=avg(metric.career);
    var currentN=(metric.season&&metric.season.n)||0;
    var last5=avg(metric.last5),recentN=(metric.last5&&metric.last5.n)||0;
    var history=metric.opponents&&metric.opponents[tm(opponent)]||null;
    var versus=history&&n(history.value),versusN=history&&n(history.effectiveN)||0;
    var baseline=season!==null?((currentN*season+6*(prior===null?career:prior))/(currentN+6)):(prior===null?career:prior);
    var recentRef=season!==null?season:baseline;
    var trend=last5===null?0:.45*recentN/(recentN+5)*(last5-recentRef);
    var h2h=versus===null?0:.35*versusN/(versusN+3)*(versus-baseline);
    var raw=Math.max(0,baseline+trend+h2h);
    return {forecast:raw,career:career,season:season,last5:last5,h2h:history,
      recentN:recentN,currentN:currentN,historyN:metric.career.n,
      calibration:model};
  }
  function predict(result,calibration,check,opponentAvailable,sourceFresh){
    if(!result||!calibration||!check||!opponentAvailable||!sourceFresh||
       result.historyN<5||check.holdoutN<80)return null;
    var coverage=n(check.holdout2025Coverage80);
    if(coverage===null||coverage<.68||coverage>.92)return null;
    var sigma=n(calibration.sigma),bias=n(calibration.bias);
    if(sigma===null||sigma<=0||bias===null)return null;
    var center=Math.max(0,result.forecast+bias);
    var low=center-1.2815515655446004*sigma;
    // A player can lose yards rushing; receiving/passing are nonnegative.
    return {
      center:center,low:low,high:center+1.2815515655446004*sigma,
      aboveSeason:result.season===null?null:normalCDF((center-result.season)/sigma),
      aboveCareer:result.career===null?null:normalCDF((center-result.career)/sigma),
      coverage:coverage,testN:check.holdoutN,sigma:sigma
    };
  }
  function metricCard(label,info){
    return '<div class="gp-yards-stat"><small>'+esc(label)+'</small><strong>'+esc(info&&n(info.value)!==null?fmt(info.value):'—')+'</strong>'+
      '<span>'+esc(info&&info.n?info.n+' recorded appearance'+(info.n===1?'':'s'):'No recorded appearances')+'</span></div>';
  }
  function probability(label,p){
    if(p===null||p===undefined)return '<div class="gp-yards-prob"><div class="gp-yards-prob-head"><span>'+esc(label)+'</span><strong>Unavailable</strong></div></div>';
    var val=Math.round(p*100);
    return '<div class="gp-yards-prob"><div class="gp-yards-prob-head"><span>'+esc(label)+'</span><strong>'+val+'% above · '+(100-val)+'% below</strong></div>'+
      '<div class="gp-yards-prob-track" role="meter" aria-label="'+esc(label)+' chance above" aria-valuemin="0" aria-valuemax="100" aria-valuenow="'+val+'">'+
      '<i style="width:'+val+'%"></i></div></div>';
  }
  function render(host,d,opponent,source,player,selected){
    var options=METRICS[player.position]||[],chosen=options.some(function(x){return x[0]===selected;})?selected:options[0][0];
    var metrics=player.metrics&&player.metrics[chosen]||null,code=tm(opponent&&opponent.team);
    var result=metrics?compute(metrics,code,source.model):null;
    var key=player.position+'_'+chosen;
    var calibrate=source.model.calibration&&source.model.calibration[key];
    var check=source.model.holdout&&source.model.holdout[key];
    var generated=Date.parse(source.generatedAt);
    var fresh=Number(source.season)===nowSeason()&&Number.isFinite(generated)&&Math.abs(Date.now()-generated)<72*3600000;
    var prob=predict(result,calibrate,check,Boolean(code),fresh);
    var target=result&&result.h2h||null;
    var h2h=target&&target.raw||{value:null,n:0};
    var status=result&&result.historyN>=5&&code&&fresh;
    var opts=options.map(function(x){return '<option value="'+esc(x[0])+'"'+(x[0]===chosen?' selected':'')+'>'+esc(x[1])+'</option>';}).join('');
    var historical=metrics&&metrics.career||{value:null,n:0};
    var s=metrics&&metrics.season||{value:null,n:0};
    var last=metrics&&metrics.last5||{value:null,n:0};
    var subheading=options.find(function(x){return x[0]===chosen;})||options[0];
    var markup='<div class="gp-yards-title"><div><p class="gc-kicker">NEXT GAME / YARDAGE OUTLOOK</p>'+
      '<h4>Range & chances to beat the average</h4>'+
      '<p>'+esc(code?'Upcoming opponent: '+code:'Opponent not yet verified')+' · '+esc(subheading[1])+'</p></div>'+
      '<label>Yardage type<select data-gp-yards-metric aria-label="Yardage outlook statistic">'+opts+'</select></label></div>'+
      '<div class="gp-yards-comparisons" aria-label="Four verified yardage averages">'+
       metricCard('Career average',historical)+
       metricCard('Season average',s)+
       metricCard('Last 5 average',last)+
       metricCard('H2H vs '+(code||'opponent'),h2h)+'</div>';
    if(prob){
      var low=chosen==='rushingYards'?prob.low:Math.max(0,prob.low);
      markup+='<div class="gp-yards-range" aria-label="Experimental eighty percent prediction interval">'+
        '<div><small>LOW · 10th percentile</small><strong data-yards-low>'+esc(fmt(low))+'</strong></div>'+
        '<div class="gp-yards-point"><small>PROJECTED</small><strong data-yards-projected>'+esc(fmt(prob.center))+'</strong></div>'+
        '<div><small>HIGH · 90th percentile</small><strong data-yards-high>'+esc(fmt(prob.high))+'</strong></div></div>'+
        '<div class="gp-yards-prob-grid">'+
         probability('Chance above season average',prob.aboveSeason)+
         probability('Chance above career average',prob.aboveCareer)+'</div>'+
        '<p class="gp-yards-footnote">Experimental pregame estimate, conditional on a recorded appearance. '+
        '80% range is not a cap. The 2025 held-out sample covered '+Math.round(prob.coverage*100)+
        '% inside the nominal 80% range (n='+prob.testN+'). Percentages are model estimates, not guaranteed results.</p>';
    }else{
      var reasons=[];
      if(!metrics||!metrics.career||!metrics.career.n)reasons.push('no published individual yardage history');
      else if(metrics.career.n<5)reasons.push('fewer than five recorded appearances');
      if(!code)reasons.push('next opponent not verified');
      if(!fresh)reasons.push('current model feed not fresh');
      if(!calibrate||!check||check.holdoutN<80)reasons.push('not enough historical validation cases');
      else if(check.holdout2025Coverage80<.68||check.holdout2025Coverage80>.92)reasons.push('uncertainty range did not pass validation');
      markup+='<p class="gp-yards-limited">Limited data: '+esc(reasons.join('; ')||'a tested probability is not currently available')+
        '. Range and above/below percentages are withheld.</p>';
    }
    markup+='<p class="gp-yards-footnote">H2H is weighted toward recent meetings; one old game has limited influence. '+
      'The career figure uses verified regular-season stat rows since 1999; season and last-five figures use recorded appearances. '+
      'Missing game stats are never counted as zero. Source through '+esc(source.season)+
      ' season · next-opponent data is not a separate forecast guarantee.</p>';
    host.innerHTML=markup;
    var select=host.querySelector('[data-gp-yards-metric]');
    if(select)select.addEventListener('change',function(){
      render(host,d,opponent,source,player,select.value);
      var current=host.querySelector('[data-gp-yards-metric]');if(current)current.focus({preventScroll:true});
    });
  }
  function mount(container,d,opponent){
    if(!container||!container.isConnected||!METRICS[d.position])return;
    var host=document.createElement('section');
    host.className='gp-yards-outlook';
    host.setAttribute('aria-label','Next-game yardage outlook');
    host.innerHTML='<p class="gp-yards-limited" role="status">Loading career and matchup yardage history…</p>';
    var intro=container.querySelector('.gc-player-intro');
    if(intro)intro.before(host);else container.prepend(host);
    fetchFeed().then(function(source){
      if(!host.isConnected)return;
      var player=resolve(d,source);
      if(!player||!METRICS[player.position]){
        host.innerHTML='<p class="gp-yards-limited">Limited data: verified career yardage records are not available for this player.</p>';return;
      }
      render(host,d,opponent,source,player,METRICS[player.position][0][0]);
    }).catch(function(){
      if(host.isConnected)host.innerHTML='<p class="gp-yards-limited">Yardage outlook temporarily unavailable. Verified game logs and the weekly comparison remain below.</p>';
    });
  }
  root.GPYardageOutlook={mount:mount,compute:compute,predict:predict,normalCDF:normalCDF};
})(window);
