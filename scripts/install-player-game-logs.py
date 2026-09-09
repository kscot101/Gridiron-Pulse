#!/usr/bin/env python3
"""Connect shared recent-game UI without changing projection math or layouts."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CSS = '  <link rel="stylesheet" href="./assets/player-game-log.css?v=20260909a">\n'
JS = '  <script src="./assets/player-game-log.js?v=20260909a"></script>\n'


def connect(page):
    if 'href="./assets/player-game-log.css' not in page:
        page = page.replace('</head>', CSS + '</head>', 1)
    if 'src="./assets/player-game-log.js' not in page:
        page = page.replace('<script>', JS + '<script>', 1)
    return page


def install():
    path = ROOT / 'index.html'
    page = connect(path.read_text(encoding='utf-8'))
    start = page.index('    function openProfile(kind, key) {')
    end = page.index('    function openSearch()', start)
    profile = page[start:end]
    if 'GPPlayerStats.attach' not in profile:
        target = '      openOverlay("detail-overlay");'
        assert profile.count(target) == 1
        profile = profile.replace(target, '      if (!teamMode) GPPlayerStats.attach(entity, document.getElementById("detail-body"));\n\n' + target, 1)
        page = page[:start] + profile + page[end:]
    # The spotlight's newly added name labels need structured links, too.
    target = 'escapeHtml(text(pick.name, "Player"))'
    page = page.replace(target, 'GPPlayerStats.link(pick, text(pick.name, "Player"))')
    # Link the source name with its identity rather than guessing from prose.
    start = page.index('    function spotlightSignalItems(')
    end = page.index('    function spotlightTeamMarkup(', start)
    piece = page[start:end]
    if 'sourcePlayer: pick,' not in piece:
        piece = piece.replace('          items.push({\n', '          items.push({\n            sourcePlayer: pick,\n', 1)
        page = page[:start] + piece + page[end:]
    old = 'escapeHtml(signal.source)'
    new = '(signal.sourcePlayer ? GPPlayerStats.link(signal.sourcePlayer) + escapeHtml(" / " + text(signal.sourcePlayer.team, "NFL") + " / Edge " + number(signal.sourcePlayer.score, "")) : escapeHtml(signal.source))'
    if 'signal.sourcePlayer ? GPPlayerStats.link' not in page:
        page = page.replace(old, new, 1)
    assert 'Why this game surfaced</strong>' not in page
    assert 'GPPlayerStats.attach(entity' in page
    assert 'id="spotlight-game"' in page
    assert 'playerProjectionMarkup(pick)' in page
    path.write_text(page, encoding='utf-8')
    for name in ('projections-2026.html',):
        path = ROOT / name
        page = connect(path.read_text(encoding='utf-8'))
        old = "<div class=\"name\">'+E(r.name)+'</div>"
        new = "<div class=\"name\">'+GPPlayerStats.link(r,r.name)+'</div>"
        if new not in page:
            assert old in page, 'Projection card name anchor changed'
            page = page.replace(old, new, 1)
        path.write_text(page, encoding='utf-8')
    # Validate every inline script, not just the newly added asset.
    for name in ('index.html', 'projections-2026.html'):
        page = (ROOT / name).read_text(encoding='utf-8')
        for code in re.findall(r'<script>([\s\S]*?)</script>', page):
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', encoding='utf-8') as tmp:
                tmp.write(code); tmp.flush()
                subprocess.run(['node', '--check', tmp.name], check=True)
    subprocess.run(['node', '--check', str(ROOT / 'assets/player-game-log.js')], check=True)
    print('Player links and recent-game profiles installed; JavaScript validation passed.')


if __name__ == '__main__':
    install()
