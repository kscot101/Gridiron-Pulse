"""Install the Sites-tab command-center presentation layer.

This intentionally does not replace data functions, prediction logic, favorites,
player profiles, H2H, projection feeds, or homepage freshness guards.
"""
from pathlib import Path
import re
import subprocess
import tempfile

path = Path("index.html")
page = path.read_text(encoding="utf-8")
link = '<link rel="stylesheet" href="./assets/sites-command-center.css?v=20260924-sites1">'

if link not in page:
    if "</head>" not in page:
        raise RuntimeError("index.html has no closing head tag")
    page = page.replace("</head>", link + "\n</head>", 1)

# Keep the current dynamic Spotlight copy and all live-data IDs intact.
required = [
    'id="spotlight-game"',
    'id="game-grid"',
    'id="edge-grid"',
    'id="live-grid"',
    'id="results-list"',
    'id="favorite-players"',
    'id="detail-overlay"',
    "./assets/homepage-score-source.js",
    "./assets/player-game-log.js",
]
for marker in required:
    if marker not in page:
        raise RuntimeError("Required live feature missing after layout install: " + marker)

# Validate inline JS before publishing.
for source in re.findall(r"<script\b[^>]*>(.*?)</script>", page, flags=re.S | re.I):
    if not source.strip():
        continue
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", encoding="utf-8") as handle:
        handle.write(source)
        handle.flush()
        subprocess.run(["node", "--check", handle.name], check=True)

if page.count(link) != 1:
    raise RuntimeError("Sites stylesheet link must appear exactly once")

path.write_text(page, encoding="utf-8")
print("Sites command-center layout linked; current live functionality preserved.")
