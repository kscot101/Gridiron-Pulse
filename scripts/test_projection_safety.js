'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const safety=require('../assets/projection-safety.js');
let checks=0;
function check(fn){fn();checks++;}
for(const v of [null,undefined,'','  ',false,true,NaN,Infinity,{},[],'Unavailable'])check(()=>assert.equal(safety.number(v),null));
for(const v of [0,'0',0.0])check(()=>assert.equal(safety.number(v),0));
const now=Date.parse('2026-09-11T15:00:00Z');
check(()=>assert.equal(safety.fresh({generatedAt:'2026-09-11T14:00:00Z'},now),true));
check(()=>assert.equal(safety.fresh({generatedAt:'2026-09-04T14:00:00Z'},now),false));
check(()=>assert.equal(safety.fresh({generatedAt:'2026-09-11T14:00:00Z',sourceGeneratedAt:'2026-09-04T14:00:00Z'},now),false));
check(()=>assert.equal(safety.fresh({generatedAt:'2026-09-12T14:00:00Z'},now),false));
check(()=>assert.equal(safety.fresh({},now),false));
const game={id:'123',date:'2026-09-13T17:00:00Z',status:{state:'pre'},teams:{away:{abbreviation:'DAL'},home:{abbreviation:'NYG'}}};
const pick={name:'Test Player',team:'DAL',gameId:'123'};
const row={nextGameId:'123',nextOpponent:'NYG',nextGameKickoff:game.date};
check(()=>assert.equal(safety.forGame(row,pick,[game],[],now),true));
check(()=>assert.equal(safety.forGame({...row,nextGameId:'456'},pick,[game],[],now),false));
check(()=>assert.equal(safety.forGame({...row,nextOpponent:'PHI'},pick,[game],[],now),false));
check(()=>assert.equal(safety.forGame(row,pick,[{...game,status:{state:'post'}}],[],now),false));
check(()=>assert.equal(safety.forGame(row,pick,[game],[],Date.parse('2026-09-14T00:00:00Z')),false));
check(()=>assert.equal(safety.forGame(null,pick,[game],[],now),false));
for(const file of ['index.html','projections-2026.html']){
  const html=fs.readFileSync(file,'utf8');
  const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
  for(const script of scripts)check(()=>new vm.Script(script[1],{filename:file}));
  check(()=>assert.ok(html.includes('projection-feed-status')));
  check(()=>assert.ok(html.includes('assets/projection-safety.js')));
  const parser=file==='index.html'?html.match(/function finiteProjection\(value\) \{[\s\S]*?\n    \}/):html.match(/function N\(v\)\{[^}]+\}/);
  check(()=>assert.ok(parser,'Actual page parser not found'));
  const context={GPProjectionSafety:safety};vm.createContext(context);vm.runInContext(parser[0],context);
  const f=context.finiteProjection||context.N;
  check(()=>assert.equal(f(null),null));check(()=>assert.equal(f(' '),null));check(()=>assert.equal(f(0),0));
  check(()=>assert.ok(html.includes('player-game-logs.js'),'Player popup integration missing'));
  if(file==='projections-2026.html')check(()=>assert.ok(html.includes('data-proj-follow'),'Favorites must remain intact'));
}
console.log('PASS:',checks,'JavaScript/parser/freshness/matchup checks');
