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
    assert done["exercises"][0]["sets"][0]["completed"] is True
    assert done["exercises"][0]["done"] is True

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


def test_load_timeline(client):
    ex = client.post("/api/exercises", json={"name": "Kyykky"}).json()
    client.post("/api/workouts", json={
        "profile_id": 1, "session_date": "2026-06-01",
        "exercises": [{"exercise_id": ex["id"], "sets": [
            {"set_index": 0, "reps": 5, "weight": 100, "completed": True}]}],
    })
    tl = client.get("/api/stats/load-timeline?profile_id=1").json()
    assert tl[0]["total_kg"] == 500.0
    assert tl[0]["reps"] == 5
