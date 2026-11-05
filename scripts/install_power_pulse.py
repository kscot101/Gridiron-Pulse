#!/usr/bin/env python3
"""Connect the independent ranking mirror without touching picks or model data."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION='20261105-power1'
path=ROOT/'index.html';s=path.read_text()
if 'function powerRankings()' not in s:
    s=s.replace('    function allTeams() {','''    function powerRankings() {
      return window.GPPowerPulse
        ? GPPowerPulse.current(state.snapshot)
        : state.snapshot && state.snapshot.powerRankings;
    }

    function allTeams() {''',1)
    for kind in ('teams','players'):
        old='''        state.snapshot &&
        state.snapshot.powerRankings &&
        state.snapshot.powerRankings.'''+kind
        assert old in s
        s=s.replace(old,'        powerRankings() && powerRankings().'+kind,1)
    s=s.replace('''      var power =
        state.snapshot &&
        state.snapshot.powerRankings;''','''      var power = powerRankings();
      if (window.GPPowerPulse) GPPowerPulse.status(state.snapshot);''',1)
    s=s.replace('''      var history = findHistoricalTeam(teamKey(item));''','''      var history = window.GPPowerPulse
        ? GPPowerPulse.units(item.teamId || teamKey(item), state.historicalOutlook)
        : findHistoricalTeam(teamKey(item));''',1)
    s=s.replace('''      var value = Number(metrics[key]);
      return Number.isFinite(value) ? value : null;''','''      var value = metrics[key];
      return typeof value === "number" && Number.isFinite(value) ? value : null;''',1)
    s=s.replace('''      var rawPositions = list(power && power.positions);''','''      var rawPositions = Array.from(new Set(players.map(function(p) { return p.positionGroup || p.position; }).filter(Boolean)));
      if (state.powerKind === "teams" && state.powerMetric !== "overall" &&
          !teams.some(function(t) { return teamPowerMetricValue(t, state.powerMetric) != null; })) {
        state.powerMetric = "overall";
      }''',1)
    s=s.replace('''              '<button type="button" data-power-metric="' +''','''              '<button type="button" ' +
              (option[0] !== "overall" && !teams.some(function(t) { return teamPowerMetricValue(t, option[0]) != null; })
                ? 'disabled title="These scores are awaiting an update" ' : '') +
              'data-power-metric="' +''',1)
    s=s.replace('''        if (aValue == null) aValue = number(a.heatScore);
        if (bValue == null) bValue = number(b.heatScore);''','''        // Missing unit scores are not overall Heat Scores and are never zeros.
        if (aValue == null && bValue == null) return 0;
        if (aValue == null) return 1;
        if (bValue == null) return -1;''',1)
    s=s.replace('''                ? findHistoricalTeam(entityKey)
                : null;''','''                ? (window.GPPowerPulse ? GPPowerPulse.units(item.teamId || entityKey, state.historicalOutlook) : findHistoricalTeam(entityKey))
                : null;''',1)
    for metric in ('offensePulse','defensePulse','tandemPulse'):
        s=s.replace('historyActive ? Math.round(number(teamMetrics.'+metric+')) : "—"','historyActive && typeof teamMetrics.'+metric+' === "number" ? Math.round(teamMetrics.'+metric+') : "—"')
    s=s.replace('''        <div class="power-position-nav power-team-metric-nav" id="power-team-metric-nav"></div>''','''        <p id="power-feed-status" role="status" aria-live="polite">Loading saved team and player rankings...</p>
        <div class="power-position-nav power-team-metric-nav" id="power-team-metric-nav"></div>''',1)
link='<link rel="stylesheet" href="./assets/power-pulse.css?v='+VERSION+'">'
script='<script src="./assets/power-pulse.js?v='+VERSION+'" defer></script>'
if link not in s:s=s.replace('</head>',link+'\n</head>',1)
if script not in s:s=s.replace('</body>',script+'\n</body>',1)
path.write_text(s)
p=ROOT/'.github/workflows/refresh-homepage-feed.yml';s=p.read_text()
if 'scripts/save_power_pulse.py' not in s:
    s=s.replace("      - 'scripts/refresh_homepage_scores.py'", "      - 'scripts/refresh_homepage_scores.py'\n      - 'scripts/save_power_pulse.py'")
    s=s.replace('      - name: Publish validated scores, mirror and diagnostic status','''      - name: Preserve verified Power Pulse independently of live feed age
        if: always()
        run: python scripts/save_power_pulse.py --fetch-units
      - name: Publish validated scores, mirror and diagnostic status''')
    s=s.replace('data/homepage-scoreboard.json; do','data/homepage-scoreboard.json data/power-pulse.json; do')
    p.write_text(s)
print('Independent Power Pulse loader connected. Model and pick files untouched.')
