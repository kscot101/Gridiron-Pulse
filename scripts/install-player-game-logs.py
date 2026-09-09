#!/usr/bin/env python3
"""Install the shared player popup without changing existing models or page layouts."""
from pathlib import Path
import json
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / 'assets/player-game-logs.js'
PAGES = ['index.html', 'projections-2026.html', 'projections-2026-build-c.html']
TAG = '<script src="./assets/player-game-logs.js?v=20260909-1" defer></script>'


def get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'GridironPulse/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    subprocess.run(['node', '--check', str(ASSET)], check=True)
    # Exercise the exact parser used by the browser against real source responses.
    samples = []
    for athlete, position in [('3139477', 'QB'), ('3117251', 'RB'), ('3121023', 'TE'), ('3133487', 'DEF')]:
        url = 'https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/' + athlete + '/gamelog?season=2025'
        samples.append({'id': athlete, 'position': position, 'data': get_json(url)})
    check = r'''
const fs=require('node:fs');
const assert=require('node:assert/strict');
const api=require(process.argv[1]);
const samples=JSON.parse(fs.readFileSync(0,'utf8'));
for(const sample of samples){
  const rows=api.parseGameLog(sample.data,2025);
  assert(rows.length>=3, 'Expected recent source games for '+sample.id);
  const columns=api.columns(sample.position,rows);
  assert(columns.length>=3, 'Expected position-specific source stats for '+sample.position);
  assert(rows.every(r=>r.timestamp<=Date.now()));
  assert(rows.every(r=>r.phase!=='Preseason'));
  console.log('LIVE SOURCE PASS',sample.position,sample.id,rows.length,'games;',columns.map(x=>x.label).join(', '));
}
assert.equal(api.num(null),null);assert.equal(api.num(''),null);assert.equal(api.num('-'),null);assert.equal(api.num('0'),0);
assert.equal(api.athleteId({player_id:'00-0033873'}),'');assert.equal(api.athleteId({id:'12'}),'');
console.log('PASS: missing statistics stay missing; GSIS and team IDs are not used as athlete IDs.');
'''
    subprocess.run(['node', '-e', check, str(ASSET)], input=json.dumps(samples), text=True, check=True)
    try:
        payload = get_json('https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook')
        players = payload.get('seasonOutlook', {}).get('players', [])
        verified = [p for p in players if re.fullmatch(r'[1-9][0-9]{3,9}', str(p.get('athleteId') or p.get('id') or ''))]
        print('Season directory:', len(players), 'players;', len(verified), 'numeric athlete IDs')
        print('Directory sample:', json.dumps([{k:p.get(k) for k in ['name','playerName','athleteId','id','position','positionGroup','team']} for p in players[:3]]))
    except Exception as error:
        print('Directory check unavailable:', error)

    updated = {}
    for name in PAGES:
        path = ROOT / name
        page = path.read_text(encoding='utf-8')
        if 'assets/player-game-logs.js' not in page:
            if '</body>' not in page:
                raise RuntimeError('Missing body closing tag: ' + name)
            page = page.replace('</body>', TAG + '\n</body>', 1)
        assert page.count('assets/player-game-logs.js') == 1
        # Check existing inline scripts as well as the added shared asset before writing.
        for script in re.findall(r'<script\b[^>]*>(.*?)</script>', page, flags=re.S | re.I):
            if not script.strip():
                continue
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', encoding='utf-8') as handle:
                handle.write(script)
                handle.flush()
                subprocess.run(['node', '--check', handle.name], check=True)
        updated[path] = page
    for path, page in updated.items():
        path.write_text(page, encoding='utf-8')
        print('Enabled clickable game logs:', path.name)


if __name__ == '__main__':
    main()
