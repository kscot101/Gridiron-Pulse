/* Plain-language context only. Never selects picks or changes forecast values. */
(function(root){
  'use strict';
  if(root.GPPickReasons)return;
  var playerFeed=null,defenseFeed=null;
  var POSITIONS=['QB','RB','WR','TE'];
  function list(v){return Array.isArray(v)?v:[];}
  function team(v){v=String(v||'').toUpperCase();return {WSH:'WAS',JAC:'JAX',LA:'LAR',OAK:'LV',SD:'LAC'}[v]||v;}
  function norm(v){return String(v||'').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,'');}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function num(v){return typeof v==='number'&&Number.isFinite(v)?v:null;}
  function fmt(v){return v.toLocaleString(undefined,{maximumFractionDigits:1});}
  function time(v){var t=Date.parse(v||'');return Number.isFinite(t)?new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Time unavailable';}
  function day(v){var t=typeof v==='number'?v:Date.parse(v||'');return Number.isFinite(t)?new Date(t).toISOString().slice(0,10):'';}
  function input(r,p){
    r=r||{};p=p||{};
    return {player_id:String(r.player_id||p.player_id||p.gsisId||''),athleteId:String(r.athleteId||p.athleteId||p.espnId||''),name:r.playerName||p.name||'',position:r.position||p.position||'',team:team(r.team||p.team),opponent:team(r.opponent||p.opponent||p.nextOpponent),season:r.season||null,week:r.week||null,kickoff:r.kickoff||'',historyGames:r.historyGames};
  }
  function validFeed(d,r,now){
    var y=new Date(now).getUTCFullYear()-(new Date(now).getUTCMonth()<2?1:0),t=Date.parse(d&&d.generatedAt||'');
    return !!(d&&d.ok===true&&d.schemaVersion===1&&d.seasonType==='REG'&&Number(d.season)===Number(r.season||y)&&Number(d.season)===y&&Number.isFinite(t)&&t<=now+300000&&now-t<=72*3600000);
  }
  function resolve(d,r){
    var all=Object.values(d.players||{}),p=r.player_id&&(d.players||{})[r.player_id];
    function compatible(x){return x&&team(x.team)===r.team&&x.position===r.position;}
    if(p)return compatible(p)?p:null;
    if(r.athleteId){var exact=all.filter(function(x){return String(x.espnId||'')===r.athleteId;});if(exact.length)return exact.length===1&&compatible(exact[0])?exact[0]:null;}
    // A provided stable identity must never fall back to somebody else's name.
    if(r.player_id)return null;
    var names=all.filter(function(x){return compatible(x)&&norm(x.name)===norm(r.name);});
    return names.length===1?names[0]:null;
  }
  function recent(rows,r,now,limit,isPlayer){
    var cutoff=day(Math.min(now,Date.parse(r.kickoff)||now)),map=new Map(),conflicts=new Set();
    list(rows).forEach(function(g){
      if(!g||!g.id||!day(g.date)||day(g.date)>=cutoff||isPlayer&&team(g.team)!==r.team)return;
      if(r.week&&Number(g.week)>=Number(r.week))return;
      var k=String(g.id),previous=map.get(k);
      if(previous&&JSON.stringify(previous)!==JSON.stringify(g))conflicts.add(k);
      else map.set(k,g);
    });
    return Array.from(map.entries()).filter(function(x){return !conflicts.has(x[0]);}).map(function(x){return x[1];}).sort(function(a,b){return String(b.date).localeCompare(String(a.date));}).slice(0,limit);
  }
  function mean(games,key){
    if(!games.length||games.some(function(g){return num((g.values||{})[key])===null;}))return null;
    return games.reduce(function(sum,g){return sum+g.values[key];},0)/games.length;
  }
  function describe(r,players,defense,now){
    now=now||Date.now();var out={recent:'',matchup:'',through:''},p=validFeed(players,r,now)?resolve(players,r):null;
    var games=p?recent(p.games,r,now,5,true):[],n=games.length,parts=[];
    var fields=r.position==='QB'?[['passingYards','passing yards']]:r.position==='RB'?[['carries','carries'],['scrimmageYards','rushing + receiving yards']]:[['targets','targets'],['receptions','catches']];
    fields.forEach(function(f){var v=mean(games,f[0]);if(v!==null)parts.push(fmt(v)+' '+f[1]);});
    if(!parts.length&&(r.position==='WR'||r.position==='TE')){var yards=mean(games,'receivingYards');if(yards!==null)parts.push(fmt(yards)+' receiving yards');}
    if(parts.length){out.recent=n===1?'Had '+parts.join(' and ')+' in his latest recorded game with '+r.team+'.':'Averaged '+parts.join(' and ')+' per game over his last '+n+' recorded games with '+r.team+'.';out.through=day(games[0].date);}
    if(!out.recent){
      var h=num(r.historyGames);
      out.recent=h!==null&&h>0?'This projection uses '+h+' earlier appearances with '+r.team+'. Detailed recent-form numbers are unavailable.':'Featured for the upcoming '+r.team+(r.opponent?' vs '+r.opponent:'')+' matchup. Detailed recent-form numbers are unavailable.';
    }
    var d=validFeed(defense,r,now)&&r.opponent!==r.team&&(defense.teams||{})[r.opponent];
    if(d&&POSITIONS.includes(r.position)){
      var gs=recent(d.games,r,now,3,false),key=r.position==='QB'?'QB_passingYards':r.position==='RB'?'RB_scrimmageYards':r.position+'_receivingYards',value=mean(gs,key);
      var metric=r.position==='QB'?'passing yards':r.position==='RB'?'rushing + receiving yards':'receiving yards';
      if(value!==null&&gs.length>=2){out.matchup=r.opponent+' allowed '+fmt(value)+' '+metric+' per game to opposing '+r.position+'s combined over its last '+gs.length+' games.';out.through=[out.through,day(gs[0].date)].filter(Boolean).sort().pop();}
    }
    return out;
  }
  function body(r){
    var d=describe(r,playerFeed,defenseFeed,Date.now());
    return '<strong>Why this player</strong><p>'+esc(d.recent)+'</p>'+(d.matchup?'<p class="gp-reason-matchup"><b>Matchup note:</b> '+esc(d.matchup)+'</p>':'')+(d.through?'<small>Recent-stat context through '+esc(new Date(d.through+'T12:00:00Z').toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:'UTC'}))+'. Not a guarantee.</small>':'');
  }
  function markup(record,pick){var r=input(record,pick);return '<div class="gp-pick-reason" data-pick-reason="'+esc(JSON.stringify(r))+'">'+body(r)+'</div>';}
  function label(model){return model==='workload-trial-1'?'Recent-usage estimate':'Standard estimate';}
  function details(r){
    if(!r)return '';
    return '<details class="gp-pick-details"><summary>Projection details</summary><p>'+esc(label(r.model))+'. Saved '+esc(time(r.recordedAt))+'.</p>'+(r.modelFallback?'<p>The selected estimate is unavailable for this matchup; this card shows the available alternative.</p>':'')+'<p>Pregame estimate, assuming the player plays. Injuries or lineup changes may not yet be reflected. A touchdown estimate is an expected count, not the chance of scoring.</p></details>';
  }
  function hydrate(){if(!root.document)return;document.querySelectorAll('[data-pick-reason]').forEach(function(el){try{el.innerHTML=body(JSON.parse(el.dataset.pickReason));}catch(e){/* Keep the existing safe explanation. */}});}
  async function read(name){var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort();},8000);try{var response=await fetch('./data/'+name+'.json?reasons='+Math.floor(Date.now()/3600000),{cache:'no-cache',signal:ctl.signal});if(!response.ok)return null;return await response.json();}catch(e){return null;}finally{clearTimeout(timer);}}
  async function load(){var feeds=await Promise.all([read('defense-players'),read('team-defense')]);playerFeed=feeds[0];defenseFeed=feeds[1];hydrate();}
  root.GPPickReasons={markup:markup,details:details,label:label,describe:describe,input:input};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.GPPickReasons;
  if(root.document){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',load,{once:true});else load();}
})(typeof window!=='undefined'?window:globalThis);
