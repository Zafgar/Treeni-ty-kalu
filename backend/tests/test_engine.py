"""Laskentamoottorin testit."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import engine


def test_estimate_1rm_basic():
    # 100 kg x 1 toisto, ei varastoa -> 1RM = 100
    assert engine.estimate_1rm(100, 1, 0) == 100
    # Epley: 100 x 5 -> 100 * (1 + 5/30) ~= 116.7
    assert round(engine.estimate_1rm(100, 5, 0), 1) == 116.7


def test_1rm_with_rir():
    # 5 toistoa varastolla 2 = 7 toistoa uupumukseen -> isompi 1RM-arvio
    assert engine.estimate_1rm(100, 5, 2) > engine.estimate_1rm(100, 5, 0)


def test_convert_scheme_more_reps_lowers_weight():
    # 4x5 -> 4x8 samalla varastolla: enemmän toistoja -> kevyempi paino
    r = engine.convert_scheme(100, 4, 5, 4, 8, current_rir=2, target_rir=2)
    assert r.suggested_weight < 100
    assert r.from_scheme == "4x5"
    assert r.to_scheme == "4x8"


def test_convert_scheme_fewer_reps_raises_weight():
    # 4x8 -> 4x5: vähemmän toistoja -> raskaampi paino
    r = engine.convert_scheme(100, 4, 8, 4, 5, current_rir=2, target_rir=2)
    assert r.suggested_weight > 100


def test_round_to_increment():
    assert engine.round_to_increment(101.2, 2.5) == 100.0
    assert engine.round_to_increment(101.3, 2.5) == 102.5


def test_estimate_total():
    lifts = {
        "kyykky": {"weight": 200, "reps": 5, "rir": 1},
        "penkki": {"weight": 140, "reps": 5, "rir": 1},
        "mave": {"weight": 240, "reps": 5, "rir": 1},
    }
    t = engine.estimate_total(lifts)
    assert t.total_low < t.total_mid < t.total_high
    assert "kyykky" in t.per_lift
