#!/usr/bin/env python3
"""Exact copies of published player records; no new statistical calculations."""
import argparse,json,re
from pathlib import Path
from build_player_directory import ROOT,save


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--install',action='store_true');args=parser.parse_args()
    data=json.loads((ROOT/'data/player-recent-games.json').read_text())
    if data.get('ok') is not True or data.get('schemaVersion')!=1:raise ValueError('Invalid full game-log feed')
    groups={i:[] for i in range(64)}
    for p in data['players']:
        if not re.fullmatch(r'00-\d+',p['id']):raise ValueError('Unsupported stable player ID')
        groups[int(re.sub(r'\D','',p['id']))%64].append(p)
    metadata={k:v for k,v in data.items() if k!='players'}
    for i,players in groups.items():save(ROOT/f'data/player-logs/{i:02d}.json',dict(metadata,players=players))
    assert sum(len(x) for x in groups.values())==len(data['players'])
    for i,expected in groups.items():assert json.loads((ROOT/f'data/player-logs/{i:02d}.json').read_text())['players']==expected
    if args.install:
        p=ROOT/'assets/player-game-log.js';s=p.read_text()
        if 'async function loadPlayer(' not in s:
            s=s.replace('  function resolve(d, data) {', '''  async function loadPlayer(d,force) {
    if (window.GPLogShards) {
      try { var shard=await GPLogShards.load(d,force); if(shard)return shard; } catch(e) { /* Keep the complete-feed fallback. */ }
    }
    return load(force);
  }
  function resolve(d, data) {''',1)
        s=s.replace('data=await load(false);','data=await loadPlayer(d,false);')
        s=s.replace('Promise.all([load(force), window.GPPlayerDirectory','Promise.all([loadPlayer(d,force), window.GPPlayerDirectory')
        p.write_text(s)
        tag='<script src="./assets/player-log-shards.js?v=20261105-players1" defer></script>'
        for name in ['index.html','pick-tracker.html','projection-trial.html','projections-2026.html','team.html']:
            p=ROOT/name;s=p.read_text()
            if tag not in s:s=s.replace('</head>',tag+'\n</head>',1)
            p.write_text(s)
        test=ROOT/'scripts/check_player_directory.py'
        s=test.read_text().replace("if rel=='data/homepage-snapshot.json':", "if rel in ['data/homepage-snapshot.json','data/player-recent-games.json']:")
        s=s.replace("'Published local statistics; external feeds blocked'", "'Published local statistics; external feeds and full game-log download blocked'")
        test.write_text(s)
    sizes=[(ROOT/f'data/player-logs/{i:02d}.json').stat().st_size for i in groups]
    print(json.dumps({'segments':len(groups),'players':len(data['players']),'largestSegmentBytes':max(sizes),'fullFeedBytes':(ROOT/'data/player-recent-games.json').stat().st_size}))
if __name__=='__main__':main()
