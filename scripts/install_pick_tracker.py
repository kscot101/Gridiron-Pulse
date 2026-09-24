"""Add navigation to the read-only pick tracker; do not edit forecasts or models."""
import re
from pathlib import Path

for name in ('index.html', 'projection-trial.html'):
    path = Path(name)
    page = path.read_text(encoding='utf-8')
    before = re.findall(r'<script\b[^>]*>.*?</script>', page, flags=re.S | re.I)
    if 'id="gp-pick-tracker-link"' not in page:
        if name == 'index.html':
            anchor = '<div class="hero-actions">'
            link = '<a id="gp-pick-tracker-link" class="secondary gp-exact-link" href="pick-tracker.html">Pick Tracker / By Position</a>'
        else:
            anchor = '<nav aria-label="Main navigation">'
            link = '<a id="gp-pick-tracker-link" href="pick-tracker.html">Pick Tracker</a>'
        if page.count(anchor) != 1:
            raise RuntimeError('Missing or ambiguous navigation hook in ' + name)
        page = page.replace(anchor, anchor + '\n' + link, 1)
    assert page.count('id="gp-pick-tracker-link"') == 1
    assert before == re.findall(r'<script\b[^>]*>.*?</script>', page, flags=re.S | re.I)
    path.write_text(page, encoding='utf-8')
print('Tracker links installed. Existing app scripts and data files unchanged.')
