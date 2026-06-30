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


def test_parse_scheme():
    assert engine.parse_scheme("12,10,8") == [12, 10, 8]
    assert engine.parse_scheme("5x5") == [5, 5, 5, 5, 5]
    assert engine.parse_scheme("4x8,10,12") == [8, 10, 12]
    assert engine.parse_scheme(None) == []
    assert engine.parse_scheme("") == []


def test_best_1rm_from_sets():
    sets = [
        {"weight": 100, "reps": 5, "rir": 1, "completed": True},
        {"weight": 110, "reps": 3, "rir": 0, "completed": True},
        {"weight": 200, "reps": 1, "rir": 0, "completed": False},  # ei lasketa
    ]
    best = engine.best_1rm_from_sets(sets)
    # 110x3 antaa korkeamman arvion kuin 100x5(rir1)? tarkistetaan vain validius
    assert best is not None
    assert best["weight"] in (100, 110)


def test_best_1rm_ignores_empty():
    assert engine.best_1rm_from_sets([{"weight": 0, "reps": 0, "completed": True}]) is None


def test_body_composition():
    c = engine.body_composition(100, 20, height_cm=180)
    assert c["fat_mass_kg"] == 20.0
    assert c["lean_mass_kg"] == 80.0
    assert "bmi" in c and "ffmi" in c
    # ilman pituutta vain massat
    c2 = engine.body_composition(80, 15)
    assert c2["fat_mass_kg"] == 12.0
    assert "bmi" not in c2


def test_age_from_birthdate():
    from datetime import date
    assert engine.age_from_birthdate(date(1991, 1, 1), date(2026, 6, 29)) == 35
    assert engine.age_from_birthdate(date(1991, 12, 31), date(2026, 6, 29)) == 34
    assert engine.age_from_birthdate(None, date(2026, 1, 1)) is None


def test_weekly_average_and_trend():
    from datetime import date, timedelta
    today = date(2026, 6, 28)
    # Kaksi viikkoa dataa: edellinen viikko 80, tämä viikko 79
    pts = []
    for i in range(7):
        pts.append((today - timedelta(days=i), 79.0))
        pts.append((today - timedelta(days=7 + i), 80.0))
    assert engine.weekly_average(pts, today, 7) == 79.0
    # Trendi: 79 - 80 = -1 kg/viikko
    assert engine.weight_trend(pts, today) == -1.0


def test_adaptive_tdee():
    # Söi 2500 kcal/pv, paino putosi 1 kg 14 vrk -> TDEE > 2500
    tdee = engine.adaptive_tdee(2500, -1.0, 14)
    assert tdee == round(2500 + 7700 / 14)


def test_macro_targets_cut():
    t = engine.macro_targets(80, "cut", 2800, -0.5)
    assert t["protein_g"] == 176  # 80 * 2.2
    assert t["fat_g"] == 64       # 80 * 0.8
    assert t["kcal"] < 2800       # vaje
    assert t["carbs_g"] >= 0


def test_day_targets_cycling():
    targets = {"kcal": 2500, "protein_g": 180, "fat_g": 70, "carbs_g": 250}
    dt = engine.day_targets(targets, training_days=4, workout_kcal_avg=500)
    assert dt["cycled"] is True
    # Treenipäivä > lepopäivä kaloreissa
    assert dt["train_day"]["kcal"] > dt["rest_day"]["kcal"]
    # Viikkokeskiarvo pysyy ~tavoitteessa
    weekly = dt["train_day"]["kcal"] * 4 + dt["rest_day"]["kcal"] * 3
    assert abs(weekly - 2500 * 7) <= 10
    # Proteiini vakio
    assert dt["train_day"]["protein_g"] == 180 and dt["rest_day"]["protein_g"] == 180


def test_day_targets_no_cycling():
    targets = {"kcal": 2500, "protein_g": 180, "fat_g": 70, "carbs_g": 250}
    assert engine.day_targets(targets, 0)["cycled"] is False
    assert engine.day_targets(targets, 7)["cycled"] is False


def test_weekly_review():
    r = engine.weekly_review(2500, 2480, -0.5, -0.5)
    assert r["target_weekly_kcal"] == 17500
    assert r["adherence_pct"] >= 95
    assert "tavoitteessa" in r["verdict"].lower()


def test_waist_assessment_bulk():
    a = engine.waist_assessment(110, 180, "bulk")
    assert a["waist_height_ratio"] == round(110 / 180, 3)
    assert a["level"] in ("ok", "koholla", "korkea")
    high = engine.waist_assessment(110, 180, "bulk")  # 0.611 -> korkea
    assert high["level"] == "korkea"


def test_classify_lift():
    assert engine.classify_lift("Takakyykky") == "squat"
    assert engine.classify_lift("Penkkipunnerrus") == "bench"
    assert engine.classify_lift("Maastaveto") == "deadlift"
    assert engine.classify_lift("Pystypunnerrus") == "ohp"
    assert engine.classify_lift("Hauiskääntö") is None


def test_strength_level():
    # 200 kg kyykky 100 kg painolla = 2.0x -> korkea taso
    lvl = engine.strength_level("squat", 200, 100, "mies")
    assert lvl["ratio"] == 2.0
    assert lvl["level_index"] == 4  # 1.75x <= 2.0x < 2.1x -> "Kokenut"
    assert lvl["level"] == "Kokenut"
    # heikko nostaja
    low = engine.strength_level("squat", 60, 100, "mies")
    assert low["level_index"] <= 0
    # naisten kertoimet skaalaavat kynnyksiä alas
    f = engine.strength_level("squat", 140, 100, "nainen")
    assert f["level_index"] > engine.strength_level("squat", 140, 100, "mies")["level_index"]


def test_natural_ceiling():
    # Kyykky 2.4x kehon paino naturaalikatto
    assert engine.natural_ceiling("squat", 100, "mies") == 240.0
    # naisilla matalampi
    assert engine.natural_ceiling("squat", 100, "nainen") < 240.0
    # tuntematon liike
    assert engine.natural_ceiling("curl", 100) is None


def test_forecast_progress():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    # nouseva 1RM 100 -> 120 kahdessa kuukaudessa
    hist = [(base + timedelta(days=7 * i), 100 + i * 2.5) for i in range(8)]
    fc = engine.forecast_progress(hist, horizon_weeks=12, ceiling=160)
    assert len(fc) == 12
    assert fc[0]["mid"] > 100  # ennuste nousee
    assert fc[-1]["mid"] <= 160  # ei ylitä kattoa
    assert fc[0]["low"] < fc[0]["mid"] < fc[0]["high"]


def test_physique_level():
    # FFMI 19 -> Harrastaja-luokkaa (miehet)
    p = engine.physique_level(19.0, "mies")
    assert p["level_index"] == 1
    assert p["level"] == "Harrastaja"
    # FFMI 27 -> kilpataso
    high = engine.physique_level(27.0, "mies")
    assert high["level_index"] >= 6
    # Naisilla kynnykset matalammat -> sama FFMI antaa korkeamman tason
    f = engine.physique_level(21.0, "nainen")
    m = engine.physique_level(21.0, "mies")
    assert f["level_index"] > m["level_index"]
    assert engine.physique_level(None) is None


def test_pearson():
    assert engine.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert engine.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == -1.0
    assert engine.pearson([1, 2], [1, 2]) is None  # liian vähän pisteitä


def test_estimate_total():
    lifts = {
        "kyykky": {"weight": 200, "reps": 5, "rir": 1},
        "penkki": {"weight": 140, "reps": 5, "rir": 1},
        "mave": {"weight": 240, "reps": 5, "rir": 1},
    }
    t = engine.estimate_total(lifts)
    assert t.total_low < t.total_mid < t.total_high
    assert "kyykky" in t.per_lift
