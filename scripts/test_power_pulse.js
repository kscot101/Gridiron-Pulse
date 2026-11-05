'use strict';
const assert=require('node:assert/strict'), fs=require('node:fs');
const api=require('../assets/power-pulse.js');
const source=JSON.parse(fs.readFileSync('data/power-pulse.json','utf8')).rankings;
const now=Date.parse(source.generatedAt)+2*3600000;
const copy=()=>structuredClone(source);
assert.equal(api.usable(source,now),true,'Rankings survive the old 90-minute cutoff');
assert.equal(source.teams.length,32);
for(const [label,edit] of [
 ['future',x=>x.generatedAt=new Date(now+3600000).toISOString()],
 ['expired',x=>x.generatedAt=new Date(now-8*86400000).toISOString()],
 ['wrong season',x=>x.seasonYear-=1],
 ['no teams',x=>x.teams=[]],['no players',x=>x.players=[]],
 ['missing score',x=>x.teams[0].heatScore=null],
 ['bad score',x=>x.players[0].heatScore=NaN],
 ['empty history',x=>x.players[0].recentGames=[]],
 ['empty sample',x=>x.players[0].sampleSize=0],
 ['duplicate identity',x=>x.players.push(x.players[0])],
 ['not available',x=>x.available=false],
 ['future game evidence',x=>x.teams[0].recentGames[0].date=new Date(now+3600000).toISOString()]
]){const value=copy();edit(value);assert.equal(api.usable(value,now),false,label);}
const newer=copy();newer.generatedAt=new Date(now-60000).toISOString();
assert.equal(api.choose([source,newer],now),newer);
const empty=copy();empty.generatedAt=newer.generatedAt;empty.teams=[];
assert.equal(api.choose([source,empty],now),source);
assert.equal(api.choose([source],now+8*86400000),null);
assert.equal(api.units('1',{generatedAt:newer.generatedAt,teams:[{teamId:'1',historical:{active:true},metrics:{offensePulse:null}}]},now),null);
assert.equal(api.units('1',{generatedAt:newer.generatedAt,teams:[{teamId:'1',historical:{active:true},metrics:{offensePulse:0}}]},now).metrics.offensePulse,0);
assert.deepEqual(source,JSON.parse(fs.readFileSync('data/homepage-snapshot.json','utf8')).snapshot.powerRankings,'Exact existing rankings copied, not recalculated');
console.log('20 Power Pulse validity, availability and unchanged-score checks passed.');
