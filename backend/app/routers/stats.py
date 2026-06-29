"""Kehityksen seuranta: ennätykset, per-liike-historia ja lajitotalit.

Tämänhetkisen 1RM:n sääntö (ratkaisee kahden ohjelman "kiistan"):
  - "current_1rm" = paras arvioitu 1RM tuoreen aikaikkunan sisällä
    (oletus 56 vrk liikkeen viimeisimmästä treenipäivästä). Recency voittaa,
    ja ikkunan sisällä otetaan paras tulos -> uusi ohjelma päivittää arvon
    automaattisesti kun tulos paranee, vanha jää historiaan.
  - "best_ever" = kaikkien aikojen paras arvioitu 1RM (säilyy erikseen).
Näin järjestelmä ei "kiistele" kahden ohjelman välillä: vain tuore aktiivinen
jakso määrää tämänhetkisen tason.
"""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import engine, models
from ..database import get_db

router = APIRouter(prefix="/api/stats", tags=["stats"])

DEFAULT_WINDOW_DAYS = 56


def _sets_payload(we: models.WorkoutExercise) -> list[dict]:
    return [
        {"weight": s.weight, "reps": s.reps, "rir": s.rir, "completed": s.completed}
        for s in we.sets
    ]


def _exercise_session_points(db: Session, exercise_id: int) -> list[dict]:
    """Aikasarja: per treenipäivä paras arvioitu 1RM, paras sarja ja volyymi."""
    rows = (
        db.query(models.WorkoutExercise, models.WorkoutSession)
        .join(models.WorkoutSession, models.WorkoutExercise.session_id == models.WorkoutSession.id)
        .filter(models.WorkoutExercise.exercise_id == exercise_id)
        .order_by(models.WorkoutSession.session_date)
        .all()
    )
    # Yhdistä saman päivän treenit (jos sama liike useassa treenissä per päivä)
    by_date: dict[date, dict] = {}
    for we, session in rows:
        sets = _sets_payload(we)
        best = engine.best_1rm_from_sets(sets)
        volume = sum(s["weight"] * s["reps"] for s in sets if s["completed"])
        d = session.session_date
        entry = by_date.setdefault(
            d,
            {"date": d, "estimated_1rm": 0.0, "best_set": None, "volume": 0.0,
             "program_day_id": session.program_day_id, "session_id": session.id},
        )
        entry["volume"] += volume
        if best and best["estimated_1rm"] > entry["estimated_1rm"]:
            entry["estimated_1rm"] = best["estimated_1rm"]
            entry["best_set"] = {"weight": best["weight"], "reps": best["reps"], "rir": best["rir"]}
    return [by_date[d] for d in sorted(by_date)]


def _records_for_exercise(points: list[dict], window_days: int) -> dict | None:
    """Laske best_ever ja current tuore-ikkuna-säännöllä."""
    valid = [p for p in points if p["estimated_1rm"] > 0]
    if not valid:
        return None
    best_ever = max(valid, key=lambda p: p["estimated_1rm"])
    last_date = max(p["date"] for p in valid)
    cutoff = last_date - timedelta(days=window_days)
    recent = [p for p in valid if p["date"] >= cutoff]
    current = max(recent, key=lambda p: p["estimated_1rm"]) if recent else best_ever
    return {
        "current_1rm": current["estimated_1rm"],
        "current_date": current["date"],
        "current_best_set": current["best_set"],
        "best_ever_1rm": best_ever["estimated_1rm"],
        "best_ever_date": best_ever["date"],
        "best_ever_set": best_ever["best_set"],
        "last_trained": last_date,
        "sessions": len(valid),
    }


@router.get("/exercises/{exercise_id}/history")
def exercise_history(
    exercise_id: int,
    window_days: int = Query(DEFAULT_WINDOW_DAYS),
    db: Session = Depends(get_db),
):
    """Yhden liikkeen kehityskäyrä + ennätykset."""
    ex = db.get(models.Exercise, exercise_id)
    points = _exercise_session_points(db, exercise_id)
    records = _records_for_exercise(points, window_days)
    return {
        "exercise_id": exercise_id,
        "exercise_name": ex.name if ex else None,
        "points": [
            {
                "date": p["date"].isoformat(),
                "estimated_1rm": p["estimated_1rm"],
                "volume": round(p["volume"], 1),
                "best_set": p["best_set"],
            }
            for p in points
        ],
        "records": _serialize_records(records),
    }


def _serialize_records(records: dict | None) -> dict | None:
    if not records:
        return None
    out = dict(records)
    for k in ("current_date", "best_ever_date", "last_trained"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    return out


@router.get("/records")
def records(
    main_only: bool = Query(False),
    window_days: int = Query(DEFAULT_WINDOW_DAYS),
    db: Session = Depends(get_db),
):
    """Ennätystaulukko kaikille (tai vain pää-) liikkeille."""
    q = db.query(models.Exercise)
    if main_only:
        q = q.filter(models.Exercise.is_main_lift.is_(True))
    result = []
    for ex in q.order_by(models.Exercise.name).all():
        points = _exercise_session_points(db, ex.id)
        rec = _records_for_exercise(points, window_days)
        if not rec:
            continue
        result.append({
            "exercise_id": ex.id,
            "exercise_name": ex.name,
            "is_main_lift": ex.is_main_lift,
            "sport": ex.sport,
            **_serialize_records(rec),
        })
    # Järjestä tuoreimman tason mukaan laskevasti
    result.sort(key=lambda r: r["current_1rm"], reverse=True)
    return result


@router.get("/total")
def total(
    sport: str = Query(...),
    window_days: int = Query(DEFAULT_WINDOW_DAYS),
    db: Session = Depends(get_db),
):
    """Lajitotal (esim. voimanosto): pääliikkeiden tämänhetkisten 1RM summa
    ala-/yläraja-arvioineen sekä total-kehityskäyrä ajan yli."""
    lifts = (
        db.query(models.Exercise)
        .filter(models.Exercise.sport == sport, models.Exercise.is_main_lift.is_(True))
        .order_by(models.Exercise.name)
        .all()
    )
    per_lift = []
    lift_timeseries: dict[str, list[dict]] = {}
    total_low = total_mid = total_high = 0.0
    for ex in lifts:
        points = _exercise_session_points(db, ex.id)
        rec = _records_for_exercise(points, window_days)
        lift_timeseries[ex.name] = points
        if not rec or not rec["current_best_set"]:
            per_lift.append({"exercise_name": ex.name, "current_1rm": rec["current_1rm"] if rec else 0,
                             "low": 0, "high": 0})
            if rec:
                total_mid += rec["current_1rm"]
                total_low += rec["current_1rm"]
                total_high += rec["current_1rm"]
            continue
        bs = rec["current_best_set"]
        rir_val = 1.0 if bs["rir"] is None else float(bs["rir"])
        e_mid = rec["current_1rm"]
        e_low = round(engine.estimate_1rm(bs["weight"], bs["reps"], max(0.0, rir_val - 1)), 1)
        e_high = round(engine.estimate_1rm(bs["weight"], bs["reps"], rir_val + 1), 1)
        per_lift.append({
            "exercise_name": ex.name, "current_1rm": e_mid, "low": e_low, "high": e_high,
            "current_date": rec["current_date"].isoformat() if rec["current_date"] else None,
        })
        total_low += e_low
        total_mid += e_mid
        total_high += e_high

    # Total-kehityskäyrä: yhdistetty päiväakseli, kullakin päivällä summa
    # kunkin liikkeen viimeisimmästä tunnetusta arviosta siihen mennessä.
    all_dates = sorted({p["date"] for pts in lift_timeseries.values() for p in pts})
    timeline = []
    last_known: dict[str, float] = {}
    for d in all_dates:
        for name, pts in lift_timeseries.items():
            for p in pts:
                if p["date"] == d and p["estimated_1rm"] > 0:
                    last_known[name] = p["estimated_1rm"]
        if last_known:
            timeline.append({"date": d.isoformat(), "total": round(sum(last_known.values()), 1)})

    return {
        "sport": sport,
        "total_low": round(total_low, 1),
        "total_mid": round(total_mid, 1),
        "total_high": round(total_high, 1),
        "per_lift": per_lift,
        "timeline": timeline,
    }


@router.get("/sports")
def sports(db: Session = Depends(get_db)):
    """Lajit joille on määritelty pääliikkeitä (totaleja varten)."""
    rows = (
        db.query(models.Exercise.sport)
        .filter(models.Exercise.is_main_lift.is_(True), models.Exercise.sport.isnot(None))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]})


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Yleisnäkymä: tunnusluvut, viimeisimmät treenit ja kärkiennätykset."""
    total_workouts = db.query(models.WorkoutSession).count()
    total_exercises = db.query(models.Exercise).count()
    total_programs = db.query(models.Program).count()
    recent_sessions = (
        db.query(models.WorkoutSession)
        .order_by(models.WorkoutSession.session_date.desc(), models.WorkoutSession.id.desc())
        .limit(5)
        .all()
    )
    recent = [
        {"id": s.id, "date": s.session_date.isoformat(), "name": s.name,
         "exercises": len(s.exercises)}
        for s in recent_sessions
    ]
    return {
        "total_workouts": total_workouts,
        "total_exercises": total_exercises,
        "total_programs": total_programs,
        "recent_workouts": recent,
    }
