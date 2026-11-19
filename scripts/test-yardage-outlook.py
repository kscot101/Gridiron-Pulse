#!/usr/bin/env python3
"""Unit tests for frozen pregame yardage feature definitions."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("yardage", Path(__file__).with_name("build-yardage-outlook.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def game(season, week, yards, opponent="BUF", player_id="00-0000001"):
    return {"id": player_id, "position": "WR", "name": "Test Player", "team": "KC",
            "opponent": opponent, "gameId": str(season)+"_"+str(week),
            "season": season, "week": week, "values": {"receivingYards": yards}}


class YardageTests(unittest.TestCase):
    def test_previous_five_and_career_are_separate(self):
        history = [game(2024, i+1, x) for i, x in enumerate([30, 40, 50, 60, 70, 80, 90])]
        out = module.signal(history, "receivingYards", "BUF", 2026)
        self.assertEqual(out["career"]["n"], 7)
        self.assertEqual(out["last5"]["n"], 5)
        self.assertAlmostEqual(out["career"]["value"], 60)
        self.assertAlmostEqual(out["last5"]["value"], 70)
        self.assertEqual(out["h2h"]["raw"]["n"], 7)

    def test_opponent_only_matching_identity(self):
        history = [game(2023, i+1, 50, "DEN") for i in range(6)] + [game(2025, 1, 95, "BUF")]
        out = module.signal(history, "receivingYards", "BUF", 2026)
        self.assertEqual(out["h2h"]["raw"]["n"], 1)
        self.assertAlmostEqual(out["h2h"]["value"], 95)
        # One H2H is heavily shrunk, never treated as a guaranteed 95-yard outcome.
        self.assertTrue(50 < out["forecast"] < 90)

    def test_missing_yardage_not_zero(self):
        rows = [game(2025, i+1, None) for i in range(5)]
        self.assertIsNone(module.signal(rows, "receivingYards", "BUF", 2026))

    def test_fewer_than_five_games_withheld(self):
        rows = [game(2025, i+1, 45) for i in range(4)]
        self.assertIsNone(module.signal(rows, "receivingYards", "BUF", 2026))

    def test_old_meeting_weighs_less_than_new(self):
        rows = [game(2019, i+1, 40, "BUF") for i in range(5)] + [game(2025, 1, 100, "BUF")]
        out = module.signal(rows, "receivingYards", "BUF", 2026)
        self.assertGreater(out["h2h"]["value"], 60)
        self.assertLess(out["h2h"]["effectiveN"], 6)

    def test_team_alias_and_positions(self):
        self.assertEqual(module.team("JAC"), "JAX")
        self.assertEqual(module.position("FB"), "RB")

    def test_model_cdf(self):
        self.assertAlmostEqual(module.normal_cdf(0), .5)
        self.assertAlmostEqual(module.normal_cdf(1.2815515655), .9, places=3)

    def test_quantile(self):
        self.assertEqual(module.quantile([1, 2, 3, 4, 5], .8), 4.2)

    def test_full_career_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Career history would be incomplete"):
                module.build(Path(tmp), Path(tmp)/"out.json", 2026)


if __name__ == "__main__":
    unittest.main(verbosity=2)
