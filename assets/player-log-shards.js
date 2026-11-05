/* Same published records, divided into small same-origin downloads. */
(function(root){
  'use strict';
  var base=new URL('../data/player-logs/',document.currentScript.src),cache=new Map(),inflight=new Map();
  function arr(x){return Array.isArray(x)?x:[];}
  function norm(x){return String(x||'').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b/g,'').replace(/[^a-z0-9]/g,'');}
  function index(d){
    if(!d||d.ok!==true||d.schemaVersion!==1||!Array.isArray(d.players))throw Error('Invalid game-log segment');
    d.byId=new Map();d.byEspn=new Map();d.byName=new Map();
    d.players.forEach(function(p){
      d.byId.set(String(p.id),p);if(p.espnId)d.byEspn.set(String(p.espnId),p);
      Array.from(new Set([p.name].concat(arr(p.aliases)).map(norm))).forEach(function(n){var group=d.byName.get(n)||[];group.push(p);d.byName.set(n,group);});
    });return d;
  }
  async function load(player,force){
    if(root.GPPlayerDirectory){await root.GPPlayerDirectory.load();player=root.GPPlayerDirectory.enrich(player);}
    var id=String(player.player_id||player.gsisId||player.id||'');
    if(!/^00-\d+$/.test(id))return null;
    var bucket=String(Number(id.replace(/\D/g,''))%64).padStart(2,'0'),saved=cache.get(bucket);
    if(!force&&saved&&Date.now()-saved.at<900000)return saved.data;
    if(inflight.has(bucket))return inflight.get(bucket);
    var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort();},12000);
    var work=fetch(new URL(bucket+'.json?v='+Math.floor(Date.now()/900000),base),{cache:'no-cache',signal:ctl.signal}).then(function(r){if(!r.ok)throw Error('Game-log segment unavailable');return r.json();}).then(index).then(function(d){cache.set(bucket,{data:d,at:Date.now()});return d;}).finally(function(){clearTimeout(timer);inflight.delete(bucket);});
    inflight.set(bucket,work);return work;
  }
  root.GPLogShards={load:load};
})(window);
