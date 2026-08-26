// GRIDIRON PULSE v1.9j live shadow candidate adapter.
// Research/shadow only: the current Season Worker remains the official source.

export const SHADOW_MODEL_VERSION = "v1.9j";
export const SHADOW_SEASON = 2026;

const ROUTES = Object.freeze({
  QB: Object.freeze({ 4: "worker", 8: "worker", 12: "worker" }),
  RB: Object.freeze({ 4: "v19", 8: "worker", 12: "worker" }),
  TE: Object.freeze({ 4: "worker", 8: "v19", 12: "worker" }),
  WR: Object.freeze({ 4: "v19", 8: "v19", 12: "worker" }),
});

export function checkpointForWeek(week) {
  const value = Number(week);
  if (!Number.isFinite(value) || value < 4) return null;
  if (value < 8) return 4;
  if (value < 12) return 8;
  return 12;
}

export function routeForWeek(position, week) {
  const normalizedPosition = String(position || "").trim().toUpperCase();
  const checkpoint = checkpointForWeek(week);
  if (!checkpoint || !ROUTES[normalizedPosition]) {
    return {
      route: "worker",
      checkpoint,
      reason: checkpoint ? "unknown-position-fail-closed" : "pre-week4-fail-closed",
    };
  }

  return {
    route: ROUTES[normalizedPosition][checkpoint] || "worker",
    checkpoint,
    reason: "frozen-2026-prior-only-policy",
  };
}

function finiteNumber(value) {
  // Number(null) and Number("") both equal 0 in JavaScript. For a shadow
  // challenger those values mean "missing", not a legitimate zero projection,
  // so reject them before numeric coercion and fail closed to the champion.
  if (value === null || value === undefined) return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function buildShadowDecision({
  position,
  week,
  championPrediction,
  challengerPrediction,
  championFinalGames = null,
  challengerFinalGames = null,
  playerKey = null,
} = {}) {
  const policy = routeForWeek(position, week);
  const champion = finiteNumber(championPrediction);
  const challenger = finiteNumber(challengerPrediction);
  const championGames = finiteNumber(championFinalGames);
  const challengerGames = finiteNumber(challengerFinalGames);

  // The official result is never replaced by this module.
  // Any missing challenger input fails closed to the current Worker.
  const challengerUsable = policy.route === "v19" && challenger !== null;
  const shadowSource = challengerUsable ? "v19" : "worker";
  const shadowPrediction = challengerUsable ? challenger : champion;
  const shadowFinalGames =
    challengerUsable && challengerGames !== null ? challengerGames : championGames;

  const delta =
    champion !== null && shadowPrediction !== null
      ? shadowPrediction - champion
      : null;
  const deltaPct =
    champion !== null && champion !== 0 && delta !== null
      ? (delta / Math.abs(champion)) * 100
      : null;

  return {
    modelVersion: SHADOW_MODEL_VERSION,
    season: SHADOW_SEASON,
    mode: "shadow-only",
    playerKey,
    position: String(position || "").trim().toUpperCase() || null,
    week: Number.isFinite(Number(week)) ? Number(week) : null,
    checkpoint: policy.checkpoint,
    policyRoute: policy.route,
    policyReason: policy.reason,
    officialSource: "worker",
    officialPrediction: champion,
    officialPredictedFinalGames: championGames,
    shadowSource,
    shadowPrediction,
    shadowPredictedFinalGames: shadowFinalGames,
    delta,
    deltaPct,
    failClosedToWorker: policy.route !== "v19" || !challengerUsable,
  };
}

export function applyShadowToPlayers(players, { week } = {}) {
  if (!Array.isArray(players)) return [];
  return players.map((player) =>
    buildShadowDecision({
      position: player?.position,
      week,
      playerKey: player?.playerKey ?? player?.id ?? null,
      championPrediction:
        player?.championPrediction ?? player?.workerPrediction ?? player?.projection ?? null,
      challengerPrediction:
        player?.challengerPrediction ?? player?.v19Prediction ?? null,
      championFinalGames:
        player?.championFinalGames ?? player?.workerPredictedFinalGames ?? null,
      challengerFinalGames:
        player?.challengerFinalGames ?? player?.v19PredictedFinalGames ?? null,
    })
  );
}

export const SHADOW_ROUTE_MATRIX = ROUTES;
