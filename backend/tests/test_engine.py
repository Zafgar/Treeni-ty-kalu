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


def test_backtest_learns_from_data():
    from datetime import date, timedelta
    base = date.today()

    def mk(vals, step=30):
        return [(base - timedelta(days=(len(vals) - 1 - i) * step), v) for i, v in enumerate(vals)]

    # Plataa: malli yliarvioi -> rate_ratio < 1 (kaava oppii hidastumisen)
    plateau = engine.backtest_forecast(mk([170, 175, 178, 179, 179.5, 180, 180, 180]))
    assert plateau["rate_ratio"] < 1.0 and plateau["n"] >= 3

    # Tasainen vahva vaste (geneettinen): malli osuu tai aliarvioi -> rate_ratio >= 1
    responder = engine.backtest_forecast(mk([150, 152, 155, 157, 160, 162, 165, 168]))
    assert responder["rate_ratio"] >= 1.0

    # Johdonmukainen data -> pieni empiirinen virhe -> kapea haarukka
    steady = mk([176, 177, 178, 179, 180, 181, 182, 183])
    bt = engine.backtest_forecast(steady)
    fc = engine.forecast_progress(steady, 52, ceiling=210, error_scale=bt["error_scale"],
                                  rate_calibration=bt["rate_ratio"])
    assert (fc[-1]["high"] - fc[-1]["low"]) < 20  # kapea kun data on tasaista

    # Liian vähän dataa -> neutraali (ei opi)
    assert engine.backtest_forecast(mk([100, 110]))["n"] == 0


def test_forecast_tames_with_sparse_data():
    from datetime import date, timedelta
    base = date.today()
    # Harva, jyrkkä data (2 pistettä viikon välein, +8 kg) -> ei saa räjähtää
    sparse = [(base - timedelta(days=7), 100), (base, 108)]
    conf_s = engine.forecast_confidence(2, 7)
    fc_s = engine.forecast_progress(sparse, 52, ceiling=200, confidence=conf_s)
    # Tiheä, tasainen data -> kapeampi haarukka ja maltillisempi mid
    rich = [(base - timedelta(days=180 - i * 15), 100 + i * 1.5) for i in range(12)]
    conf_r = engine.forecast_confidence(12, 180)
    fc_r = engine.forecast_progress(rich, 52, ceiling=200, confidence=conf_r)
    w_sparse = fc_s[-1]["high"] - fc_s[-1]["low"]
    w_rich = fc_r[-1]["high"] - fc_r[-1]["low"]
    assert w_rich < w_sparse            # haarukka kapenee kun dataa on enemmän
    assert fc_s[-1]["mid"] < 100 + 52 * 4  # ei absurdia nousua vuodessa


def test_readiness_flags_overtraining():
    # Riittävästi pitkän ajan dataa -> hälytykset annetaan
    r = engine.readiness(hrv_recent=38, hrv_base=48, hrv_base_n=20, hrv_recent_n=6,
                         rhr_recent=60, rhr_base=52, rhr_base_n=20, rhr_recent_n=6,
                         sleep_recent=6.0, sleep_n=6, acwr=1.8)
    assert r["score"] < 60
    assert "ylikuormitus" in r["status"]
    assert len(r["warnings"]) >= 3
    # Hyvä tilanne -> korkeat pisteet, ei varoituksia
    good = engine.readiness(hrv_recent=50, hrv_base=48, hrv_base_n=20, hrv_recent_n=6,
                            rhr_recent=50, rhr_base=52, rhr_base_n=20, rhr_recent_n=6,
                            sleep_recent=8.0, sleep_n=6, acwr=1.0)
    assert good["score"] >= 80 and not good["warnings"]


def test_readiness_thin_data_no_alarm():
    # Vähän vertailudataa -> ei kovaa hälytystä vaikka arvot huonoja
    r = engine.readiness(hrv_recent=38, hrv_base=48, hrv_base_n=3, hrv_recent_n=1,
                         rhr_recent=60, rhr_base=52, rhr_base_n=3, rhr_recent_n=1)
    assert not r["warnings"]
    assert r["thin_data"] is True


def test_readiness_feeling_and_nutrition():
    # Huono treenifiilis + ravinnon vajaus tuottavat varoitukset ilman biometriaa
    r = engine.readiness(neg_feeling_ratio=0.6, feeling_n=5,
                         nutrition_deficit_pct=0.30, nutrition_n=8)
    assert any("fiilis" in w.lower() for w in r["warnings"])
    assert any("ravinto" in w.lower() for w in r["warnings"])


def test_mr_olympia_tier():
    lv = engine.physique_level(31, "mies")
    assert lv["level"] == "Mr. Olympia -taso"
    assert len(lv["levels"]) == 9


def test_bodypart_fat_adjustment():
    # Korkealla rasva-%:lla iso mitta ei ole yhtä paljon lihasta
    high = engine.bodypart_level("hauis", 42, 180, "mies", body_fat_pct=28)
    assert high.get("fat_inflation_cm", 0) > 0
    assert high["lean_adjusted_cm"] < 42
    assert high["lean_level_index"] <= high["level_index"]
    # Lean-tasolla ei korjausta
    lean = engine.bodypart_level("hauis", 42, 180, "mies", body_fat_pct=12)
    assert "fat_inflation_cm" not in lean


def test_measurement_forecast_weight_coupling():
    from datetime import date, timedelta
    b = date.today()
    hist = [(b - timedelta(days=(3 - i) * 30), 62) for i in range(4)]  # reisi tasainen
    losing = engine.forecast_measurement(hist, 26, site="reisi", bodyweight=100,
                                         body_fat_pct=30, bodyweight_trend_per_week=-0.5)
    stable = engine.forecast_measurement(hist, 26, site="reisi", bodyweight=100,
                                         body_fat_pct=30, bodyweight_trend_per_week=0.0)
    assert losing[-1]["mid"] < stable[-1]["mid"]   # painonpudotus pienentää reittä
    assert abs(stable[-1]["mid"] - 62) < 0.5       # vakiopaino -> pysyy samana


def test_body_fat_navy():
    # Mies: kaula 40, vyötärö 88, pituus 180 -> järkevä rasva-% (10–25 %)
    bf = engine.body_fat_navy("mies", 180, 40, 88)
    assert bf is not None and 8 < bf < 30
    # Puuttuva mitta -> None
    assert engine.body_fat_navy("mies", 180, None, 88) is None
    # Nainen vaatii myös lantion
    assert engine.body_fat_navy("nainen", 168, 32, 70) is None
    assert engine.body_fat_navy("nainen", 168, 32, 70, hip_cm=95) is not None


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


def test_muscle_map_tricky_names():
    """Regressio: nimet joissa yleinen avainsana osuisi väärään sääntöön."""
    from app import engine
    # Ojentajaliikkeet eivät saa mennä rinta-sääntöön "punnerrus"-sanasta
    for name in ("Ranskalainen punnerrus", "Ojentajan punnerrus köysi",
                 "Taljapunnerrus", "Yhden käden ojentajapunnerrus käsipaino"):
        m = engine.exercise_muscle_map(name)
        assert m.get("ojentajat") == 1 and "rinta" not in m, name
    # Reverse pec deck on takaolkapää, ei rinta
    m = engine.exercise_muscle_map("Takaolkapää (reverse pec deck)")
    assert m.get("olkapäät", 0) >= 0.8 and "rinta" not in m
    # Heilautus on takaketjuliike, ei etureisiliike
    m = engine.exercise_muscle_map("Kahvakuulaheilautus", "jalat")
    assert m.get("pakarat") == 1 and m.get("takareidet", 0) >= 0.5
    # Vatsa-kategoria ilman nimiosumaa -> keskivartalo
    assert engine.exercise_muscle_map("Riipunta jalannosto", "vatsa") == {"keskivartalo": 1}
    # Penkki ja pystypunnerrus pysyvät oikein
    assert engine.exercise_muscle_map("Penkkipunnerrus")["rinta"] == 1
    assert engine.exercise_muscle_map("Pystypunnerrus")["olkapäät"] == 1


def test_experience_rate_calibration():
    from app import engine
    # Aloittelija nostaa tahtia kun dataa vähän, kokenut laskee
    assert engine.experience_rate_calibration("aloittelija", 0.0) > 1.2
    assert engine.experience_rate_calibration("kokenut", 0.0) < 0.8
    # Vaikutus häipyy kun luottamus (oma data) kasvaa
    assert abs(engine.experience_rate_calibration("aloittelija", 1.0) - 1.0) < 1e-9
    assert abs(engine.experience_rate_calibration("kokenut", 1.0) - 1.0) < 1e-9
    # Tuntematon/ei vastausta -> neutraali
    assert engine.experience_rate_calibration(None, 0.2) == 1.0


def test_nutrition_quality_and_direction_helpers():
    from app import engine
    # Huono tyyli: vähän proteiinia, paljon herkkuja, vähän kasviksia
    bad = {"protein_g": 70, "fat_g": 60, "carb_share": 0.5, "fat_share": 0.35,
           "treat_share": 0.4, "veg_g": 100, "kcal": 2500, "n_days": 6}
    q = engine.nutrition_quality(bad, 85, "maintain")
    assert q["level"] == "heikko" and q["energy_flag"] is True
    assert q["score"] < 50 and q["better_approach"]
    # Hyvä tyyli
    good = {"protein_g": 170, "fat_g": 80, "carb_share": 0.4, "fat_share": 0.3,
            "treat_share": 0.08, "veg_g": 550, "kcal": 2600, "n_days": 7}
    assert engine.nutrition_quality(good, 85, "maintain")["level"] == "hyva"
    # Liian vähän dataa -> None
    assert engine.nutrition_quality({**good, "n_days": 3}, 85) is None

    # Kuukauden suunta: molemmat nousevat selvästi -> väärä suunta
    v = engine.waist_weight_direction(1.5, 2.5, True)
    assert v["status"] == "bad" and v["action"] is True
    # Pieni muutos EI hälytä (turvotus/tarkkuus)
    assert engine.waist_weight_direction(0.2, 0.5, True) is None
    # Ei tarpeeksi dataa -> None vaikka luvut isot
    assert engine.waist_weight_direction(1.5, 2.5, False) is None
    # Vyötärö kaventuu -> hyvä
    assert engine.waist_weight_direction(0.3, -1.5, True)["status"] == "good"

    # Saman päivän neuvot: herkkuvoittoinen + proteiinivaje
    adv = engine.today_food_advice(3200, 40, 1200, 2600, 180)
    assert adv and len(adv["tips"]) >= 2
    # Siisti päivä -> ei neuvoja
    assert engine.today_food_advice(2000, 160, 100, 2600, 180) is None


def test_alcohol_assessment():
    from app import engine
    from datetime import date, timedelta
    today = date(2026, 6, 30)
    # 4 juomapäivää, iso kertaryöppy (~72 g = 6 tuoppia)
    drink_days = [today - timedelta(days=d) for d in (2, 9, 16, 23)]
    events = [(d, 72.0) for d in drink_days]
    # Aamut: juomapäivän JÄLKEEN huono HRV/uni/korkea syke, muuten hyvä
    nights = {}
    for i in range(30):
        d = today - timedelta(days=i)
        after = (d - timedelta(days=1)) in set(drink_days)
        nights[d] = {"hrv": 45 if after else 62, "rhr": 60 if after else 52,
                     "sleep": 6.0 if after else 7.6}
    a = engine.alcohol_assessment(events, nights, "mies", 85, today)
    assert a["any_use"] and a["binge_days"] == 4 and a["level"] == "korkea"
    assert a["drinks_30d"] > 20
    # Oma mitattu vaste tunnistaa HRV-laskun ja sykenousun
    assert a["measured_response"]["hrv"]["delta_pct"] < -5
    assert any("HRV" in n for n in a["measured_notes"])
    assert a["low_impact_drinks"] >= 1
    # Ei käyttöä -> siisti viesti
    none = engine.alcohol_assessment([], {}, "mies", 85, today)
    assert none["any_use"] is False
    # Nainen sietää vähemmän (matalampi binge-raja)
    aw = engine.alcohol_assessment(events, {}, "nainen", 62, today)
    assert aw["binge_threshold_g"] == 48


def test_set_performance_review():
    from app import engine
    inc = 2.5
    # Romahdus: tavoite 12, tehtiin 12,9,6,4,3 -> laske painoa
    sets = [{"weight": 60, "reps": r, "completed": True} for r in (12, 9, 6, 4, 3)]
    r = engine.set_performance_review(sets, 12, inc,
                                      last_top={"weight": 60, "reps": 12}, last_reps_at_weight=48)
    assert r["verdict"] == "reduce" and r["ask_reduce"] and r["suggested_weight"] < 60
    # Tavoitetoistot täyttyivät -> korota +inc
    sets2 = [{"weight": 55, "reps": 12, "completed": True} for _ in range(4)]
    r2 = engine.set_performance_review(sets2, 12, inc)
    assert r2["verdict"] == "increase" and r2["suggested_weight"] == 57.5
    # Enemmän toistoja samalla painolla kuin viimeksi -> kannustava vertailu
    sets3 = [{"weight": 50, "reps": r, "completed": True} for r in (10, 10, 9)]
    r3 = engine.set_performance_review(sets3, 12, inc,
                                       last_top={"weight": 50, "reps": 8}, last_reps_at_weight=24)
    assert r3["compare"] and "enemmän" in r3["compare"]
    # Tasainen suoritus alle tavoitteen mutta ei romahdusta -> hold
    sets4 = [{"weight": 50, "reps": r, "completed": True} for r in (10, 10, 9, 9)]
    r4 = engine.set_performance_review(sets4, 12, inc)
    assert r4["verdict"] == "hold"


def test_resolve_tdee_stability():
    from app import engine
    base = 2600.0
    # Liian vähän dataa -> perusarvio, ei adaptiivinen (ei hätiköintiä)
    r = engine.resolve_tdee(base, 3500, 0.0, 21, intake_day_count=2,
                            weight_point_count=6, weight_span_days=20)
    assert r["source"] == "perusarvio" and r["tdee"] == round(base)
    assert any("kirjaa ruokaa" in n for n in r["data_needs"])
    # Painodataa liian vähän -> perusarvio
    r2 = engine.resolve_tdee(base, 2500, 0.0, 21, intake_day_count=12,
                             weight_point_count=1, weight_span_days=5)
    assert r2["source"] == "perusarvio"
    # Tarpeeksi dataa -> adaptiivinen, mutta RAJATTU perusarvion ympärille
    r3 = engine.resolve_tdee(base, 2400, 0.0, 21, intake_day_count=12,
                             weight_point_count=8, weight_span_days=20)
    assert r3["source"].startswith("adaptiivinen") and r3["confidence"] == "korkea"
    # Absurdi syönti ei saa nostaa yli ~perusarvio*1.18 (clamp + blend)
    r4 = engine.resolve_tdee(base, 6000, 0.0, 21, intake_day_count=15,
                             weight_point_count=8, weight_span_days=20)
    assert r4["tdee"] <= round(base * 1.18) + 1
    # Absurdin matala ei saa laskea alle ~perusarvio*0.82
    r5 = engine.resolve_tdee(base, 800, 0.0, 21, intake_day_count=15,
                             weight_point_count=8, weight_span_days=20)
    assert r5["tdee"] >= round(base * 0.82) - 1


def test_set_review_increase_then_decline_is_normal():
    """Käyttäjän ydinongelma: korotuksen jälkeen laskevat sarjat EIVÄT saa
    aiheuttaa laskuehdotusta — tavoitellaan täysiä sarjoja uudella painolla."""
    from app import engine as E
    inc = 2.5
    S = lambda w, reps: [{"weight": w, "reps": x, "completed": True} for x in reps]
    # 1) Juuri korotettu 100->102.5, sarjat 8,7,7,6 (tavoite 8) -> HOLD, ei laskua
    r = E.set_performance_review(S(102.5, [8, 7, 7, 6]), 8, inc,
                                 {"weight": 100, "reps": 8}, 32)
    assert r["verdict"] == "hold" and not r["ask_reduce"] and r["recently_increased"]
    assert "korota taas" in r["reason"].lower() or "tavoittele" in r["reason"].lower()
    # 2) Tuore aloitus 4,4,3,2 (tavoite 8) -> selvästi liikaa -> REDUCE
    r2 = E.set_performance_review(S(60, [4, 4, 3, 2]), 8, inc)
    assert r2["verdict"] == "reduce" and r2["suggested_weight"] < 60
    # 3) Eristävä 12,10,9 (tavoite 12) -> OK, ei laskua
    r3 = E.set_performance_review(S(12, [12, 10, 9]), 12, inc, {"weight": 12, "reps": 36}, 33)
    assert r3["verdict"] == "hold" and not r3["ask_reduce"]
    # 4) Eristävä 12,8,5 (tavoite 12) -> selvä romahdus -> REDUCE
    r4 = E.set_performance_review(S(12, [12, 8, 5]), 12, inc, {"weight": 12, "reps": 33}, 33)
    assert r4["verdict"] == "reduce"
    # 5) Lievä takapakki samalla painolla (8,7,6,6 vs 32) -> HOLD, katso lepo (ei laskua)
    r5 = E.set_performance_review(S(100, [8, 7, 6, 6]), 8, inc, {"weight": 100, "reps": 8}, 32)
    assert r5["verdict"] == "hold" and not r5["ask_reduce"]
    assert "lepo" in r5["reason"].lower() or "uni" in r5["reason"].lower()
    # 6) Sama takapakki dieetillä -> normaalia dieetillä
    r6 = E.set_performance_review(S(100, [8, 7, 6, 6]), 8, inc, {"weight": 100, "reps": 8}, 32, on_cut=True)
    assert r6["verdict"] == "hold" and "dieet" in r6["reason"].lower()
    # 7) Liian iso korotus joka romahti (5,4,3,3, tavoite 8) -> REDUCE + palaa-vinkki
    r7 = E.set_performance_review(S(105, [5, 4, 3, 3]), 8, inc, {"weight": 100, "reps": 8}, 32)
    assert r7["verdict"] == "reduce"


def test_forecast_plateau_is_flat_but_credits_real_progress():
    """Käyttäjän ongelma: usea kerta samalla painolla EI saa tuottaa
    systemaattista nousuennustetta, mutta aito toisto-/painokehitys pitää nähdä."""
    from datetime import date, timedelta
    from app import engine as E
    base = date(2025, 1, 1)

    def hist(vals):
        return [(base + timedelta(days=i * 7), v) for i, v in enumerate(vals)]

    def y1(vals):
        h = hist(vals)
        conf = E.forecast_confidence(len(h), (h[-1][0] - h[0][0]).days)
        bt = E.backtest_forecast(h)
        fc = E.forecast_progress(h, 52, ceiling=None, confidence=conf,
                                 rate_calibration=bt["rate_ratio"], error_scale=bt["error_scale"])
        return h[-1][1], fc[-1]["mid"]

    def e(w, reps, rir=1):
        return round(E.estimate_1rm(w, reps, rir), 1)

    # Tasanne: sama paino, toistot heiluvat 3-5 -> ennuste käytännössä tasainen
    plateau = [e(100, 4), e(100, 3), e(100, 5), e(100, 4), e(100, 4),
               e(100, 3), e(100, 5), e(100, 4), e(100, 4), e(100, 5)]
    cur, fut = y1(plateau)
    assert abs(fut - cur) <= 2.0, f"tasanne ei saa nousta systemaattisesti: {cur}->{fut}"

    # Yksi hyvä päivä tasanteen lopussa ei saa laukaista vuoden nousua
    spike = plateau[:-1] + [e(100, 7)]
    cur, fut = y1(spike)
    assert abs(fut - cur) <= 2.0, f"yksi piikki ei saa tuottaa nousuennustetta: {cur}->{fut}"

    # Aito toistokehitys (3->7) -> ennusteen pitää nousta selvästi
    prog = [e(100, 3), e(100, 3), e(100, 4), e(100, 4), e(100, 5),
            e(100, 5), e(100, 6), e(100, 6), e(100, 7), e(100, 7)]
    cur, fut = y1(prog)
    assert fut - cur >= 4.0, f"aito toistokehitys pitää nähdä nousuna: {cur}->{fut}"


def test_robust_rate_ignores_single_outlier():
    from app import engine as E
    # Tasainen data + yksi iso poikkeama -> robusti tahti pysyy lähellä nollaa
    flat = [(i * 7, 100.0) for i in range(8)]
    flat_spike = flat[:-1] + [(49, 130.0)]
    assert abs(E._robust_rate(flat_spike)) < 0.05
    # OLS reagoi poikkeamaan selvästi enemmän (osoittaa miksi robusti on parempi)
    assert E._linear_rate(flat_spike) > E._robust_rate(flat_spike)
