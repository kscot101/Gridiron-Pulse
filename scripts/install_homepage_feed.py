"""Install homepage freshness guards without replacing the site's layout/model."""
from pathlib import Path
import re
import subprocess
import tempfile

path = Path('index.html')
page = path.read_text(encoding='utf-8')
marker = '<!-- HOMEPAGE FEED SAFETY 20260924 -->'
if marker not in page:
    def replace_function(name, body):
        global page
        pattern = r'    (?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{.*?(?=\n    (?:async )?function )'
        page, count = re.subn(pattern, lambda match: body.rstrip()+'\n', page, count=1, flags=re.S)
        if count != 1:
            raise RuntimeError('Missing unique homepage hook: '+name)

    replace_function('loadSnapshot', '''    async function loadSnapshot(silent) {
      try {
        state.snapshot = await GPHomepageFeed.load(AGENT_URL);
        renderAll();
        if (!silent) toast(state.snapshot.feedStatus.analysisCurrent
          ? "Games and analysis refreshed"
          : "Current game data loaded; analysis awaiting refresh");
      } catch (error) {
        state.snapshot = GPHomepageFeed.compose(null, [], null, null, Date.now());
        renderAll();
        document.getElementById("connection-label").textContent = "Game feed temporarily unavailable";
        if (!silent) toast("Game data is unavailable. Old games are not presented as live.");
      } finally {
        scheduleRefresh();
      }
    }
''')
    replace_function('spotlightGame', '''    function spotlightGame() {
      return GPHomepageFeed.pickSpotlight(allGames(), spotlightGameScore, Date.now());
    }
''')
    replace_function('findGame', '''    function findGame(id) {
      return allGames().concat(list(state.snapshot && state.snapshot.recentGames))
        .find(function(game) { return String(game.id) === String(id); });
    }
''')
    replace_function('renderResults', '''    function renderResults() {
      GPHomepageFeed.renderResults(state.snapshot);
    }
''')
    anchor = '      renderModel();\n      renderResults();'
    if page.count(anchor) != 1:
        raise RuntimeError('Homepage render hook is ambiguous')
    page = page.replace(anchor, anchor+'\n      GPHomepageFeed.paint(state.snapshot);', 1)
    page = page.replace('</head>', marker+'\n<script src="./assets/homepage-feed.js?v=20260924a"></script>\n<style>\n#homepage-feed-status{margin:0 0 18px;padding:12px 14px;border:1px solid rgba(255,255,255,.2);border-radius:8px;background:rgba(5,13,10,.9);color:#e9f1ed;font-size:12px;line-height:1.6;overflow-wrap:anywhere}#homepage-feed-status[data-mode="scores-only"],#homepage-feed-status[data-mode="unavailable"]{border-left:3px solid #ffaf70}#model-feed-status{color:rgba(255,255,255,.7);line-height:1.6;font-size:12px;margin-bottom:16px}#results-list details summary{padding:14px 0}#results-list>.result-row{grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto}@media(max-width:600px){#results-list>.result-row{grid-template-columns:1fr}#results-list .actual{overflow-wrap:anywhere}}\n</style>\n</head>',1)
    hero = '<div class="shell hero-inner">'
    if page.count(hero) != 1:
        raise RuntimeError('Missing unique hero container')
    page = page.replace(hero, hero+'\n        <div id="homepage-feed-status" role="status">Checking the current game slate...</div>',1)
    model = '<div class="model-overview" id="model-overview"></div>'
    if model not in page:
        raise RuntimeError('Missing model record container')
    page = page.replace(model, '<div id="model-feed-status"></div>\n        '+model,1)
    page = page.replace('Final scores and locked Player Edge outcomes post automatically\n            after each game.', 'Recent final scores and originally locked Player Edge outcomes are\n            shown separately. Older model results stay in the history section.',1)
    page = page.replace('No active Player Edge spotlight is attached to this profile.', 'No current Player Edge spotlight is attached to this profile.',1)

transport = '<script src="./assets/homepage-score-source.js?v=20260924a"></script>'
if transport not in page:
    page = page.replace('</head>', transport+'\n</head>',1)
responsive = '<link rel="stylesheet" href="./assets/homepage-responsive.css?v=20260924a">'
if responsive not in page:
    page = page.replace('</head>', responsive+'\n</head>',1)

# Validate every inline script before touching the production file.
for i, source in enumerate(re.findall(r'<script\b[^>]*>(.*?)</script>',page,flags=re.S|re.I)):
    if not source.strip():
        continue
    with tempfile.NamedTemporaryFile(suffix='.js', mode='w', encoding='utf-8') as test:
        test.write(source)
        test.flush()
        subprocess.run(['node','--check',test.name],check=True)
assert page.count(marker)==1
assert page.count(transport)==1
assert page.count(responsive)==1
path.write_text(page,encoding='utf-8')
print('Homepage data safety installed; existing sections and projection code retained.')
