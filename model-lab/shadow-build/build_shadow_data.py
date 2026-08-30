#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import requests

HERE = Path(__file__).resolve()
MODEL_LAB = HERE.parents[1]
sys.path.insert(0, str(MODEL_LAB))

from v19_live_challenger_feed import (  # noqa: E402
    live_feature_frame,
    normalize_name,
    normalize_team,
    worker_identity_key,
    worker_player_key,
    worker_projection_value,
)
from v19_player_availability_backtest import enrich_availability_columns  # noqa: E402

SEASON = 2026
WORKER_URL = "https://gridiron-pulse-season.kadescott97.workers.dev/season-outlook"
PACK_PATH = MODEL_LAB / "v19_shadow_model_pack.json"
DIST = HERE.parent / "dist"
ROUTES = {
    ("RB", 4): "v19",
    ("WR", 4): "v19",
    ("WR", 8): "v19",
    ("TE", 8): "v19",
}


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def round6(value):
    number = finite(value)
    return None if number is None else round(number, 6)


def checkpoint_for_week(week: int):
    if week < 4:
        return None
    if week < 8:
        return 4
    if week < 12:
        return 8
    return 12


def load_pack():
    payload = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    if payload.get("version") != "v1.9-shadow-model-pack-1":
        raise RuntimeError("Unexpected v1.9 model pack version")
    if not payload.get("researchOnly"):
        raise RuntimeError("Model pack is not marked research-only")
    return payload


def load_worker_snapshot():
    try:
        response = requests.get(
            WORKER_URL,
            timeout=30,
            headers={"Accept": "application/json", "User-Agent": "GridironPulse-shadow-build/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        snapshot = payload.get("seasonOutlook") if isinstance(payload, Mapping) else None
        if not isinstance(snapshot, Mapping):
            snapshot = payload if isinstance(payload, Mapping) else {}
        players = snapshot.get("players") if isinstance(snapshot, Mapping) else []
        return dict(snapshot), [row for row in (players or []) if isinstance(row, Mapping)], None
    except Exception as exc:
        return {}, [], f"worker-fetch-failed: {exc}"


def indexes(players):
    by_id = {}
    by_identity = {}
    for player in players:
        key = worker_player_key(player)
        if key:
            by_id[key] = player
        identity = worker_identity_key(player)
        if identity[0] and identity[1]:
            by_identity[identity] = player
    return by_id, by_identity


def find_worker(row, by_id, by_identity):
    key = str(row.get("playerKey") or "").upper().strip()
    if key and key in by_id:
        return by_id[key]
    identity = (
        normalize_name(row.get("playerName")),
        str(row.get("position") or "").upper().strip(),
        normalize_team(row.get("team")),
    )
    return by_identity.get(identity)


def knn(model, raw, kind):
    features = list(model.get("features") or [])
    medians = list(model.get("medians") or [])
    scales = list(model.get("scales") or [])
    history_x = list(model.get("x") or [])
    history_y = list(model.get("y") or [])
    if not features or len(features) != len(medians) or len(features) != len(scales):
        raise RuntimeError("Invalid KNN model")

    vector = []
    imputed = []
    for idx, feature in enumerate(features):
        median = finite(medians[idx]) or 0.0
        scale = finite(scales[idx])
        if scale is None or abs(scale) < 1e-9:
            scale = 1.0
        value = finite(raw.get(feature))
        if value is None:
            value = median
            imputed.append(feature)
        vector.append((value - median) / scale)

    candidates = []
    for row, target in zip(history_x, history_y):
        if not isinstance(row, list) or len(row) != len(vector):
            continue
        values = [finite(value) for value in row]
        y = finite(target)
        if y is None or any(value is None for value in values):
            continue
        distance = math.sqrt(sum((value - vector[i]) ** 2 for i, value in enumerate(values)) / len(vector))
        candidates.append((distance, y))
    candidates.sort(key=lambda item: item[0])
    k = min(max(1, int(finite(model.get("k")) or 1)), len(candidates))
    if k <= 0:
        raise RuntimeError("No valid KNN comparables")

    chosen = candidates[:k]
    weights = []
    for distance, _ in chosen:
        if kind == "rate":
            weights.append(1.0 / max(distance + 0.15, 0.15))
        else:
            weights.append(1.0 / max(distance, 0.05))
    denom = sum(weights)
    prediction = sum(weight * chosen[i][1] for i, weight in enumerate(weights)) / denom
    return prediction, k, imputed


def project_row(pack, record, official):
    position = str(record.get("position") or "").upper()
    checkpoint = int(record.get("checkpoint") or 0)
    route_key = f"{position}-{checkpoint}"
    route = pack.get("routes", {}).get(route_key)
    if not route or ROUTES.get((position, checkpoint)) != "v19":
        return None

    pace = finite(record.get("pacePrimaryEq17"))
    current_primary = finite(record.get("currentPrimary"))
    current_games = finite(record.get("games"))
    current_team_games = finite(record.get("currentTeamGames"))
    remaining_team_games = finite(record.get("remainingTeamGames"))
    if None in (pace, current_primary, current_team_games, remaining_team_games):
        return None

    rate_raw = {feature: record.get(feature) for feature in route["rate"]["features"]}
    health_raw = {feature: record.get(feature) for feature in route["availability"]["features"]}
    rate_adjustment, rate_k, rate_imputed = knn(route["rate"], rate_raw, "rate")
    availability, avail_k, avail_imputed = knn(route["availability"], health_raw, "availability")
    availability = max(0.0, min(1.0, availability))
    rate_eq17 = pace + (rate_adjustment if route.get("historyGate") else 0.0)
    remaining_games = availability * remaining_team_games
    shadow = current_primary + (rate_eq17 / 17.0) * remaining_games
    predicted_final_games = None if current_games is None else current_games + remaining_games
    official_prediction = worker_projection_value(official) if official else None
    delta = None if official_prediction is None else shadow - official_prediction
    delta_pct = None if official_prediction in (None, 0) else delta / abs(official_prediction) * 100.0

    return {
        "playerKey": record.get("playerKey"),
        "playerName": record.get("playerName"),
        "team": record.get("team"),
        "position": position,
        "checkpoint": checkpoint,
        "routeKey": route_key,
        "officialSource": "current-season-worker",
        "officialPrediction": round6(official_prediction),
        "shadowSource": "v19",
        "shadowPrediction": round6(shadow),
        "delta": round6(delta),
        "deltaPct": round6(delta_pct),
        "currentPrimary": round6(current_primary),
        "currentGames": round6(current_games),
        "currentTeamGames": round6(current_team_games),
        "paceEq17": round6(pace),
        "rateEq17": round6(rate_eq17),
        "rateAdjustment": round6(rate_adjustment),
        "availabilityRate": round6(availability),
        "predictedRemainingGames": round6(remaining_games),
        "predictedFinalGames": round6(predicted_final_games),
        "rateNeighbors": rate_k,
        "availabilityNeighbors": avail_k,
        "rateImputedFeatures": rate_imputed,
        "availabilityImputedFeatures": avail_imputed,
    }


def build_live(pack, snapshot, worker_players):
    env_week = os.getenv("SHADOW_WEEK")
    week = int(env_week) if env_week and env_week.isdigit() else int(finite(snapshot.get("seasonWeek")) or 1)
    checkpoint = checkpoint_for_week(week)
    base = {
        "ok": True,
        "version": "v1.9-shadow-build-1",
        "mode": "shadow-only",
        "season": SEASON,
        "requestedWeek": week,
        "checkpoint": checkpoint,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "officialSource": "current-season-worker",
        "productionChanged": False,
    }
    if checkpoint is None:
        return {**base, "ready": False, "reason": "pre-week4-worker-only", "players": []}

    frame, status = live_feature_frame(SEASON, checkpoint)
    if frame.empty or not status.get("ready"):
        return {**base, "ready": False, "reason": status.get("reason", "live-features-unavailable"), "featureStatus": status, "players": []}

    frame = enrich_availability_columns(frame)
    by_id, by_identity = indexes(worker_players)
    outputs = []
    matched = 0
    for record in frame.to_dict("records"):
        position = str(record.get("position") or "").upper()
        if ROUTES.get((position, checkpoint)) != "v19":
            continue
        official = find_worker(record, by_id, by_identity)
        if official:
            matched += 1
        result = project_row(pack, record, official)
        if result:
            outputs.append(result)

    outputs.sort(key=lambda row: abs(row.get("delta") or 0.0), reverse=True)
    return {
        **base,
        "ready": bool(outputs),
        "reason": "ready" if outputs else "no-challenger-rows",
        "featureStatus": status,
        "summary": {
            "workerPlayers": len(worker_players),
            "challengerPlayers": len(outputs),
            "matchedOfficialPlayers": matched,
        },
        "players": outputs,
    }


def build_rehearsal(pack):
    season = 2025
    checkpoint = 4
    frame, status = live_feature_frame(season, checkpoint)
    if frame.empty or not status.get("ready"):
        return {
            "ok": True,
            "ready": False,
            "mechanicalRehearsalOnly": True,
            "notABacktest": True,
            "season": season,
            "checkpoint": checkpoint,
            "featureStatus": status,
            "players": [],
        }
    frame = enrich_availability_columns(frame)
    rows = []
    for record in frame.to_dict("records"):
        position = str(record.get("position") or "").upper()
        route_key = f"{position}-{checkpoint}"
        route = pack.get("routes", {}).get(route_key)
        if ROUTES.get((position, checkpoint)) != "v19" or not route:
            continue
        rate_missing = [name for name in route["rate"]["features"] if finite(record.get(name)) is None]
        health_missing = [name for name in route["availability"]["features"] if finite(record.get(name)) is None]
        rows.append(
            {
                "playerKey": record.get("playerKey"),
                "playerName": record.get("playerName"),
                "team": record.get("team"),
                "position": position,
                "routeKey": route_key,
                "currentPrimary": round6(record.get("currentPrimary")),
                "games": round6(record.get("games")),
                "currentTeamGames": round6(record.get("currentTeamGames")),
                "paceEq17": round6(record.get("pacePrimaryEq17")),
                "rateMissing": rate_missing,
                "availabilityMissing": health_missing,
            }
        )
    return {
        "ok": True,
        "ready": bool(rows),
        "mechanicalRehearsalOnly": True,
        "notABacktest": True,
        "doNotEvaluateAccuracy": True,
        "season": season,
        "checkpoint": checkpoint,
        "featureStatus": status,
        "summary": {
            "challengerRows": len(rows),
            "fullyCompleteRows": sum(1 for row in rows if not row["rateMissing"] and not row["availabilityMissing"]),
        },
        "players": rows[:100],
    }


def write_json(name, payload):
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / name).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def main():
    pack = load_pack()
    snapshot, worker_players, worker_error = load_worker_snapshot()
    live = build_live(pack, snapshot, worker_players)
    live["workerFetchError"] = worker_error
    rehearsal = build_rehearsal(pack)
    write_json("shadow-data.json", live)
    write_json("collector-test.json", rehearsal)
    write_json(
        "index.json",
        {
            "ok": True,
            "service": "gridiron-shadow-data",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "liveReady": live.get("ready", False),
            "liveReason": live.get("reason"),
            "collectorReady": rehearsal.get("ready", False),
            "productionChanged": False,
            "files": ["shadow-data.json", "collector-test.json"],
        },
    )
    print(json.dumps({"liveReady": live.get("ready"), "liveReason": live.get("reason"), "collectorReady": rehearsal.get("ready"), "dist": str(DIST)}, indent=2))


if __name__ == "__main__":
    main()
