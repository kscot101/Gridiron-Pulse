"""Install the wide weekly renderer. Idempotent; no feed or forecast changes."""
from pathlib import Path
import re

RELEASE = '20261116-widebars1'
PAGES = ('index.html', 'projections-2026.html', 'projection-trial.html', 'pick-tracker.html')

path = Path('assets/matchup-comparisons.js')
source = path.read_text(encoding='utf-8')
anchor = '  function renderTripleChart(rows, seasonValue, h2hValue, metricLabel, code, compatible) {'
bridge = '\n    if (root.GPWeeklyChart) return root.GPWeeklyChart.render(rows, seasonValue, h2hValue, metricLabel, code, compatible);'
if anchor not in source:
    raise RuntimeError('Existing weekly chart renderer changed; inspect before installing')
if bridge not in source:
    source = source.replace(anchor, anchor + bridge, 1)
    path.write_text(source, encoding='utf-8')

for name in PAGES:
    path = Path(name)
    source = path.read_text(encoding='utf-8')
    source, count = re.subn(r'matchup-comparisons\.js\?v=[^"\s<>]+',
                          'matchup-comparisons.js?v=' + RELEASE, source)
    if count != 1:
        raise RuntimeError(f'{name}: expected one existing comparison script, found {count}')
    new_script = '<script src="./assets/player-weekly-chart.js?v=' + RELEASE + '" defer></script>'
    new_css = '<link rel="stylesheet" href="./assets/player-weekly-chart.css?v=' + RELEASE + '">'
    if 'assets/player-weekly-chart.js' not in source:
        pattern = r'(<script\b[^>]*src="[^"<>]*assets/matchup-comparisons\.js[^"<>]*"[^>]*></script>)'
        source, count = re.subn(pattern, lambda m: new_script + '\n' + m.group(1), source, count=1)
        if count != 1:
            raise RuntimeError(f'{name}: comparison script insertion point missing')
    if 'assets/player-weekly-chart.css' not in source:
        pattern = r'(<link\b[^>]*href="[^"<>]*assets/player-comparison-v2\.css[^"<>]*"[^>]*>)'
        source, count = re.subn(pattern, lambda m: m.group(1) + '\n' + new_css, source, count=1)
        if count != 1:
            raise RuntimeError(f'{name}: player stylesheet insertion point missing')
    assert source.index('assets/player-weekly-chart.js') < source.index('assets/matchup-comparisons.js'), name
    assert source.count('assets/player-weekly-chart.js') == 1, name
    assert source.count('assets/player-weekly-chart.css') == 1, name
    path.write_text(source, encoding='utf-8')

path = Path('.github/workflows/verify-defense-publication.yml')
source = path.read_text(encoding='utf-8')
source = re.sub(r'matchup-comparisons\.js\?v=[^\s\'\"]+',
                'matchup-comparisons.js?v=' + RELEASE, source)
anchor = "for path in ['team.html',"
if "'assets/player-weekly-chart.js','assets/player-weekly-chart.css'" not in source:
    if anchor not in source:
        raise RuntimeError('Publication verifier file list changed')
    source = source.replace(anchor, "for path in ['assets/player-weekly-chart.js','assets/player-weekly-chart.css','team.html',", 1)
if "      - 'assets/player-weekly-chart.js'" not in source:
    source = source.replace("      - 'assets/matchup-comparisons.js'", "      - 'assets/matchup-comparisons.js'\n      - 'assets/player-weekly-chart.js'\n      - 'assets/player-weekly-chart.css'", 1)
path.write_text(source, encoding='utf-8')
print('Wide weekly renderer linked on all four player pages. Statistical functions unchanged.')
