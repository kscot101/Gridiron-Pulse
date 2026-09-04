#!/usr/bin/env python3
"""Add touchdown projections to the Gridiron Pulse v2.1 preview.

Touchdowns use the same net projection adjustment already produced by v2.1:
2025 player TD/game rate x (v2.1 context rate / 2025 reported primary rate).
Availability uses the same candidate remaining games as the primary projection.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Mapping

import pandas as pd
import requests


def finite(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_name(value: object) -> str:
    import re
    text = str(value or "").lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_team(value: object) -> str:
    text = str(value or "").strip().upper()
    return {"JAC": "JAX", "LA": "LAR", "STL": "LAR", "OAK": "LV", "SD": "LAC", "WSH": "WAS"}.get(text, text)


def normalize_position(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"RB", "FB", "HB", "TB"}:
        return "RB"
    if text in {"WR", "LWR", "RWR", "SWR", "FL", "SE"}:
        return "WR"
    if text in {"TE", "LTE", "RTE"}:
        return "TE"
    return text


def worker_name(player: Mapping[str, object]) -> str:
    return str(player.get("playerName") or player.get("name") or player.get("displayName") or player.get("fullName") or "")


def current_touchdowns(player: Mapping[str, object], position: str) -> float:
    stats = player.get("currentStats") if isinstance(player.get("currentStats"), Mapping) else {}

    def first(*keys: str) -> float:
        for key in keys:
            if key in stats and stats.get(key) is not None:
                return finite(stats.get(key), 0.0)
        return 0.0

    if position == "QB":
        return first("passingTouchdowns", "passingTds", "passingTDs", "passing_tds")
    if position == "RB":
        return first("rushingTouchdowns", "rushingTds", "rushingTDs", "rushing_tds") + first(
            "receivingTouchdowns", "receivingTds", "receivingTDs", "receiving_tds"
        )
    return first("receivingTouchdowns", "receivingTds", "receivingTDs", "receiving_tds")


def load_worker(url: str) -> list[dict]:
    try:
        response = requests.get(url, timeout=45, headers={"User-Agent": "GridironPulse-TDProjection/2.1"})
        response.raise_for_status()
        payload = response.json()
        outlook = payload.get("seasonOutlook") if isinstance(payload.get("seasonOutlook"), Mapping) else payload
        players = outlook.get("players") if isinstance(outlook, Mapping) else []
        return players if isinstance(players, list) else []
    except Exception:
        return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--worker-url", required=True)
    args = parser.parse_args()

    preview = json.loads(args.preview.read_text(encoding="utf-8"))
    players = preview.get("players") if isinstance(preview.get("players"), list) else []
    source = pd.read_csv(args.source, low_memory=False)
    source["season"] = pd.to_numeric(source.get("season"), errors="coerce")
    prior = source[source["season"] < args.season].sort_values("season", ascending=False)

    by_id = {}
    by_name_pos = {}
    for row in prior.to_dict("records"):
        player_id = str(row.get("player_id") or "")
        key = (normalize_name(row.get("player_name")), normalize_position(row.get("position")))
        if player_id and player_id not in by_id:
            by_id[player_id] = row
        if key[0] and key not in by_name_pos:
            by_name_pos[key] = row

    worker_players = load_worker(args.worker_url)
    worker_index = {}
    for player in worker_players:
        pos = normalize_position(player.get("positionGroup") or player.get("position"))
        key = (normalize_name(worker_name(player)), pos, normalize_team(player.get("team")))
        worker_index[key] = player
        worker_index.setdefault((key[0], key[1], ""), player)

    projected_count = 0
    for player in players:
        pos = normalize_position(player.get("position") or player.get("target_position"))
        player_id = str(player.get("player_id") or player.get("playerKey") or player.get("athleteId") or "")
        history = by_id.get(player_id) or by_name_pos.get((normalize_name(player.get("playerName") or player.get("player_name")), pos))
        if not history:
            player["candidateTouchdowns"] = None
            player["projectedTouchdownsPerGame"] = None
            continue

        last_td_total = finite(history.get("touchdowns"), 0.0)
        last_td_pg = finite(history.get("touchdowns_pg"), 0.0)
        reported_rate = finite(player.get("last_year_reported_rate"), 0.0)
        context_rate = finite(player.get("last_year_context_rate"), reported_rate)
        adjustment = context_rate / reported_rate if reported_rate > 1e-9 else 1.0
        adjustment = max(0.50, min(1.50, adjustment))
        projected_td_pg = max(0.0, last_td_pg * adjustment)

        team = normalize_team(player.get("team") or player.get("targetTeam") or player.get("target_team"))
        worker = worker_index.get((normalize_name(player.get("playerName") or player.get("player_name")), pos, team)) or worker_index.get(
            (normalize_name(player.get("playerName") or player.get("player_name")), pos, "")
        )
        actual_tds = current_touchdowns(worker, pos) if worker else 0.0
        remaining = max(0.0, finite(player.get("candidateRemainingGames"), finite(player.get("projected_games_v21"), 17.0)))
        candidate_tds = actual_tds + projected_td_pg * remaining

        next_factor = finite(player.get("nextMatchupFactor"), 1.0)
        player.update(
            {
                "lastYearTouchdowns": round(last_td_total, 3),
                "lastYearTouchdownsPerGame": round(last_td_pg, 4),
                "touchdownProjectionAdjustment": round(adjustment, 4),
                "projectedTouchdownsPerGame": round(projected_td_pg, 4),
                "actualTouchdowns": round(actual_tds, 3),
                "candidateTouchdowns": round(candidate_tds, 2),
                "nextGameTouchdownRate": round(projected_td_pg * next_factor, 4) if player.get("nextOpponent") else None,
            }
        )
        projected_count += 1

    preview["players"] = players
    meta = preview.get("meta") if isinstance(preview.get("meta"), dict) else {}
    meta["touchdownProjectionPlayers"] = projected_count
    meta["touchdownProjectionMethod"] = "2025 TD/game x exact v2.1 net primary-rate adjustment x same projected availability"
    preview["meta"] = meta
    args.preview.write_text(json.dumps(preview, indent=2, allow_nan=False), encoding="utf-8")

    csv_path = args.preview.with_suffix(".csv")
    if csv_path.exists():
        pd.DataFrame(players).to_csv(csv_path, index=False)

    print(f"Touchdown projections added: {projected_count}/{len(players)}")


if __name__ == "__main__":
    main()
