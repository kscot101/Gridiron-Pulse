(function (window, document) {
  "use strict";

  // Fan predictions are personal, browser-only choices. They are not model picks.
  var CALLS_KEY = "gridironPulseFanCallsV1";
  var TEAM_KEY = "gridironPulseFeaturedFanTeamV1";
  var activeGameId = "";
  var pendingTeamKey = readText(TEAM_KEY);
  var latestState = null;

  function readText(key) {
    try { return window.localStorage.getItem(key) || ""; }
    catch (error) { return ""; }
  }

  function saveText(key, value) {
    try { window.localStorage.setItem(key, value); return true; }
    catch (error) { return false; }
  }

  function readCalls() {
    try {
      var parsed = JSON.parse(readText(CALLS_KEY) || "{}");
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (error) { return {}; }
  }

  function saveCalls(calls) {
    var recent = Object.keys(calls).sort(function(a, b) {
      return String(calls[b] && calls[b].savedAt || "").localeCompare(String(calls[a] && calls[a].savedAt || ""));
    }).slice(0, 100);
    var trimmed = {};
    recent.forEach(function(key) { trimmed[key] = calls[key]; });
    return saveText(CALLS_KEY, JSON.stringify(trimmed));
  }

  function clean(value) {
    return String(value == null ? "" : value).replace(/[&<>'"]/g, function(char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char];
    });
  }

  function teamKey(team) {
    return String(team && (team.teamId || team.id || team.abbreviation || team.team) || "").toUpperCase();
  }

  function teamName(team) {
    return String(team && (team.displayName || team.teamName || team.name || team.abbreviation || team.team) || "NFL team");
  }

  function isPregame(game) {
    var kickoff = Date.parse(game && game.date);
    return !!(game && game.id != null && game.teams && game.teams.away && game.teams.home &&
      teamKey(game.teams.away) && teamKey(game.teams.home) &&
      game.status && game.status.state === "pre" &&
      Number.isFinite(kickoff) && kickoff > Date.now());
  }

  function nextGames(state) {
    return (Array.isArray(state && state.snapshot && state.snapshot.games) ? state.snapshot.games : [])
      .filter(isPregame)
      .sort(function(a, b) { return Date.parse(a.date) - Date.parse(b.date); })
      .slice(0, 24);
  }

  function nextGame(games) {
    var spotlight = typeof window.spotlightGame === "function" ? window.spotlightGame() : null;
    var picked = games.find(function(game) { return String(game.id) === activeGameId; }) ||
      (spotlight && games.find(function(game) { return String(game.id) === String(spotlight.id); })) ||
      games[0] || null;
    if (picked) activeGameId = String(picked.id);
    else activeGameId = "";
    return picked;
  }

  function dateLabel(date) {
    var parsed = new Date(date);
    return Number.isFinite(parsed.getTime())
      ? new Intl.DateTimeFormat(undefined, {weekday:"short",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).format(parsed)
      : "Kickoff pending";
  }

  function renderCalls(state) {
    var mount = document.getElementById("gp-fan-calls");
    if (!mount) return;
    var games = nextGames(state), game = nextGame(games);
    var callCount = Object.keys(readCalls()).length;
    if (!game) {
      mount.innerHTML =
        '<p class="gp-fan-card-kicker">MAKE THE CALL</p>' +
        '<h3>Pick a winner.</h3>' +
        '<p class="gp-fan-card-copy">No future matchup is available on the verified slate right now. The prediction board opens when games return.</p>' +
        '<p class="gp-fan-micro">' + callCount + ' personal calls saved on this browser</p>';
      return;
    }

    var away = game.teams.away, home = game.teams.home;
    var chosen = readCalls()[String(game.id)];
    var saved = chosen && String(chosen.teamKey || "");
    var options = games.map(function(item) {
      return '<option value="' + clean(item.id) + '"' +
        (String(item.id) === String(game.id) ? ' selected' : '') + '>' +
        clean((item.teams.away.abbreviation || teamName(item.teams.away)) + " @ " +
          (item.teams.home.abbreviation || teamName(item.teams.home)) + " · " + dateLabel(item.date)) +
        '</option>';
    }).join("");

    function pick(team, role) {
      var key = teamKey(team);
      return '<button class="gp-call-choice' + (saved === key ? ' is-picked' : '') +
        '" type="button" data-gp-call="' + clean(key) + '" aria-pressed="' + (saved === key) + '">' +
        '<span class="gp-call-role">' + role + '</span>' +
        '<strong>' + clean(teamName(team)) + '</strong>' +
        '<span class="gp-call-indicator">' + (saved === key ? '✓ Your call' : 'Pick to win →') + '</span>' +
        '</button>';
    }

    mount.innerHTML =
      '<div class="gp-fan-topline"><span class="gp-fan-card-kicker">MAKE THE CALL</span><span class="gp-fan-saved">' +
      callCount + ' saved</span></div>' +
      '<h3>Who takes the win?</h3>' +
      '<label class="gp-fan-field-label" for="gp-call-game">Choose a game</label>' +
      '<select class="gp-fan-select" id="gp-call-game">' + options + '</select>' +
      '<p class="gp-fan-kickoff">' + clean(dateLabel(game.date)) + '</p>' +
      '<div class="gp-call-matchup">' + pick(away, "AWAY") + '<span class="gp-call-versus">VS</span>' + pick(home, "HOME") + '</div>' +
      '<div class="gp-fan-card-foot"><span id="gp-call-status" role="status" aria-live="polite">' +
      (saved ? 'Your prediction is saved. Change it before kickoff.' : 'Choose a winner before kickoff.') +
      '</span><button class="gp-fan-link" type="button" data-game="' + clean(game.id) + '">Game Hub ↗</button></div>';
  }

  function teamOptions() {
    var teams = typeof window.allTeams === "function" ? window.allTeams() : [];
    var seen = {};
    return teams.filter(function(team) {
      var key = teamKey(team);
      if (!key || seen[key]) return false;
      seen[key] = true;
      return true;
    }).sort(function(a, b) { return teamName(a).localeCompare(teamName(b)); });
  }

  function renderTeam(state) {
    var mount = document.getElementById("gp-fan-team");
    if (!mount) return;
    var teams = teamOptions();
    var favorites = state && state.favorites && Array.isArray(state.favorites.teams) ? state.favorites.teams : [];
    var option = teams.find(function(team) { return teamKey(team) === pendingTeamKey; });
    var chosen = option && teamKey(option) || "";
    var followed = chosen && favorites.some(function(team) { return team.key === chosen; });
    mount.innerHTML =
      '<div class="gp-fan-topline"><span class="gp-fan-card-kicker">YOUR TEAM</span><span class="gp-fan-saved">' +
      favorites.length + ' following</span></div>' +
      '<h3>Rep your colors.</h3>' +
      '<p class="gp-fan-card-copy">Choose a team and add it to My Pulse for a shortcut to its form, outlook, and next matchup.</p>' +
      '<label class="gp-fan-field-label" for="gp-fan-team-select">Your team</label>' +
      '<select class="gp-fan-select" id="gp-fan-team-select"' + (!teams.length ? ' disabled' : '') + '>' +
      '<option value="">Select an NFL team</option>' +
      teams.map(function(team) { var key = teamKey(team); return '<option value="' + clean(key) + '"' +
        (key === chosen ? ' selected' : '') + '>' + clean(teamName(team)) + '</option>'; }).join("") +
      '</select>' +
      '<button type="button" class="gp-fan-action" data-gp-save-team' + (!teams.length ? ' disabled' : '') + '>' +
      (followed ? 'Team in My Pulse ✓' : 'Follow this team →') + '</button>' +
      '<div class="gp-fan-card-foot"><span role="status" id="gp-fan-team-status">' +
      (!teams.length ? 'Waiting for a verified team list.' : followed ? 'Already in your watchlist.' : 'Saved to this browser only.') +
      '</span><a class="gp-fan-link" href="#my-pulse">My Pulse ↗</a></div>';
  }

  function renderFocus(state) {
    var mount = document.getElementById("gp-fan-focus");
    if (!mount) return;
    var follows = state && state.favorites && Array.isArray(state.favorites.players) ? state.favorites.players.length : 0;
    mount.innerHTML =
      '<div class="gp-fan-topline"><span class="gp-fan-card-kicker">FIND YOUR EDGE</span><span class="gp-fan-saved">PLAYER EDGE</span></div>' +
      '<h3>Your next deep dive.</h3>' +
      '<p class="gp-fan-card-copy">Skip the scrolling. Jump directly into the type of player matchup you want to study.</p>' +
      '<div class="gp-fan-focus-actions">' +
      '<button type="button" data-gp-focus="qb"><span>Quarterback impact</span><b>↗</b></button>' +
      '<button type="button" data-gp-focus="stars"><span>Top team stars</span><b>↗</b></button>' +
      '<button type="button" data-gp-focus="favorites"><span>Players you follow</span><b>↗</b></button>' +
      '</div>' +
      '<div class="gp-fan-card-foot"><span>' + follows + ' player' + (follows === 1 ? '' : 's') + ' followed</span>' +
      '<a class="gp-fan-link" href="pick-tracker.html">Results tracker ↗</a></div>';
  }

  function render(state) {
    latestState = state || window.state || {};
    renderCalls(latestState);
    renderTeam(latestState);
    renderFocus(latestState);
  }

  function showMessage(message) {
    if (typeof window.toast === "function") window.toast(message);
  }

  function handleClick(event) {
    var call = event.target.closest("[data-gp-call]");
    if (call) {
      var games = nextGames(latestState || window.state || {});
      var game = games.find(function(item) { return String(item.id) === activeGameId; });
      var key = call.getAttribute("data-gp-call");
      if (!game || [teamKey(game.teams.away), teamKey(game.teams.home)].indexOf(key) === -1 || !isPregame(game)) {
        showMessage("This game is no longer open for predictions.");
        render(latestState);
        return;
      }
      var calls = readCalls();
      calls[String(game.id)] = {
        gameId: String(game.id), teamKey: key, savedAt: new Date().toISOString(),
        kickoff: game.date
      };
      if (!saveCalls(calls)) {
        showMessage("Your browser could not save this prediction.");
        return;
      }
      render(latestState);
      showMessage("Your call is saved on this browser.");
      return;
    }

    if (event.target.closest("[data-gp-save-team]")) {
      var choice = document.getElementById("gp-fan-team-select");
      var key = choice && choice.value;
      var team = teamOptions().find(function(candidate) { return teamKey(candidate) === key; });
      if (!team || !key) {
        var note = document.getElementById("gp-fan-team-status");
        if (note) note.textContent = "Choose an NFL team first.";
        return;
      }
      pendingTeamKey = key;
      if (!saveText(TEAM_KEY, key)) showMessage("Your browser could not save the featured team.");
      var follows = latestState && latestState.favorites && Array.isArray(latestState.favorites.teams) ? latestState.favorites.teams : [];
      if (!follows.some(function(saved) { return saved.key === key; }) && typeof window.toggleFavorite === "function") {
        window.toggleFavorite("teams", key); // Existing My Pulse favorite storage and refresh.
      } else render(latestState);
      return;
    }

    var focus = event.target.closest("[data-gp-focus]");
    if (focus) {
      var mode = focus.getAttribute("data-gp-focus");
      var target = document.querySelector('[data-edge="' + mode + '"]');
      if (target) target.click(); // Reuse the site's own Player Edge filters.
      var picks = document.getElementById("player-edge");
      if (picks) picks.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }

  document.addEventListener("click", handleClick);
  document.addEventListener("change", function(event) {
    if (event.target.id === "gp-call-game") {
      activeGameId = event.target.value;
      render(latestState);
    }
    if (event.target.id === "gp-fan-team-select") pendingTeamKey = event.target.value;
  });

  window.GPFanZone = {render: render};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function() { render(window.state); }, {once:true});
  else render(window.state);
})(window, document);
