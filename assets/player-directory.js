/* Independent roster/stat directory. Never changes picks or forecasts. */
(function(root){
  'use strict';
  if(root.GPPlayerDirectory)return;
  var records=[],byId=new Map(),byEspn=new Map(),pending=null,loadedAt=0;
  var script=root.document&&document.currentScript;
  var url=script?new URL('../data/player-directory.json',script.src).href:'';
  function arr(v){return Array.isArray(v)?v:[];}
  function norm(v){return String(v||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,'');}
  function position(v){v=typeof v==='object'&&v?v.abbreviation:v;v=String(v||'').toUpperCase();return {FB:'RB',HB:'RB',TB:'RB',LWR:'WR',RWR:'WR',SWR:'WR',FL:'WR',SE:'WR',LTE:'TE',RTE:'TE'}[v]||v;}
  function team(v){v=typeof v==='object'&&v?v.abbreviation||v.team:v;v=String(v||'').toUpperCase();return {LA:'LAR',STL:'LAR',JAC:'JAX',WSH:'WAS',SD:'LAC',OAK:'LV'}[v]||v;}
  function identities(p){
    var id=String(p.player_id||p.gsisId||p.gsis_id||p.id||''),espn=String(p.athleteId||p.espnId||p.espn_id||'');
    if(!espn&&/^\d+$/.test(id))espn=id;
    if(!espn&&id.startsWith('espn:'))espn=id.slice(5);
    return {id:id,espn:espn};
  }
  function ingest(data){
    if(!data||data.ok!==true||data.schemaVersion!==1||!Array.isArray(data.players))throw Error('Invalid player directory');
    var ids=new Map(),espns=new Map();
    data.players.forEach(function(p){
      if(!p.id||!p.name||ids.has(p.id))throw Error('Conflicting player directory identity');
      ids.set(p.id,p);
      if(p.athleteId){if(espns.has(String(p.athleteId)))throw Error('Conflicting ESPN identity');espns.set(String(p.athleteId),p);}
    });
    records=data.players;byId=ids;byEspn=espns;loadedAt=Date.now();api.status='ready';return records;
  }
  function resolve(p){
    p=p||{};var key=identities(p),a=byId.get(key.id),b=byEspn.get(key.espn);
    if(a&&b&&a.id!==b.id)return null;
    if(a||b)return a||b;
    // Never override an unresolved explicit provider ID with a name guess.
    if(key.espn||/^00-\d+$/.test(key.id))return null;
    var name=norm(p.name||p.playerName||p.player_display_name||p.displayName||p.player_name),pos=position(p.position||p.positionGroup||p.pos),club=team(p.team);
    if(!name)return null;
    var matches=records.filter(function(x){return arr(x.aliases).concat(x.name).some(function(n){return norm(n)===name;})&&(!pos||position(x.position)===pos);});
    if(matches.length>1&&club)matches=matches.filter(function(x){return arr(x.teams).map(team).includes(club);});
    return matches.length===1?matches[0]:null;
  }
  function enrich(p){
    p=p||{};var d=resolve(p);if(!d)return p;
    return Object.assign({},d,p,{player_id:d.player_id||p.player_id,id:d.id,athleteId:d.athleteId||p.athleteId,espnId:d.athleteId||p.espnId,aliases:d.aliases,position:position(p.position||p.positionGroup||d.position),name:p.name||p.playerName||d.name});
  }
  function merge(existing){
    var map=new Map();
    arr(existing).forEach(function(p){
      var d=resolve(p),x=enrich(p);if(!x.name)return;
      if(d)x=Object.assign({},x,{name:d.name,team:d.team,position:position(d.position),directoryOnly:false});
      var key=d?d.id:identities(x).espn||identities(x).id||team(x.team)+':'+norm(x.name);
      if(!map.has(key))map.set(key,x);
    });
    records.forEach(function(d){if(!map.has(d.id))map.set(d.id,Object.assign({},d,{position:position(d.position),directoryOnly:true}));});
    return Array.from(map.values());
  }
  function matches(item,query){
    var names=arr(item.aliases).concat(item.title||item.name||''),q=norm(query),hay=norm(names.join(' ')+' '+(item.meta||''));
    return !q||names.some(function(n){return norm(n).includes(q);})||String(query).trim().split(/\s+/).every(function(t){var k=norm(t);return !k||hay.includes(k);});
  }
  function rank(item,query){var names=arr(item.aliases).concat(item.title||item.name||'').map(norm),q=norm(query);return q&&names.includes(q)?0:q&&names.some(function(n){return n.startsWith(q);})?1:2;}
  async function load(force){
    if(!force&&records.length&&Date.now()-loadedAt<3600000)return records;
    if(pending)return pending;
    api.status='loading';var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort();},10000);
    pending=fetch(url+'?directory='+Math.floor(Date.now()/3600000),{cache:'no-cache',signal:ctl.signal}).then(function(r){if(!r.ok)throw Error('Player directory unavailable');return r.json();}).then(ingest).catch(function(){api.status=records.length?'ready':'unavailable';return records;}).finally(function(){clearTimeout(timer);pending=null;});
    return pending;
  }
  var api={all:function(){return records;},resolve:resolve,enrich:enrich,merge:merge,matches:matches,rank:rank,load:load,ingest:ingest,norm:norm,status:'loading'};
  root.GPPlayerDirectory=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root.document){load().then(function(){if(typeof root.renderSearch==='function')root.renderSearch();});}
})(typeof window!=='undefined'?window:globalThis);
