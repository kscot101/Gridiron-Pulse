"""Move the existing picks section up; preserve all sports data and inline app code."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

ROOT = Path('.')
KEY = '20261005-picks-front1'
INDEX = ROOT / 'index.html'
NAV = ROOT / 'assets/home-sections.js'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inline_scripts(page):
    return re.findall(r'<script\b[^>]*>(.*?)</script>', page, flags=re.S | re.I)


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected exactly one layout anchor: ' + old[:90])
    return text.replace(old, new, 1)


protected_paths = [p for p in (ROOT / 'data').rglob('*') if p.is_file()]
protected_paths += [ROOT / name for name in (
    'assets/player-game-log.js', 'assets/player-game-log.css',
    'assets/homepage-feed.js', 'assets/homepage-score-source.js',
    'assets/projection-trial.js', 'assets/projection-safety.js',
    'assets/sites-command-center.css', 'assets/home-sections.css',
    'pick-tracker.html', 'projections-2026.html', 'projection-trial.html')]
protected = {str(p): digest(p) for p in protected_paths}
original = INDEX.read_text(encoding='utf-8')
nav_original = NAV.read_text(encoding='utf-8')
base_blobs = {str(p): subprocess.check_output(['git', 'hash-object', str(p)], text=True).strip() for p in (INDEX, NAV)}
page = original
if KEY not in page:
    found = re.search(r'    <section class="section" id="player-edge">.*?</section>', page, flags=re.S)
    if not found:
        raise RuntimeError('The original Player Edge section could not be located')
    block = found.group(0)
    page = page[:found.start()] + page[found.end():]
    block = once(block, '<section class="section" id="player-edge">', '<section class="section gp-featured-picks" id="player-edge" aria-labelledby="daily-picks-heading">')
    block = once(block, '<p class="eyebrow">Pregame intelligence</p>', '<p class="eyebrow">PLAYER EDGE / CURRENT SLATE</p>')
    block = once(block, '<h2>Player Edge</h2>', '<h2 id="daily-picks-heading">Picks of the Day</h2>')
    block = once(block,
        'Each game tracks both quarterbacks and one non-QB team star using\n            opponent defense, current form, team scheme and similar-position\n            history.',
        'Current-slate picks, projected stats and matchup signals. Click a\n            player for recent games and head-to-head history, or visit the\n            <a class="gp-picks-tracker" href="pick-tracker.html">Pick Tracker for saved results</a>.')
    page = once(page, '    <section class="section soft" id="my-pulse">', block + '\n\n    <section class="section soft" id="my-pulse">')

    # Move the existing sidebar entry, rather than creating a second picks section.
    rail_old = '      <button class="home-section-link" data-home-section="player-edge" data-scroll="player-edge">Player Edge</button>\n'
    page = once(page, rail_old, '')
    rail_spotlight = '      <button class="home-section-link" data-home-section="top" data-scroll="top" aria-current="location">Spotlight</button>\n'
    rail_new = '      <button class="home-section-link gp-picks-rail-link" data-home-section="player-edge" data-scroll="player-edge">Picks of the Day</button>\n'
    page = once(page, rail_spotlight, rail_spotlight + rail_new)
    page = once(page, '<button data-scroll="player-edge">Player Edge</button>', '<button data-scroll="player-edge">Daily Picks</button>')

    # A persistent header shortcut stays available when the desktop nav disappears.
    search = re.search(r'      <button class="search-button" id="open-search".*?</button>', page, flags=re.S)
    if not search:
        raise RuntimeError('Search control not found')
    tools = '<div class="gp-header-tools">\n        <a id="gp-picks-shortcut" class="gp-picks-shortcut" href="#player-edge" aria-label="Go to Picks of the Day">Picks</a>\n' + search.group(0) + '\n      </div>'
    page = page[:search.start()] + '      ' + tools + page[search.end():]

    hero_old = '              <button class="secondary" data-scroll="player-edge">\n                Open Player Edge\n              </button>'
    page = once(page, hero_old, '')
    page = once(page, '<div class="hero-actions">', '<div class="hero-actions">\n              <a class="primary gp-hero-picks" href="#player-edge">See Today\'s Picks</a>')
    page = once(page, '<button class="primary" data-scroll="games">', '<button class="secondary" data-scroll="games">')

    style = '''
<style id="gp-picks-prominence-style" data-version="20261005-picks-front1">
/* Existing picks, now easy to find. Scoped to the homepage navigation. */
.gp-header-tools{display:flex;align-items:center;justify-content:flex-end;gap:10px;justify-self:end;min-width:0}
.gp-header-tools .search-button{margin-left:0}
.gp-picks-shortcut{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 15px;border:1px solid #c9ff32;background:#c9ff32;color:#07100d!important;-webkit-text-fill-color:#07100d!important;font:850 13px/1.1 var(--sans);text-decoration:none;white-space:nowrap}
.gp-picks-shortcut:hover,.gp-hero-picks:hover{filter:brightness(1.06)}
.gp-hero-picks{display:inline-flex;align-items:center;justify-content:center;text-decoration:none}
#player-edge.gp-featured-picks{border-top:3px solid #c9ff32;scroll-margin-top:84px}
#player-edge .eyebrow{color:#315b45}
#player-edge .gp-picks-tracker{color:#163c27;text-underline-offset:3px;font-weight:800}
.home-section-link.gp-picks-rail-link:not([aria-current="location"]){border-color:rgba(201,255,50,.6);color:#e9ffb0}
.gp-picks-shortcut:focus-visible,.gp-hero-picks:focus-visible,.gp-picks-tracker:focus-visible{outline:3px solid #238751;outline-offset:3px}
@media(max-width:1180px){.topbar-inner{grid-template-columns:minmax(0,1fr) auto;gap:12px}.gp-header-tools{gap:8px}}
@media(max-width:760px){.gp-header-tools .search-button{width:40px;min-height:42px;padding:0}.gp-picks-shortcut{padding:0 12px}.brand{min-width:0;width:auto}.brand>span:last-child{min-width:0}.brand-mark{flex-shrink:0}}
@media(max-width:420px){.topbar-inner{gap:8px}.brand{gap:8px}.brand strong{font-size:12px;white-space:normal;line-height:1.15}.brand small{font-size:7px;letter-spacing:.09em}.gp-header-tools{gap:6px}.gp-picks-shortcut{padding:0 10px;font-size:12px}.gp-header-tools .search-button{width:36px}}
</style>
'''
    page = once(page, '</head>', style + '</head>')
    page = once(page, 'home-sections.js?v=20261002-sites-v8', 'home-sections.js?v=' + KEY)

    old_order = "var ids=['top','my-pulse','season-outlook','availability','games','player-edge','live','power-pulse','model-record','results'];"
    new_order = "var ids=['top','player-edge','my-pulse','season-outlook','availability','games','live','power-pulse','model-record','results'];"
    nav = once(nav_original, old_order, new_order)
    if inline_scripts(page) != inline_scripts(original):
        raise RuntimeError('Inline app logic changed during a presentation-only migration')
    if page.count('id="edge-grid"') != 1 or page.count('id="player-edge"') != 1:
        raise RuntimeError('Duplicate picks grid/section')
    INDEX.write_text(page, encoding='utf-8')
    NAV.write_text(nav, encoding='utf-8')

for name, expected in protected.items():
    if digest(Path(name)) != expected:
        raise RuntimeError('Protected file changed: ' + name)

report = {
    'buildKey': KEY,
    'baseBlobs': base_blobs,
    'inlineAppLogicUnchanged': inline_scripts(page) == inline_scripts(original),
    'protectedFilesUnchanged': len(protected),
    'picksCopied': False,
    'picksSectionCount': page.count('id="player-edge"'),
    'sectionOrder': re.findall(r'<section\b[^>]*\bid="([^"]+)"', page.split('<main>', 1)[1].split('</main>', 1)[0]),
    'scope': 'Placement and navigation only; current-slate selection, forecasts, freshness checks, saved picks and profiles unchanged.'
}
Path('home-picks-layout-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
