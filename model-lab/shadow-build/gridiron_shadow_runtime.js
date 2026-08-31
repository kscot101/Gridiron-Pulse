// GRIDIRON PULSE — live 2026 projection router + v1.9 build scheduler
// Deploy this code to the existing gridiron-shadow Worker.
// Heavy model work stays in gridiron-pulser builds. This Worker only routes/proxies.

const VERSION = "v1.9-live-router-1.0";
const PULSER_DATA_URL = "https://gridiron-pulser.kadescott97.workers.dev/shadow-data.json";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url = new URL(request.url);

    try {
      if (url.pathname === "/" || url.pathname === "/health") {
        return json({
          ok: true,
          worker: "gridiron-shadow",
          version: VERSION,
          mode: "live-router",
          seasonWorkerBinding: Boolean(env.SEASON_WORKER),
          scheduledBuildHookConfigured: Boolean(env.DEPLOY_HOOK_URL),
          productionSiteCanRead: true,
          endpoints: ["/health", "/projections"],
        });
      }

      if (url.pathname === "/projections") {
        return json(await buildProjectionFeed(env));
      }

      return json({ ok: false, error: "NOT_FOUND" }, 404);
    } catch (error) {
      return json(
        {
          ok: false,
          version: VERSION,
          error: error?.message || String(error),
          failClosedToCurrentWorker: true,
        },
        500,
      );
    }
  },

  async scheduled(event, env, ctx) {
    if (!env.DEPLOY_HOOK_URL) return;
    ctx.waitUntil(triggerPulserBuild(env.DEPLOY_HOOK_URL));
  },
};

async function triggerPulserBuild(hookUrl) {
  const response = await fetch(hookUrl, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Deploy hook failed: ${response.status}`);
  }
}

async function buildProjectionFeed(env) {
  const [seasonResult, shadowResult] = await Promise.all([
    loadSeasonOutlook(env),
    loadShadowData(),
  ]);

  const season = seasonResult.snapshot || {};
  const seasonPlayers = Array.isArray(season.players) ? season.players : [];
  const shadow = shadowResult.payload || {};
  const shadowPlayers = Array.isArray(shadow.players) ? shadow.players : [];
  const week = finite(season.seasonWeek) ?? finite(shadow.requestedWeek) ?? 1;

  const shadowById = new Map();
  const shadowByIdentity = new Map();

  for (const player of shadowPlayers) {
    const id = cleanId(player.playerKey || player.gsisId || player.gsis_id || player.id);
    if (id) shadowById.set(id.toUpperCase(), player);

    const identity = identityKey(player.playerName || player.name, player.position, player.team);
    if (identity) shadowByIdentity.set(identity, player);
  }

  let v19Active = 0;

  const players = seasonPlayers.map((player) => {
    const id = cleanId(
      player.gsisId ||
        player.gsis_id ||
        player.playerKey ||
        player.athleteId ||
        player.id,
    );
    const name = playerName(player);
    const position = playerPosition(player);
    const team = playerTeam(player);
    const officialPrediction = workerProjection(player);

    const candidate =
      (id && shadowById.get(id.toUpperCase())) ||
      shadowByIdentity.get(identityKey(name, position, team)) ||
      null;

    const routedV19 = routeForWeek(position, week) === "v19";
    const candidatePrediction = finite(candidate?.shadowPrediction);
    const candidateReady =
      Boolean(shadow.ready) &&
      routedV19 &&
      candidate &&
      candidatePrediction !== null &&
      String(candidate.shadowSource || "v19").toLowerCase() === "v19";

    if (candidateReady) v19Active += 1;

    return {
      playerKey: id || null,
      playerName: name,
      team,
      position,
      primaryMetric: player.primaryMetric || candidate?.primaryMetric || "",
      route: routeForWeek(position, week),
      activeSource: candidateReady ? "v19" : "worker",
      activePrediction: candidateReady ? candidatePrediction : officialPrediction,
      officialPrediction,
      shadowPrediction: candidatePrediction,
      delta:
        candidatePrediction !== null && officialPrediction !== null
          ? candidatePrediction - officialPrediction
          : null,
      shadowReady: candidateReady,
    };
  });

  return {
    ok: true,
    version: VERSION,
    season: finite(season.seasonYear) ?? 2026,
    seasonWeek: week,
    generatedAt: new Date().toISOString(),
    officialSource: "current-season-worker",
    shadowReady: Boolean(shadow.ready),
    shadowReason: shadow.reason || null,
    shadowGeneratedAt: shadow.generatedAt || null,
    pulserReachable: shadowResult.ok,
    safety: {
      currentWorkerFallback: true,
      onlyValidatedRoutesCanUseV19: true,
    },
    summary: {
      players: players.length,
      v19Active,
      workerActive: players.length - v19Active,
    },
    players,
  };
}

async function loadSeasonOutlook(env) {
  if (!env.SEASON_WORKER) {
    throw new Error("SEASON_WORKER service binding is missing");
  }

  for (const path of ["/season-outlook", "/latest"]) {
    const response = await env.SEASON_WORKER.fetch(
      new Request(`https://season.internal${path}`, {
        headers: { Accept: "application/json" },
      }),
    );

    if (!response.ok) continue;
    const payload = await response.json();

    if (payload?.ok && payload?.seasonOutlook) {
      return { snapshot: payload.seasonOutlook, path };
    }

    if (Array.isArray(payload?.players)) {
      return { snapshot: payload, path };
    }
  }

  throw new Error("Season Worker unavailable through service binding");
}

async function loadShadowData() {
  try {
    const response = await fetch(`${PULSER_DATA_URL}?t=${Date.now()}`, {
      headers: { Accept: "application/json" },
      cf: { cacheTtl: 0 },
    });

    if (!response.ok) {
      return { ok: false, payload: { ready: false, reason: `pulser-${response.status}` } };
    }

    return { ok: true, payload: await response.json() };
  } catch (error) {
    return {
      ok: false,
      payload: { ready: false, reason: error?.message || "pulser-unavailable" },
    };
  }
}

function routeForWeek(position, week) {
  const pos = String(position || "").toUpperCase();
  const w = Number(week) || 1;

  if (w < 4) return "worker";
  if (w < 8) return pos === "RB" || pos === "WR" ? "v19" : "worker";
  if (w < 12) return pos === "WR" || pos === "TE" ? "v19" : "worker";
  return "worker";
}

function playerName(player) {
  return String(
    player?.name ||
      player?.playerName ||
      player?.displayName ||
      player?.fullName ||
      player?.shortName ||
      "Unknown Player",
  );
}

function playerPosition(player) {
  return String(player?.positionGroup || player?.position || player?.pos || "").toUpperCase();
}

function playerTeam(player) {
  let team = player?.team || player?.teamAbbr || player?.teamCode || player?.teamAbbreviation || "";
  if (team && typeof team === "object") {
    team = team.abbreviation || team.abbr || team.code || team.name || "";
  }
  return normalizeTeam(team);
}

function workerProjection(player) {
  const metric = player?.primaryMetric;

  if (metric && player?.projections && typeof player.projections === "object") {
    const parsed = projectionNumber(player.projections[metric]);
    if (parsed !== null) return parsed;
  }

  for (const value of [
    player?.projection,
    player?.projectedTotal,
    player?.seasonProjection,
    player?.seasonTotal,
    player?.projectedSeasonTotal,
  ]) {
    const parsed = projectionNumber(value);
    if (parsed !== null) return parsed;
  }

  return null;
}

function projectionNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;

  if (typeof value === "object") {
    for (const item of [
      value.projection,
      value.projected,
      value.value,
      value.total,
      value.mean,
      value.median,
      value.expected,
      value.projectedTotal,
      value.seasonTotal,
    ]) {
      const parsed = finite(item);
      if (parsed !== null) return parsed;
    }
  }

  return finite(value);
}

function identityKey(name, position, team) {
  const n = normalizeName(name);
  const p = String(position || "").toUpperCase();
  const t = normalizeTeam(team);
  return n && p ? `${n}|${p}|${t}` : "";
}

function normalizeName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, "")
    .replace(/[^a-z0-9]/g, "");
}

function normalizeTeam(value) {
  const team = String(value || "").trim().toUpperCase();
  return { JAC: "JAX", LAR: "LA", STL: "LA", OAK: "LV", SD: "LAC", WSH: "WAS" }[team] || team;
}

function cleanId(value) {
  const text = String(value ?? "").trim();
  return ["", "nan", "none", "null", "na"].includes(text.toLowerCase()) ? "" : text;
}

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      ...CORS,
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
