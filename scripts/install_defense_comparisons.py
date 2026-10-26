"""Idempotently connect comparison components. Do not change model/data logic."""
from pathlib import Path
import re
import subprocess
import tempfile

VERSION = '20261026-defense1'
PAGES = ['index.html','projections-2026.html','projection-trial.html','pick-tracker.html']
for name in PAGES:
    p = Path(name); text = p.read_text()
    for ext in ('css','js'):
        if 'assets/matchup-comparisons.' + ext not in text:
            tag = (f'<link rel="stylesheet" href="./assets/matchup-comparisons.css?v={VERSION}">'
                   if ext == 'css' else f'<script src="./assets/matchup-comparisons.js?v={VERSION}" defer></script>')
            assert '</head>' in text
            text = text.replace('</head>',tag+'\n</head>',1)
    text = re.sub(r'(player-game-log\.js\?v=)[^"\']+',r'\g<1>20261026-bars1',text)
    if name == 'index.html':
        hook = '      if (!teamMode) GPPlayerStats.attach(entity, document.getElementById("detail-body"));'
        if 'GPMatchupComparisons.mountTeam(entity' not in text:
            assert text.count(hook) == 1, 'Team profile attach anchor changed'
            text = text.replace(hook, hook+'\n      else if (window.GPMatchupComparisons) GPMatchupComparisons.mountTeam(entity, document.getElementById("detail-body"));',1)
        if 'id="gp-team-defense-link"' not in text:
            assert '<div class="hero-actions">' in text
            text = text.replace('<div class="hero-actions">','<div class="hero-actions">\n<a id="gp-team-defense-link" class="secondary gp-exact-link" href="team.html">Team Defense</a>',1)
    for source in re.findall(r'<script\b[^>]*>(.*?)</script>',text,flags=re.S|re.I):
        if not source.strip(): continue
        with tempfile.NamedTemporaryFile(mode='w',suffix='.js') as f:
            f.write(source); f.flush(); subprocess.run(['node','--check',f.name],check=True)
    p.write_text(text)
p=Path('assets/player-game-log.js');text=p.read_text()
old='  async function resolvedH2HOpponent(d) {\n    return h2hOpponent(d) || await scoreboardOpponent(d);\n  }'
if 'GPMatchupComparisons.resolveOpponent' not in text:
    assert old in text
    text=text.replace(old,'''  async function resolvedH2HOpponent(d) {
    if (window.GPMatchupComparisons) {
      try { var verified = await GPMatchupComparisons.resolveOpponent(d); if (verified) return verified; } catch (e) {}
    }
    return h2hOpponent(d) || await scoreboardOpponent(d);
  }''',1)
if 'GPMatchupComparisons.mountPlayer(section' not in text:
    start=text.index('  function renderH2H(')
    idx=text.index('    section.hidden=false;',start)+len('    section.hidden=false;')
    text=text[:idx]+'''
    if (window.GPMatchupComparisons) {
      Promise.resolve().then(function() {
        if (section.isConnected) GPMatchupComparisons.mountPlayer(section,d,result);
      });
    }'''+text[idx:]
p.write_text(text)
subprocess.run(['node','--check',str(p)],check=True)
for name in ['scripts/install-player-game-logs.py','.github/workflows/verify-player-h2h.yml']:
    p=Path(name)
    if p.exists():
        text=p.read_text();text=re.sub(r'(player-game-log\.js\?v=)[^"\'<>\s]+',r'\g<1>20261026-bars1',text);p.write_text(text)
print('Player bars, team profiles and dedicated team page connected; prediction engines untouched.')
