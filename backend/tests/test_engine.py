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


def test_best_1rm_assumes_reserve_for_working_sets():
    # 4x5 @ 100 ilman kirjattua varastoa: EI saa olettaa 5RM:ksi (varasto 0),
    # vaan työsarjoissa on varaa -> 1RM korkeampi kuin pelkkä Epley reps=5.
    four_sets = [{"weight": 100, "reps": 5, "completed": True} for _ in range(4)]
    best = engine.best_1rm_from_sets(four_sets)
    naive = engine.estimate_1rm(100, 5, 0)
    assert best["estimated_1rm"] > naive  # oletettu varasto nostaa arviota
    assert best["assumed_rir"] and best["assumed_rir"] >= 2.0
    # Yksittäinen sarja tulkitaan maksimiyritykseksi (ei lisävarastoa)
    single = engine.best_1rm_from_sets([{"weight": 100, "reps": 1, "completed": True}])
    assert single["assumed_rir"] == 0.0


def test_readiness_flags_overtraining():
    # HRV alhaalla, leposyke koholla, uni vähissä, kuormapiikki -> matala pisteet + varoitukset
    r = engine.readiness(hrv_recent=38, hrv_base=48, rhr_recent=60, rhr_base=52,
                         sleep_recent=6.0, acwr=1.8)
    assert r["score"] < 60
    assert "ylikuormitus" in r["status"]
    assert len(r["warnings"]) >= 3
    # Hyvä tilanne -> korkeat pisteet, ei varoituksia
    good = engine.readiness(hrv_recent=50, hrv_base=48, rhr_recent=50, rhr_base=52,
                            sleep_recent=8.0, acwr=1.0)
    assert good["score"] >= 80 and not good["warnings"]


def test_acwr_status():
    assert engine.acwr_status(170, 100)["zone"] == "korkea"
    assert engine.acwr_status(100, 100)["zone"] == "optimaalinen"
    assert engine.acwr_status(50, 100)["zone"] == "matala"
    assert engine.acwr_status(100, 0) is None


def test_weight_class():
    assert engine.weight_class(82, "mies") == "-83 kg"
    assert engine.weight_class(83, "mies") == "-83 kg"
    assert engine.weight_class(150, "mies") == "+120 kg"
    assert engine.weight_class(60, "nainen") == "-63 kg"


def test_competition_assessment():
    # 83 kg, 690 kg raw total -> kilpatasolla, painoluokka -83 kg
    a = engine.competition_assessment("voimanosto", 690, 83, "mies")
    assert a["weight_class"] == "-83 kg"
    assert a["level_index"] >= 0
    assert a["thresholds_kg"] == sorted(a["thresholds_kg"])  # nouseva
    # Raskaampi nostaja tarvitsee enemmän kiloja samaan tasoon (absoluuttisesti)
    light = engine.competition_assessment("voimanosto", 690, 70, "mies")
    heavy = engine.competition_assessment("voimanosto", 690, 120, "mies")
    assert heavy["thresholds_kg"][-1] > light["thresholds_kg"][-1]
    # Tuntematon laji -> None
    assert engine.competition_assessment("kahvakuula", 100, 80, "mies") is None


def test_baseline_tdee_scales_with_training():
    rest = engine.baseline_tdee(80, 180, 30, "mies", training_days_per_week=0)
    active = engine.baseline_tdee(80, 180, 30, "mies", training_days_per_week=6)
    assert rest is not None and active is not None
    assert active > rest  # enemmän treenejä -> suurempi tarve


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


def test_meal_schedule():
    targets = {"kcal": 2400, "protein_g": 180, "carbs_g": 250, "fat_g": 70}
    plan = engine.meal_schedule(targets, meals=4, wake="07:00", sleep="23:00", training="17:00")
    assert len(plan) == 4
    # Proteiini jaettu tasaisesti
    assert all(m["protein_g"] == 45 for m in plan)
    # Makrosummat säilyvät suunnilleen
    assert abs(sum(m["protein_g"] for m in plan) - 180) <= 4
    assert abs(sum(m["carbs_g"] for m in plan) - 250) <= 4
    # Treenin ympärillä on hiilaripainotteinen ateria (note asetettu)
    assert any("treeni" in m["note"].lower() for m in plan)
    # Ajat nousevat
    times = [m["time"] for m in plan]
    assert times == sorted(times)


def test_meal_schedule_fasting():
    targets = {"kcal": 2000, "protein_g": 160, "carbs_g": 180, "fat_g": 60}
    plan = engine.meal_schedule(targets, meals=3, wake="07:00", fasting_16_8=True)
    # Syönti alkaa noin 12:00 (herää 7 + 5 h)
    assert plan[0]["time"] >= "11:30"
    # Viimeinen ateria ennen 20:30 (8 h ikkuna)
    assert plan[-1]["time"] <= "20:30"


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


def test_volume_verdict():
    assert engine.volume_verdict(3, 0)["status"] == "low"
    assert engine.volume_verdict(14, 12)["status"] == "ok"
    assert engine.volume_verdict(26, 24)["status"] == "high"
    assert engine.volume_verdict(0, 0)["status"] == "none"
    # lasku edellisestä viikosta huomioidaan ok-tilassa
    assert "laski" in engine.volume_verdict(10, 18)["suggestion"].lower()


def test_forecast_confidence():
    assert engine.forecast_confidence(12, 84) >= 0.9   # paljon dataa, pitkä jakso
    assert engine.forecast_confidence(2, 7) < 0.3       # vähän dataa
    assert 0 <= engine.forecast_confidence(6, 40) <= 1


def test_forecast_bodyweight_effect():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    hist = [(base + timedelta(days=7 * i), 100 + i * 2) for i in range(6)]
    normal = engine.forecast_progress(hist, 12, ceiling=160)
    cutting = engine.forecast_progress(hist, 12, ceiling=160, bodyweight_trend_per_week=-1.0)
    # Painon lasku hidastaa ennustettua kehitystä
    assert cutting[-1]["mid"] <= normal[-1]["mid"]


def test_forecast_confidence_widens_band():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    hist = [(base + timedelta(days=7 * i), 100 + i * 2) for i in range(6)]
    sure = engine.forecast_progress(hist, 12, ceiling=160, confidence=1.0)
    unsure = engine.forecast_progress(hist, 12, ceiling=160, confidence=0.2)
    width_sure = sure[5]["high"] - sure[5]["low"]
    width_unsure = unsure[5]["high"] - unsure[5]["low"]
    assert width_unsure > width_sure  # vähemmän dataa -> leveämpi haarukka


def test_forecast_measurement_growth_and_decline():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    grow = [(base + timedelta(weeks=i), 39 + i * 0.3) for i in range(5)]
    fc = engine.forecast_measurement(grow, 12)
    assert fc and fc[-1]["mid"] > 40  # kasvava käsi jatkaa kasvua
    shrink = [(base + timedelta(weeks=i), 90 - i * 0.5) for i in range(5)]
    fcs = engine.forecast_measurement(shrink, 12)
    assert fcs and fcs[-1]["mid"] < 90  # vyötärö voi pienentyä
    assert engine.forecast_measurement([(base, 40), (base, 41)], 12) == []  # liian vähän


def test_measurement_ceiling_and_floor():
    # Hauis katto ~0.25*pituus
    assert engine.measurement_ceiling("hauis", 180) == round(180 * 0.25, 1)
    assert engine.measurement_ceiling("hauis", 180, "nainen") < engine.measurement_ceiling("hauis", 180)
    assert engine.measurement_ceiling("vyötärö", 180) is None  # ei kasvukattoa
    assert engine.measurement_floor("vyötärö", 180) == round(180 * 0.42, 1)


def test_forecast_measurement_respects_ceiling():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    # Lähellä kattoa (45) kasvava hauis -> ennuste ei ylitä kattoa reippaasti
    grow = [(base + timedelta(weeks=i), 44 + i * 0.2) for i in range(5)]
    fc = engine.forecast_measurement(grow, 26, ceiling=45.0)
    assert fc[-1]["mid"] <= 45 * 1.05  # taipuu kattoa kohti


def test_measurement_insight():
    # Kasvu kun paino+vyötärö nousee -> rasvavihje
    n = engine.measurement_insight("hauis", 0.2, 41, 45.0, bw_trend=0.3, waist_trend=0.2)
    assert "rasvaa" in n
    # Vakaa dieetillä -> lihas säilyy
    n2 = engine.measurement_insight("hauis", 0.0, 41, 45.0, bw_trend=-0.5, waist_trend=-0.2)
    assert "säilyy" in n2.lower()
    # Lihaskasvu kun paino/vyötärö ei nouse
    n3 = engine.measurement_insight("reisi", 0.3, 60, 68.0, bw_trend=0.0, waist_trend=0.0)
    assert "lihaskasvu" in n3.lower()


def test_recent_rate_per_week():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    pts = [(base + timedelta(weeks=i), 80 + i) for i in range(4)]
    assert round(engine.recent_rate_per_week(pts)) == 1  # +1/viikko
    assert engine.recent_rate_per_week([(base, 80)]) is None


def test_estimate_workout_kcal():
    k = engine.estimate_workout_kcal(85, 60)
    assert k and 350 < k < 600   # ~85*0.0875*60 ≈ 446
    assert engine.estimate_workout_kcal(0, 60) is None
    assert engine.estimate_workout_kcal(85, 0) is None


def test_proportion_score():
    # Hyvät suhteet -> korkea pistemäärä
    good = engine.proportion_score({"vyötärö": 80, "hartia": 128, "rintakehä": 112}, 180)
    assert good["score"] > 70
    # Iso vyötärö -> matalampi
    bad = engine.proportion_score({"vyötärö": 110, "hartia": 120, "rintakehä": 120}, 180)
    assert bad["score"] < good["score"]
    # Ei mittoja -> None
    assert engine.proportion_score({}, 180) is None


def test_bodypart_level():
    # Iso hauis (45cm @180cm = 0.25) -> korkea taso
    big = engine.bodypart_level("hauis", 45, 180, "mies")
    assert big["level_index"] >= 4
    small = engine.bodypart_level("hauis", 32, 180, "mies")
    assert small["level_index"] <= 0
    # Vyötärö käänteinen: ohut vyötärö (76cm @180 = 0.42) -> korkea taso
    lean = engine.bodypart_level("vyötärö", 76, 180)
    fat = engine.bodypart_level("vyötärö", 100, 180)
    assert lean["level_index"] > fat["level_index"]
    assert lean["reversed"] is True
    # Tuntematon kohta
    assert engine.bodypart_level("nilkka", 22, 180) is None
    # Ilman pituutta
    assert engine.bodypart_level("hauis", 40, None) is None


def test_population_average():
    avg = engine.population_average("squat", 100, "mies")
    assert avg == 70.0  # 0.7 * 100 (treenamaton aikuinen)
    assert engine.population_average("squat", 100, "nainen") < avg
    assert engine.population_average("curl", 100) is None


def test_calibration_factor():
    # Toteuma kasvoi 2x ennustettua -> kerroin > 1 (aliarvioitiin)
    m = [{"base": 100, "predicted": 110, "actual": 120},
         {"base": 100, "predicted": 105, "actual": 110}]
    assert engine.calibration_factor(m) > 1.0
    # Yliarvioitu -> < 1
    m2 = [{"base": 100, "predicted": 120, "actual": 105},
          {"base": 100, "predicted": 115, "actual": 108}]
    assert engine.calibration_factor(m2) < 1.0
    # Liian vähän dataa -> 1.0
    assert engine.calibration_factor([{"base": 100, "predicted": 110, "actual": 120}]) == 1.0


def test_value_near():
    from datetime import date
    series = [(date(2026, 1, 1), 100), (date(2026, 2, 1), 110)]
    assert engine.value_near(series, date(2026, 2, 3)) == 110
    assert engine.value_near(series, date(2026, 6, 1)) is None  # liian kaukana


def test_forecast_calibration_scales_rate():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    hist = [(base + timedelta(weeks=i), 100 + i * 2) for i in range(6)]
    low = engine.forecast_progress(hist, 12, ceiling=200, rate_calibration=0.7)
    high = engine.forecast_progress(hist, 12, ceiling=200, rate_calibration=1.3)
    assert high[-1]["mid"] > low[-1]["mid"]  # isompi kalibrointi -> nopeampi ennuste


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
