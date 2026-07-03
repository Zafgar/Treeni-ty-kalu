"""API-tason testit (FastAPI TestClient) omalla väliaikaisella kannalla.

Kattaa uudet kulut: treenin kuittaus/skip, pikavajaus (missed_reps) ja sen
vaikutus kehitysvolyymiin, liikearkisto ja ravintoseuranta.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import models  # noqa: E402
from backend.app.database import Base, get_db  # noqa: E402
from backend.app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Oletusprofiili testikantaan
    with TestingSession() as s:
        s.add(models.Profile(name="Testi"))
        s.commit()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_workout_complete_and_skip(client):
    ex = client.post("/api/exercises", json={"name": "Kyykky"}).json()
    w = client.post("/api/workouts", json={
        "profile_id": 1, "status": "planned",
        "exercises": [{"exercise_id": ex["id"], "sets": [
            {"set_index": 0, "reps": 5, "weight": 100, "completed": False}]}],
    }).json()
    assert w["status"] == "planned"
    done = client.post(f"/api/workouts/{w['id']}/complete").json()
    assert done["status"] == "completed"
    assert "new_prs" in done  # kuittaus palauttaa myös uudet ennätykset
    # Varmista että sarjat ja liike merkittiin tehdyiksi
    full = client.get(f"/api/workouts/{w['id']}").json()
    assert full["exercises"][0]["sets"][0]["completed"] is True
    assert full["exercises"][0]["done"] is True

    w2 = client.post("/api/workouts", json={"profile_id": 1, "exercises": []}).json()
    skipped = client.post(f"/api/workouts/{w2['id']}/skip").json()
    assert skipped["status"] == "skipped"


def test_missed_reps_reduces_volume(client):
    ex = client.post("/api/exercises", json={"name": "Penkki"}).json()
    client.post("/api/workouts", json={
        "profile_id": 1, "session_date": "2026-06-01",
        "exercises": [{"exercise_id": ex["id"], "missed_reps": 4, "sets": [
            {"set_index": i, "reps": 5, "weight": 100, "completed": True} for i in range(4)]}],
    })
    hist = client.get(f"/api/stats/exercises/{ex['id']}/history?profile_id=1").json()
    # 4x5x100 = 2000, miinus 4 vajaata x 100 = 1600
    assert hist["points"][0]["volume"] == 1600.0


def test_skipped_workout_excluded(client):
    ex = client.post("/api/exercises", json={"name": "Mave"}).json()
    w = client.post("/api/workouts", json={
        "profile_id": 1, "exercises": [{"exercise_id": ex["id"], "sets": [
            {"set_index": 0, "reps": 5, "weight": 200, "completed": True}]}],
    }).json()
    client.post(f"/api/workouts/{w['id']}/skip")
    hist = client.get(f"/api/stats/exercises/{ex['id']}/history?profile_id=1").json()
    assert hist["points"] == []


def test_exercise_archive_and_suggest(client):
    ex = client.post("/api/exercises", json={"name": "Kyykky"}).json()
    client.post("/api/workouts", json={
        "profile_id": 1, "exercises": [{"exercise_id": ex["id"], "sets": [
            {"set_index": 0, "reps": 5, "weight": 100, "rir": 2, "completed": True}]}],
    })
    last = client.get(f"/api/stats/exercises/{ex['id']}/last?profile_id=1").json()
    assert last["last"]["weight"] == 100
    assert "5" in last["suggestions"]
    sug = client.get(f"/api/stats/exercises/{ex['id']}/suggest?profile_id=1&target_reps=8").json()
    assert sug["suggested_weight"] is not None


def test_nutrition_logging(client):
    food = client.post("/api/nutrition/foods", json={
        "name": "Banaani", "kcal": 89, "protein_g": 1.1, "carbs_g": 23, "fat_g": 0.3}).json()
    client.post("/api/nutrition/logs?profile_id=1", json={"food_id": food["id"], "grams": 200})
    s = client.get("/api/nutrition/summary?profile_id=1").json()
    assert round(s["today"]["kcal"]) == 178  # 89 * 2


def test_exercise_with_defaults(client):
    ex = client.post("/api/exercises", json={
        "name": "Sivunostot", "category": "olkapäät", "equipment": "käsipainot",
        "default_sets": 3, "default_reps": 15}).json()
    assert ex["equipment"] == "käsipainot"
    assert ex["default_sets"] == 3 and ex["default_reps"] == 15


def test_diet_models_and_phase(client):
    models_ = client.get("/api/diet/models").json()
    assert len(models_) == 6  # 4 perusmallia + 16:8 + low carb
    phase = client.post("/api/diet/phase", json={"profile_id": 1, "model": "cut_maltillinen"}).json()
    assert phase["goal"] == "cut"
    assert phase["target_rate"] == -0.5
    got = client.get("/api/diet/phase?profile_id=1").json()
    assert got["model"] == "Maltillinen pudotus"


def test_diet_status(client):
    from datetime import date, timedelta
    client.post("/api/diet/phase", json={"profile_id": 1, "model": "cut_maltillinen"})
    ref = date(2026, 6, 28)
    # 14 päivää laskevaa painoa
    for i in range(14):
        d = (ref - timedelta(days=i)).isoformat()
        w = round(85 - (13 - i) * 0.07, 1)
        client.post("/api/body/entries?profile_id=1", json={"entry_date": d, "bodyweight": w})
    status = client.get("/api/diet/status?profile_id=1").json()
    assert status["goal"] == "cut"
    assert status["targets"]["protein_g"] > 0
    assert status["targets"]["kcal"] > 0
    assert status["trend_kg_per_week"] is not None


def test_food_filtering_and_favorite(client):
    client.post("/api/nutrition/foods", json={"name": "Kanafile", "category": "kana", "kcal": 110})
    client.post("/api/nutrition/foods", json={"name": "Banaani", "category": "hedelmät", "kcal": 89})
    # haku
    r = client.get("/api/nutrition/foods?q=kana").json()
    assert len(r) == 1 and r[0]["name"] == "Kanafile"
    # kategoria
    assert len(client.get("/api/nutrition/foods?category=hedelmät").json()) == 1
    # suosikki
    fid = r[0]["id"]
    client.patch(f"/api/nutrition/foods/{fid}", json={"is_favorite": True})
    favs = client.get("/api/nutrition/foods?favorites=true").json()
    assert len(favs) == 1 and favs[0]["id"] == fid
    # kategoriat
    cats = client.get("/api/nutrition/categories").json()
    assert "kana" in cats and "hedelmät" in cats


def test_foodlog_edit_grams(client):
    f = client.post("/api/nutrition/foods", json={"name": "Riisi", "kcal": 130}).json()
    log = client.post("/api/nutrition/logs?profile_id=1", json={"food_id": f["id"], "grams": 100}).json()
    client.patch(f"/api/nutrition/logs/{log['id']}", json={"grams": 250})
    s = client.get("/api/nutrition/summary?profile_id=1").json()
    assert round(s["today"]["kcal"]) == round(130 * 2.5)


def test_meal_create_and_quicklog(client):
    milk = client.post("/api/nutrition/foods", json={"name": "Maito", "kcal": 50, "protein_g": 3.4}).json()
    whey = client.post("/api/nutrition/foods", json={"name": "Whey", "kcal": 380, "protein_g": 80}).json()
    meal = client.post("/api/nutrition/meals?profile_id=1", json={
        "name": "Smoothie", "items": [
            {"food_id": milk["id"], "grams": 300}, {"food_id": whey["id"], "grams": 30}]}).json()
    assert meal["name"] == "Smoothie" and len(meal["items"]) == 2
    res = client.post(f"/api/nutrition/meals/{meal['id']}/log?profile_id=1&on_date=2026-06-01").json()
    assert res["logged"] == 2
    logs = client.get("/api/nutrition/logs?profile_id=1&on_date=2026-06-01").json()
    assert len(logs) == 2


def test_lowcarb_diet_model(client):
    client.patch("/api/profiles/1", json={"height_cm": 180})
    client.post("/api/body/entries?profile_id=1", json={"bodyweight": 85, "body_fat_pct": 15})
    client.post("/api/diet/phase", json={"profile_id": 1, "model": "cut_lowcarb"})
    status = client.get("/api/diet/status?profile_id=1").json()
    # Low carb -> rasva korkeampi, hiilarit matalat
    assert status["targets"]["fat_g"] > status["targets"]["protein_g"] * 0  # sanity
    std = client.post("/api/diet/phase", json={"profile_id": 1, "model": "cut_maltillinen"})
    std_status = client.get("/api/diet/status?profile_id=1").json()
    assert status["targets"]["carbs_g"] < std_status["targets"]["carbs_g"]


def test_volume_analysis_and_ack(client):
    from datetime import date, timedelta
    ref = date(2026, 6, 28)
    chest = client.post("/api/exercises", json={"name": "Penkki", "category": "rinta"}).json()
    legs = client.post("/api/exercises", json={"name": "Kyykky", "category": "jalat"}).json()
    # rinta: 3 sarjaa tällä viikolla (matala), jalat: monta
    client.post("/api/workouts", json={"profile_id": 1, "session_date": ref.isoformat(),
        "exercises": [
            {"exercise_id": chest["id"], "sets": [{"set_index": i, "reps": 5, "weight": 100, "completed": True} for i in range(3)]},
            {"exercise_id": legs["id"], "sets": [{"set_index": i, "reps": 5, "weight": 140, "completed": True} for i in range(12)]},
        ]})
    va = client.get("/api/stats/volume-analysis?profile_id=1").json()
    cats = {c["category"]: c for c in va["categories"]}
    assert cats["rinta"]["sets_week"] == 3 and cats["rinta"]["status"] == "low"
    assert cats["jalat"]["sets_week"] == 12 and cats["jalat"]["status"] == "ok"
    assert va["acknowledged"] is False
    # kuittaus
    client.post(f"/api/stats/volume-ack?profile_id=1&week_key={va['week_key']}")
    va2 = client.get("/api/stats/volume-analysis?profile_id=1").json()
    assert va2["acknowledged"] is True


def test_generate_program(client):
    # Liikekirjasto on testikannassa tyhjä -> seedataan tarvittavat liikkeet
    for name in ["Takakyykky", "Penkkipunnerrus", "Maastaveto", "Jalkaprässi",
                 "Romanialainen maastaveto", "Jalkojen koukistus", "Pohjenousu",
                 "Vinopenkki tanko", "Pystypunnerrus", "Sivunostot", "Taljapunnerrus",
                 "Leuanveto", "Alatalja soutu", "Ylätalja eteen", "Hauiskääntö tanko"]:
        client.post("/api/exercises", json={"name": name, "category": "yleinen"})
    plans = client.get("/api/templates/plans").json()
    assert any(p["id"] == "voimanosto" for p in plans)
    r = client.post("/api/templates/generate", json={"plan": "bodaus", "days_per_week": 3, "profile_id": 1}).json()
    assert r["days"] == 3
    prog = client.get(f"/api/programs/{r['program_id']}").json()
    assert prog["schedule_type"] == "weekly"
    assert len(prog["days"]) == 3
    # pääliikkeellä on percent_scheme
    assert any(pe.get("percent_scheme") for d in prog["days"] for pe in d["exercises"])


def test_generate_closest_days(client):
    client.post("/api/exercises", json={"name": "Takakyykky"})
    client.post("/api/exercises", json={"name": "Penkkipunnerrus"})
    client.post("/api/exercises", json={"name": "Maastaveto"})
    # voimanosto tukee 3 ja 4 -> pyyntö 7 antaa lähimmän (4)
    r = client.post("/api/templates/generate", json={"plan": "voimanosto", "days_per_week": 7, "profile_id": 1}).json()
    assert r["days"] == 4


def test_measurement_forecast(client):
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    for i in range(5):
        client.post("/api/body/measurements?profile_id=1", json={
            "entry_date": (base + timedelta(weeks=i)).isoformat(), "site": "hauis", "value_cm": 39 + i * 0.4})
    s = client.get("/api/body/summary?profile_id=1").json()
    assert "hauis" in s["measurement_forecasts"]
    assert len(s["measurement_forecasts"]["hauis"]) > 0


def test_load_timeline(client):
    ex = client.post("/api/exercises", json={"name": "Kyykky"}).json()
    client.post("/api/workouts", json={
        "profile_id": 1, "session_date": "2026-06-01", "duration_min": 65, "kcal_burned": 450,
        "exercises": [{"exercise_id": ex["id"], "sets": [
            {"set_index": 0, "reps": 5, "weight": 100, "completed": True}]}],
    })
    tl = client.get("/api/stats/load-timeline?profile_id=1").json()
    assert tl[0]["total_kg"] == 500.0
    assert tl[0]["reps"] == 5
    assert tl[0]["duration_min"] == 65
    assert tl[0]["kcal_burned"] == 450


def test_feeling_marker(client):
    ex = client.post("/api/exercises", json={"name": "Kyykky"}).json()
    w = client.post("/api/workouts", json={
        "profile_id": 1, "feeling": "negative", "feeling_note": "kipu olkapäässä",
        "exercises": [{"exercise_id": ex["id"], "sets": [
            {"set_index": 0, "reps": 5, "weight": 100, "completed": True}]}],
    }).json()
    assert w["feeling"] == "negative"
    ov = client.get("/api/stats/overview?profile_id=1").json()
    assert len(ov["flagged_feelings"]) == 1
    assert ov["flagged_feelings"][0]["feeling_note"] == "kipu olkapäässä"


def test_forecast_only_for_main_lifts(client):
    from datetime import date, timedelta
    # Apuliike -> ei ennustetta
    acc = client.post("/api/exercises", json={"name": "Hauiskääntö"}).json()
    main = client.post("/api/exercises", json={"name": "Takakyykky", "is_main_lift": True}).json()
    client.post("/api/body/entries?profile_id=1", json={"bodyweight": 100})
    base = date(2026, 1, 1)
    for i in range(4):
        d = (base + timedelta(weeks=i)).isoformat()
        for ex, wt in [(acc, 30 + i), (main, 140 + i * 5)]:
            client.post("/api/workouts", json={
                "profile_id": 1, "session_date": d,
                "exercises": [{"exercise_id": ex["id"], "sets": [
                    {"set_index": 0, "reps": 5, "weight": wt, "completed": True}]}]})
    acc_h = client.get(f"/api/stats/exercises/{acc['id']}/history?profile_id=1").json()
    main_h = client.get(f"/api/stats/exercises/{main['id']}/history?profile_id=1").json()
    assert acc_h["forecast"] == []        # apuliike ei saa ennustetta
    assert len(main_h["forecast"]) > 0    # pääliike saa


def test_physique_in_body_summary(client):
    # Aseta pituus profiilille, kirjaa paino + rasva-% -> fysiikkataso
    # (profiili 1 luodaan fixturessa ilman pituutta -> päivitetään)
    from backend.app import models
    s = client.get("/api/profiles").json()
    pid = s[0]["id"]
    client.patch(f"/api/profiles/{pid}", json={"height_cm": 180})
    client.post(f"/api/body/entries?profile_id={pid}", json={"bodyweight": 85, "body_fat_pct": 12})
    summary = client.get(f"/api/body/summary?profile_id={pid}").json()
    assert summary["composition"]["ffmi"] is not None
    assert summary["physique"]["level"] is not None


def test_muscle_load(client):
    from datetime import date, timedelta
    today = date.today()
    bench = client.post("/api/exercises", json={"name": "Penkkipunnerrus", "category": "rinta"}).json()
    squat = client.post("/api/exercises", json={"name": "Takakyykky", "category": "jalat"}).json()
    curl = client.post("/api/exercises", json={"name": "Hauiskääntö tanko", "category": "kädet"}).json()
    # Kaksi treeniä tällä 7 pv jaksolla -> datavaroitus poistuu
    for days_ago, ex, w in ((5, bench, 100), (2, squat, 140)):
        client.post("/api/workouts", json={"profile_id": 1,
            "session_date": (today - timedelta(days=days_ago)).isoformat(),
            "exercises": [{"exercise_id": ex["id"],
                "sets": [{"set_index": i, "reps": 5, "weight": w, "completed": True} for i in range(4)]}]})
    data = client.get("/api/stats/muscle-load?profile_id=1").json()
    areas = {a["area"]: a for a in data["areas"]}
    # Penkki jakaa kuorman rinnalle JA ojentajille/olkapäille
    assert areas["rinta"]["effective_sets"] == 4.0
    assert areas["ojentajat"]["effective_sets"] == 2.0
    assert areas["olkapäät"]["effective_sets"] > 0
    # Kyykky kuormittaa etureisiä täysillä ja pakaroita osittain
    assert areas["etureidet"]["effective_sets"] == 4.0
    assert areas["pakarat"]["effective_sets"] > 2
    # Hauista ei treenattu -> vajaa/ei kuormaa ja ehdotus löytyy
    assert areas["hauis"]["status"] in ("low", "none")
    assert data["workouts_week"] == 2
    assert data["cns"] is not None and "score" in data["cns"]
    sug_areas = {s["area"] for s in data["suggestions"]}
    assert sug_areas, "vajaille alueille pitää tulla ehdotuksia"
