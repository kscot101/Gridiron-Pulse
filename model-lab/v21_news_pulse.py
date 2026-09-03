#!/usr/bin/env python3
"""GRIDIRON PULSE v2.1 player news pulse collector.

Collects recent attributed NFL headlines from official club RSS feeds and a
small set of league-wide feeds. It matches articles to players, classifies only
explicit role/form/availability language and stores the evidence used.

News is display-only by default. It cannot change the projection unless the
v2.1 config explicitly enables it and the evidence gate is satisfied.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import feedparser
import requests

TEAM_DOMAINS = {
    "ARI": "azcardinals.com",
    "ATL": "atlantafalcons.com",
    "BAL": "baltimoreravens.com",
    "BUF": "buffalobills.com",
    "CAR": "panthers.com",
    "CHI": "chicagobears.com",
    "CIN": "bengals.com",
    "CLE": "clevelandbrowns.com",
    "DAL": "dallascowboys.com",
    "DEN": "denverbroncos.com",
    "DET": "detroitlions.com",
    "GB": "packers.com",
    "HOU": "houstontexans.com",
    "IND": "colts.com",
    "JAX": "jaguars.com",
    "KC": "chiefs.com",
    "LV": "raiders.com",
    "LAC": "chargers.com",
    "LAR": "therams.com",
    "MIA": "miamidolphins.com",
    "MIN": "vikings.com",
    "NE": "patriots.com",
    "NO": "neworleanssaints.com",
    "NYG": "giants.com",
    "NYJ": "newyorkjets.com",
    "PHI": "philadelphiaeagles.com",
    "PIT": "steelers.com",
    "SEA": "seahawks.com",
    "SF": "49ers.com",
    "TB": "buccaneers.com",
    "TEN": "tennesseetitans.com",
    "WAS": "commanders.com",
}

GENERAL_FEEDS = [
    {
        "name": "PFF NFL",
        "url": "https://www.pff.com/feed",
        "trust": 0.78,
        "official": False,
    },
    {
        "name": "FOX Sports NFL",
        "url": "https://api.foxsports.com/v2/content/optimized-rss?partnerKey=MB0Wehpmuj2lUhuRhQaafhBjAJqaPU244mlTDK1i&size=50&tags=fs%2Fnfl",
        "trust": 0.78,
        "official": False,
    },
    {
        "name": "ESPN NFL",
        "url": "https://www.espn.com/espn/rss/nfl/news",
        "trust": 0.82,
        "official": False,
    },
]

POSITIVE_PATTERNS = [
    (r"\bfull participant\b|\bfull participation\b|\bpracticed in full\b", 0.45, "full-practice"),
    (r"\bexpected to play\b|\bcleared to play\b|\bno limitations\b", 0.45, "cleared"),
    (r"\bexpanded role\b|\blarger role\b|\bfeatured role\b|\bmore targets\b|\bmore carries\b", 0.55, "role-expansion"),
    (r"\bnamed (?:the )?starter\b|\bwill start\b|\bstarting role\b", 0.5, "starter-confirmed"),
    (r"\bstandout\b|\bimpressed\b|\bsharp\b|\bstrong camp\b|\bbreakout\b", 0.32, "positive-form"),
    (r"\bhealthy\b|\bfully healthy\b|\b100 percent\b", 0.24, "healthy"),
]

NEGATIVE_PATTERNS = [
    (r"\bdid not practice\b|\bnonparticipant\b|\bno practice\b", -0.72, "did-not-practice"),
    (r"\bruled out\b|\bwill not play\b|\bnot expected to play\b", -1.0, "out"),
    (r"\bdoubtful\b", -0.78, "doubtful"),
    (r"\bquestionable\b", -0.35, "questionable"),
    (r"\blimited participant\b|\blimited practice\b", -0.28, "limited-practice"),
    (r"\bsnap count\b|\blimited role\b|\bmanaged workload\b", -0.35, "workload-limit"),
    (r"\bdemoted\b|\bmoved to backup\b|\blost the starting job\b", -0.7, "role-loss"),
    (r"\bsetback\b|\bsidelined\b|\bmiss(?:ing|ed)? practice\b", -0.48, "setback"),
    (r"\bstruggling\b|\bstruggled\b|\bslow start\b", -0.22, "negative-form"),
]

RATE_REASONS = {
    "role-expansion",
    "starter-confirmed",
    "positive-form",
    "role-loss",
    "workload-limit",
    "negative-form",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_datetime(entry: Mapping[str, object]) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), timezone.utc)
            except Exception:
                pass
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def player_tokens(name: str) -> Tuple[str, str, str]:
    text = normalize(name)
    parts = [part for part in text.split() if part not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    if not parts:
        return "", "", ""
    first = parts[0]
    last = parts[-1]
    return compact(" ".join(parts)), first, last


def article_matches_player(article_text: str, player_name: str) -> bool:
    full, first, last = player_tokens(player_name)
    compact_text = compact(article_text)
    normalized_text = f" {normalize(article_text)} "
    if not full or not last:
        return False
    if full in compact_text:
        return True
    if len(last) >= 5 and f" {last} " in normalized_text and first and f" {first} " in normalized_text:
        return True
    return False


def classify(text: str) -> dict:
    normalized = normalize(text)
    hits: List[dict] = []
    for pattern, score, reason in [*POSITIVE_PATTERNS, *NEGATIVE_PATTERNS]:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            hits.append({"reason": reason, "score": score})
    raw = sum(item["score"] for item in hits)
    rate_raw = sum(item["score"] for item in hits if item["reason"] in RATE_REASONS)
    return {
        "score": clamp(raw, -1.5, 1.5),
        "rateScore": clamp(rate_raw, -1.0, 1.0),
        "reasons": [item["reason"] for item in hits],
    }


def feed_specs() -> List[dict]:
    specs = list(GENERAL_FEEDS)
    for team, domain in TEAM_DOMAINS.items():
        specs.append(
            {
                "name": f"{team} official",
                "team": team,
                "url": f"https://www.{domain}/rss/news",
                "trust": 1.0,
                "official": True,
            }
        )
    return specs


def load_feed(spec: Mapping[str, object], cutoff: datetime) -> Tuple[List[dict], Optional[str]]:
    url = str(spec["url"])
    try:
        response = requests.get(
            url,
            timeout=25,
            headers={
                "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                "User-Agent": "GridironPulse-NewsPulse/2.1",
            },
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        entries: List[dict] = []
        for entry in parsed.entries:
            published = parse_datetime(entry)
            if published and published < cutoff:
                continue
            title = str(entry.get("title") or "").strip()
            summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary") or entry.get("description") or ""))
            summary = re.sub(r"\s+", " ", summary).strip()
            link = str(entry.get("link") or "").strip()
            if not title:
                continue
            entries.append(
                {
                    "title": title[:240],
                    "summary": summary[:500],
                    "link": link,
                    "publishedAt": published.isoformat() if published else None,
                    "source": str(spec.get("name") or urlparse(url).netloc),
                    "sourceDomain": urlparse(link or url).netloc.lower(),
                    "sourceTeam": spec.get("team"),
                    "trust": safe_float(spec.get("trust"), 0.7),
                    "official": bool(spec.get("official")),
                }
            )
        return entries, None
    except Exception as exc:
        return [], str(exc)


def recency_weight(published_at: Optional[str], now: datetime, lookback_days: int) -> float:
    if not published_at:
        return 0.55
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_days = max(0.0, (now - published).total_seconds() / 86400.0)
    except Exception:
        return 0.55
    return clamp(1.0 - age_days / max(1.0, float(lookback_days)), 0.15, 1.0)


def aggregate_player_news(player: Mapping[str, object], articles: Sequence[Mapping[str, object]], config: Mapping[str, object], now: datetime) -> dict:
    name = str(player.get("playerName") or player.get("player_name") or "")
    team = str(player.get("team") or player.get("targetTeam") or "").upper()
    lookback = int(config["news"].get("lookbackDays") or 8)
    evidence: List[dict] = []
    for article in articles:
        source_team = str(article.get("sourceTeam") or "").upper()
        if source_team and team and source_team != team:
            continue
        text = f"{article.get('title') or ''} {article.get('summary') or ''}"
        if not article_matches_player(text, name):
            continue
        signal = classify(text)
        if not signal["reasons"]:
            continue
        age_weight = recency_weight(article.get("publishedAt"), now, lookback)
        trust = safe_float(article.get("trust"), 0.7)
        evidence.append(
            {
                "source": article.get("source"),
                "sourceDomain": article.get("sourceDomain"),
                "official": bool(article.get("official")),
                "title": article.get("title"),
                "url": article.get("link"),
                "publishedAt": article.get("publishedAt"),
                "reasons": signal["reasons"],
                "weightedScore": signal["score"] * trust * age_weight,
                "weightedRateScore": signal["rateScore"] * trust * age_weight,
            }
        )

    evidence.sort(key=lambda item: abs(safe_float(item.get("weightedScore"))), reverse=True)
    evidence = evidence[:8]
    domains = {str(item.get("sourceDomain") or item.get("source") or "") for item in evidence}
    has_official = any(item.get("official") for item in evidence)
    actionable = bool(
        evidence
        and (
            has_official and bool(config["news"].get("officialSourceCanStandAlone", True))
            or len(domains) >= int(config["news"].get("minimumIndependentSources") or 2)
        )
    )
    score = clamp(sum(safe_float(item.get("weightedScore")) for item in evidence), -1.0, 1.0)
    rate_score = clamp(sum(safe_float(item.get("weightedRateScore")) for item in evidence), -1.0, 1.0)
    cap = safe_float(config["news"].get("maximumRateAdjustmentPct"), 0.025)
    modifier = 1.0 + clamp(rate_score * cap, -cap, cap)
    if score >= 0.18:
        label = "POSITIVE"
    elif score <= -0.18:
        label = "NEGATIVE"
    elif evidence:
        label = "MIXED"
    else:
        label = "NO SIGNAL"
    return {
        "newsSignal": label,
        "newsScore": score,
        "newsRateScore": rate_score,
        "newsModifier": modifier,
        "newsActionable": actionable,
        "newsSourceCount": len(domains),
        "newsEvidence": evidence,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preview = json.loads(args.preview.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if preview.get("productionChanged") is not False or config.get("productionChanged") is not False:
        raise RuntimeError("News pulse requires shadow-only inputs")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=int(config["news"].get("lookbackDays") or 8))
    articles: List[dict] = []
    coverage: List[dict] = []
    seen = set()
    for spec in feed_specs():
        rows, error = load_feed(spec, cutoff)
        kept = 0
        for row in rows:
            key = (str(row.get("link") or ""), str(row.get("title") or ""))
            if key in seen:
                continue
            seen.add(key)
            articles.append(row)
            kept += 1
        coverage.append(
            {
                "source": spec.get("name"),
                "url": spec.get("url"),
                "official": bool(spec.get("official")),
                "articles": kept,
                "error": error,
            }
        )

    players = []
    apply_projection = bool(config["news"].get("applyToProjection", False))
    for raw in preview.get("players") or []:
        if not isinstance(raw, Mapping):
            continue
        player = dict(raw)
        signal = aggregate_player_news(player, articles, config, now)
        player.update(signal)
        player["newsApplied"] = bool(apply_projection and signal["newsActionable"])
        candidate = player.get("candidateProjection")
        if player["newsApplied"] and candidate is not None:
            player["newsAdjustedProjection"] = safe_float(candidate) * signal["newsModifier"]
        else:
            player["newsAdjustedProjection"] = candidate
        player["productionChanged"] = False
        players.append(player)

    output = dict(preview)
    output.update(
        {
            "version": "v2.1-last-season-context-news-preview-1",
            "newsGeneratedAt": now.isoformat(),
            "newsApplyToProjection": apply_projection,
            "newsArticleCount": len(articles),
            "newsPlayersWithEvidence": sum(1 for player in players if player.get("newsEvidence")),
            "newsPlayersActionable": sum(1 for player in players if player.get("newsActionable")),
            "newsCoverage": coverage,
            "players": players,
            "productionChanged": False,
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "articles": len(articles),
                "playersWithEvidence": output["newsPlayersWithEvidence"],
                "playersActionable": output["newsPlayersActionable"],
                "newsApplied": apply_projection,
                "productionChanged": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
