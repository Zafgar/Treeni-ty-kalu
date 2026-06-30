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


def _exercise_session_points(
    db: Session, exercise_id: int, profile_id: int | None = None
) -> list[dict]:
    """Aikasarja: per treenipäivä paras arvioitu 1RM, paras sarja ja volyymi."""
    q = (
        db.query(models.WorkoutExercise, models.WorkoutSession)
        .join(models.WorkoutSession, models.WorkoutExercise.session_id == models.WorkoutSession.id)
        .filter(models.WorkoutExercise.exercise_id == exercise_id)
    )
    if profile_id is not None:
        q = q.filter(models.WorkoutSession.profile_id == profile_id)
    # Skipattuja treenejä ei lasketa kehitykseen.
    q = q.filter(models.WorkoutSession.status != "skipped")
    rows = q.order_by(models.WorkoutSession.session_date).all()
    # Yhdistä saman päivän treenit (jos sama liike useassa treenissä per päivä)
    by_date: dict[date, dict] = {}
    for we, session in rows:
        sets = _sets_payload(we)
        best = engine.best_1rm_from_sets(sets)
        volume = sum(s["weight"] * s["reps"] for s in sets if s["completed"])
        # Vähennä pikakirjattu vajaus volyymistä työpainolla, jotta samalla
        # painolla tehty sarjojen suoritus näkyy oikein kehityskäyrällä.
        if we.missed_reps:
            top_w = max((s["weight"] for s in sets if s["completed"]), default=0.0)
            volume = max(0.0, volume - we.missed_reps * top_w)
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


def _latest_bodyweight(db: Session, profile_id: int | None) -> float | None:
    if profile_id is None:
        return None
    b = (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == profile_id, models.BodyEntry.bodyweight.isnot(None))
        .order_by(models.BodyEntry.entry_date.desc())
        .first()
    )
    return b.bodyweight if b else None


@router.get("/exercises/{exercise_id}/history")
def exercise_history(
    exercise_id: int,
    profile_id: int | None = Query(None),
    window_days: int = Query(DEFAULT_WINDOW_DAYS),
    forecast: bool = Query(True),
    horizon_weeks: int = Query(26),
    db: Session = Depends(get_db),
):
    """Yhden liikkeen kehityskäyrä + ennätykset + realistinen ennuste."""
    ex = db.get(models.Exercise, exercise_id)
    points = _exercise_session_points(db, exercise_id, profile_id)
    records = _records_for_exercise(points, window_days)

    # Ennuste vain pääliikkeille (tunnistettu kyykky/penkki/mave/pystypunnerrus
    # tai is_main_lift) — apuliikkeiden ennuste ei ole hyödyllinen.
    forecast_points = []
    lift_key = engine.classify_lift(ex.name) if ex else None
    is_main = bool(lift_key) or (ex.is_main_lift if ex else False)
    if forecast and is_main and len([p for p in points if p["estimated_1rm"] > 0]) >= 2:
        # Katto naturaalinostajan realistisesta huipusta (jos paino tunnetaan)
        ceiling = None
        bw = _latest_bodyweight(db, profile_id)
        if lift_key and bw:
            profile = db.get(models.Profile, profile_id) if profile_id else None
            ceiling = engine.natural_ceiling(lift_key, bw, profile.sex if profile else None)
        history = [(p["date"], p["estimated_1rm"]) for p in points if p["estimated_1rm"] > 0]
        forecast_points = engine.forecast_progress(history, horizon_weeks, ceiling)

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
        "forecast": forecast_points,
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
    profile_id: int | None = Query(None),
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
        points = _exercise_session_points(db, ex.id, profile_id)
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
    profile_id: int | None = Query(None),
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
        points = _exercise_session_points(db, ex.id, profile_id)
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


@router.get("/exercises/{exercise_id}/last")
def exercise_last(
    exercise_id: int, profile_id: int | None = Query(None), db: Session = Depends(get_db)
):
    """Liikearkisto: viimeksi käytetty paino ja ehdotetut raudat eri toistoille.

    Käytetään kun liike lisätään treeniin -> esitäyttö edellisellä painolla.
    1RM-arviota ei korosteta (ei kiinnosta joka liikkeessä), vaan sopivat
    painot eri sarjamäärille.
    """
    points = _exercise_session_points(db, exercise_id, profile_id)
    valid = [p for p in points if p["best_set"]]
    if not valid:
        return {"exercise_id": exercise_id, "last": None, "suggestions": {}}
    last = max(valid, key=lambda p: p["date"])
    bs = last["best_set"]
    one_rm = engine.estimate_1rm(bs["weight"], bs["reps"], bs.get("rir"))
    suggestions = {
        str(r): engine.round_to_increment(engine.weight_for_reps(one_rm, r, bs.get("rir")))
        for r in (1, 3, 5, 8, 10, 12)
    }
    return {
        "exercise_id": exercise_id,
        "last": {
            "date": last["date"].isoformat(),
            "weight": bs["weight"], "reps": bs["reps"], "rir": bs.get("rir"),
        },
        "suggestions": suggestions,
    }


@router.get("/exercises/{exercise_id}/suggest")
def exercise_suggest(
    exercise_id: int,
    target_reps: int = Query(5),
    target_rir: float | None = Query(None),
    increase: bool = Query(False),
    profile_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Ehdota seuraavan kerran paino tehdyn perusteella.

    Jos increase = true (käyttäjä aikoo korottaa), lisätään pieni nousu kun
    edellinen suoritus meni täysillä; muuten ehdotetaan toistomäärää vastaava
    paino. Käyttäjä voi hyväksyä tai määrittää itse.
    """
    points = _exercise_session_points(db, exercise_id, profile_id)
    valid = [p for p in points if p["best_set"]]
    if not valid:
        return {"suggested_weight": None, "note": "Ei aiempaa dataa tälle liikkeelle."}
    last = max(valid, key=lambda p: p["date"])
    bs = last["best_set"]
    one_rm = engine.estimate_1rm(bs["weight"], bs["reps"], bs.get("rir"))
    rir = target_rir if target_rir is not None else bs.get("rir")
    base = engine.weight_for_reps(one_rm, target_reps, rir)
    if increase:
        base *= 1.025  # ~2.5 % nosto kun aikoo korottaa
    suggested = engine.round_to_increment(base)
    return {
        "suggested_weight": suggested,
        "from": {"weight": bs["weight"], "reps": bs["reps"], "date": last["date"].isoformat()},
        "note": (
            f"Edellinen paras: {bs['weight']} kg × {bs['reps']}. "
            f"Ehdotus {target_reps} toistolle" + (" (korotettu)" if increase else "") + f": {suggested} kg."
        ),
    }


@router.get("/load-timeline")
def load_timeline(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Kokonaisrauta: per treenipäivä siirretty kokonais-kg, toistot ja sarjat,
    yhdistettynä painoon ja kaloreihin samalle aikajanalle vertailua varten."""
    wq = db.query(models.WorkoutSession).filter(models.WorkoutSession.status != "skipped")
    if profile_id is not None:
        wq = wq.filter(models.WorkoutSession.profile_id == profile_id)
    sessions = wq.order_by(models.WorkoutSession.session_date).all()

    by_date: dict[date, dict] = {}
    for s in sessions:
        agg = by_date.setdefault(s.session_date,
                                 {"total_kg": 0.0, "reps": 0, "sets": 0, "kcal_burned": 0.0, "duration_min": 0})
        if s.kcal_burned:
            agg["kcal_burned"] += s.kcal_burned
        if s.duration_min:
            agg["duration_min"] += s.duration_min
        for we in s.exercises:
            top_w = max((st.weight for st in we.sets if st.completed), default=0.0)
            for st in we.sets:
                if st.completed:
                    agg["total_kg"] += st.weight * st.reps
                    agg["reps"] += st.reps
                    agg["sets"] += 1
            if we.missed_reps:
                agg["total_kg"] = max(0.0, agg["total_kg"] - we.missed_reps * top_w)
                agg["reps"] = max(0, agg["reps"] - we.missed_reps)

    # Paino ja kalorit samalle aikajanalle
    body = {b.entry_date: b for b in db.query(models.BodyEntry).filter(
        models.BodyEntry.profile_id == profile_id).all()} if profile_id else {}
    kcal_by_date: dict[date, float] = {}
    if profile_id is not None:
        for fl in db.query(models.FoodLog).filter(models.FoodLog.profile_id == profile_id).all():
            kcal_by_date[fl.entry_date] = kcal_by_date.get(fl.entry_date, 0.0) + fl.food.kcal * fl.grams / 100.0

    timeline = []
    for d in sorted(by_date):
        agg = by_date[d]
        b = body.get(d)
        timeline.append({
            "date": d.isoformat(),
            "total_kg": round(agg["total_kg"], 1),
            "reps": agg["reps"],
            "sets": agg["sets"],
            "kcal_burned": round(agg["kcal_burned"]) if agg["kcal_burned"] else None,
            "duration_min": agg["duration_min"] or None,
            "bodyweight": b.bodyweight if b else None,
            "kcal": round(kcal_by_date.get(d), 0) if d in kcal_by_date else None,
        })
    return timeline


@router.get("/levels")
def levels(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Voimatasot pääliikkeille (8 porrasta) kehon painoon suhteutettuna."""
    bw = _latest_bodyweight(db, profile_id)
    profile = db.get(models.Profile, profile_id) if profile_id else None
    sex = profile.sex if profile else None
    result = []
    for ex in db.query(models.Exercise).filter(models.Exercise.is_main_lift.is_(True)).all():
        lift_key = engine.classify_lift(ex.name)
        if not lift_key:
            continue
        points = _exercise_session_points(db, ex.id, profile_id)
        rec = _records_for_exercise(points, DEFAULT_WINDOW_DAYS)
        if not rec or not bw:
            continue
        lvl = engine.strength_level(lift_key, rec["current_1rm"], bw, sex)
        if lvl:
            result.append({"exercise_name": ex.name, "current_1rm": rec["current_1rm"],
                           "bodyweight": bw, **lvl})
    return {"bodyweight": bw, "all_levels": engine.STRENGTH_LEVELS, "lifts": result}


# Metriikat joita voi korreloida (nimi -> kuvaus)
CORRELATION_METRICS = {
    "bodyweight": "Kehon paino",
    "kcal": "Kalorit (syöty)",
    "sleep_hours": "Uni (h)",
    "sleep_score": "Unipisteet",
    "hrv": "HRV",
    "resting_hr": "Leposyke",
    "tonnage": "Kokonaisrauta (kg)",
    "workout_kcal": "Treenin kcal",
    "duration_min": "Treenin kesto (min)",
}


def _weekly_series(by_date: dict, dates: list) -> dict:
    """Muodosta viikoittainen keskiarvosarja päiväkohtaisesta datasta."""
    from collections import defaultdict
    weeks = defaultdict(list)
    for d in dates:
        if d in by_date and by_date[d] is not None:
            iso = d.isocalendar()
            weeks[(iso[0], iso[1])].append(by_date[d])
    return {wk: sum(v) / len(v) for wk, v in weeks.items()}


@router.get("/correlation/metrics")
def correlation_metrics():
    return CORRELATION_METRICS


@router.get("/correlation")
def correlation(
    a: str = Query(...), b: str = Query(...),
    profile_id: int = Query(...), db: Session = Depends(get_db),
):
    """Kahden muuttujan viikkotason korrelaatio + normalisoidut sarjat overlaylle."""
    def metric_by_date(metric: str) -> dict:
        out: dict = {}
        if metric == "kcal":
            for fl in db.query(models.FoodLog).filter(models.FoodLog.profile_id == profile_id).all():
                out[fl.entry_date] = out.get(fl.entry_date, 0.0) + fl.food.kcal * fl.grams / 100.0
        elif metric in ("tonnage", "workout_kcal", "duration_min"):
            wq = db.query(models.WorkoutSession).filter(
                models.WorkoutSession.profile_id == profile_id,
                models.WorkoutSession.status != "skipped")
            for s in wq.all():
                if metric == "workout_kcal":
                    if s.kcal_burned:
                        out[s.session_date] = out.get(s.session_date, 0.0) + s.kcal_burned
                elif metric == "duration_min":
                    if s.duration_min:
                        out[s.session_date] = out.get(s.session_date, 0.0) + s.duration_min
                else:
                    tot = 0.0
                    for we in s.exercises:
                        top_w = max((st.weight for st in we.sets if st.completed), default=0.0)
                        tot += sum(st.weight * st.reps for st in we.sets if st.completed)
                        if we.missed_reps:
                            tot = max(0.0, tot - we.missed_reps * top_w)
                    out[s.session_date] = out.get(s.session_date, 0.0) + tot
        else:
            for e in db.query(models.BodyEntry).filter(models.BodyEntry.profile_id == profile_id).all():
                val = getattr(e, metric, None)
                if val is not None:
                    out[e.entry_date] = val
        return out

    a_data, b_data = metric_by_date(a), metric_by_date(b)
    all_dates = sorted(set(a_data) | set(b_data))
    a_weekly = _weekly_series(a_data, all_dates)
    b_weekly = _weekly_series(b_data, all_dates)
    common = sorted(set(a_weekly) & set(b_weekly))
    xs = [a_weekly[w] for w in common]
    ys = [b_weekly[w] for w in common]
    r = engine.pearson(xs, ys)

    from datetime import date as _date
    series = [{"week": f"{w[0]}-{w[1]:02d}",
               "date": _date.fromisocalendar(w[0], w[1], 1).isoformat(),
               "a": round(a_weekly[w], 1), "b": round(b_weekly[w], 1)} for w in common]
    return {
        "a": a, "b": b, "a_label": CORRELATION_METRICS.get(a, a),
        "b_label": CORRELATION_METRICS.get(b, b),
        "pearson": r, "n": len(common), "series": series,
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
def overview(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Yleisnäkymä: tunnusluvut, viimeisimmät treenit ja kärkiennätykset."""
    wq = db.query(models.WorkoutSession)
    pq = db.query(models.Program)
    if profile_id is not None:
        wq = wq.filter(models.WorkoutSession.profile_id == profile_id)
        pq = pq.filter(models.Program.profile_id == profile_id)
    total_workouts = wq.count()
    total_exercises = db.query(models.Exercise).count()
    total_programs = pq.count()
    recent_sessions = (
        wq.order_by(models.WorkoutSession.session_date.desc(), models.WorkoutSession.id.desc())
        .limit(5)
        .all()
    )
    recent = [
        {"id": s.id, "date": s.session_date.isoformat(), "name": s.name,
         "exercises": len(s.exercises), "feeling": s.feeling}
        for s in recent_sessions
    ]
    # Merkityt fiilikset (positiiviset/negatiiviset) — auttaa huomaamaan ongelmat
    flagged_q = wq.filter(models.WorkoutSession.feeling.in_(["positive", "negative"]))
    flagged = [
        {"id": s.id, "date": s.session_date.isoformat(), "name": s.name,
         "feeling": s.feeling, "feeling_note": s.feeling_note}
        for s in flagged_q.order_by(models.WorkoutSession.session_date.desc()).limit(8).all()
    ]
    return {
        "total_workouts": total_workouts,
        "total_exercises": total_exercises,
        "total_programs": total_programs,
        "recent_workouts": recent,
        "flagged_feelings": flagged,
    }
