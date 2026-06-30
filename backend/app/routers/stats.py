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


def _bodyweight_trend(db: Session, profile_id: int | None) -> float | None:
    """Painon muutos kg/viikko (viikkokeskiarvoista) ennusteen säätöä varten."""
    if profile_id is None:
        return None
    entries = (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == profile_id, models.BodyEntry.bodyweight.isnot(None))
        .order_by(models.BodyEntry.entry_date)
        .all()
    )
    points = [(e.entry_date, e.bodyweight) for e in entries]
    if len(points) < 2:
        return None
    return engine.weight_trend(points, max(d for d, _ in points))


HORIZON_CHECKPOINTS = [4, 12, 26, 52]


def _snapshot_forecast(db, profile_id, kind, ref, base_value, forecast_points):
    """Tallenna ennuste osuvuusvertailua varten (korkeintaan kerran/viikko per kohde)."""
    if profile_id is None or not forecast_points:
        return
    from datetime import date as _date, timedelta as _td
    recent = db.query(models.ForecastLog).filter(
        models.ForecastLog.profile_id == profile_id, models.ForecastLog.kind == kind,
        models.ForecastLog.ref == str(ref), models.ForecastLog.made_on >= _date.today() - _td(days=6)
    ).first()
    if recent:
        return
    today = _date.today()
    for h in HORIZON_CHECKPOINTS:
        if h - 1 < len(forecast_points):
            p = forecast_points[h - 1]
            db.add(models.ForecastLog(
                profile_id=profile_id, kind=kind, ref=str(ref), made_on=today,
                horizon_weeks=h, base_value=round(base_value, 1),
                predicted=p["mid"], predicted_low=p["low"], predicted_high=p["high"],
                target_date=today + _td(weeks=h)))
    db.commit()


def _matured_for_key(db, profile_id, kind, ref, actual_series):
    """Palauta erääntyneet (target_date <= tänään) ennusteet + toteuma."""
    from datetime import date as _date
    rows = db.query(models.ForecastLog).filter(
        models.ForecastLog.profile_id == profile_id, models.ForecastLog.kind == kind,
        models.ForecastLog.ref == str(ref), models.ForecastLog.target_date <= _date.today()
    ).order_by(models.ForecastLog.target_date).all()
    out = []
    for r in rows:
        actual = engine.value_near(actual_series, r.target_date)
        if actual is None:
            continue
        out.append({"made_on": r.made_on, "target_date": r.target_date,
                    "horizon_weeks": r.horizon_weeks, "base": r.base_value,
                    "predicted": r.predicted, "low": r.predicted_low, "high": r.predicted_high,
                    "actual": round(actual, 1)})
    return out


def _calibration_for_key(db, profile_id, kind, ref, actual_series) -> float:
    if profile_id is None:
        return 1.0
    matured = _matured_for_key(db, profile_id, kind, ref, actual_series)
    return engine.calibration_factor(matured)


@router.get("/exercises/{exercise_id}/history")
def exercise_history(
    exercise_id: int,
    profile_id: int | None = Query(None),
    window_days: int = Query(DEFAULT_WINDOW_DAYS),
    forecast: bool = Query(True),
    horizon_weeks: int = Query(52),
    db: Session = Depends(get_db),
):
    """Yhden liikkeen kehityskäyrä + ennätykset + realistinen ennuste."""
    ex = db.get(models.Exercise, exercise_id)
    points = _exercise_session_points(db, exercise_id, profile_id)
    records = _records_for_exercise(points, window_days)

    # Ennuste vain pääliikkeille (tunnistettu kyykky/penkki/mave/pystypunnerrus
    # tai is_main_lift) — apuliikkeiden ennuste ei ole hyödyllinen.
    forecast_points = []
    forecast_meta = None
    lift_key = engine.classify_lift(ex.name) if ex else None
    is_main = bool(lift_key) or (ex.is_main_lift if ex else False)
    valid_pts = [p for p in points if p["estimated_1rm"] > 0]
    if forecast and is_main and len(valid_pts) >= 2:
        # Katto naturaalinostajan realistisesta huipusta (jos paino tunnetaan)
        ceiling = None
        bw = _latest_bodyweight(db, profile_id)
        if lift_key and bw:
            profile = db.get(models.Profile, profile_id) if profile_id else None
            ceiling = engine.natural_ceiling(lift_key, bw, profile.sex if profile else None)
        # Luottamus datan määrästä ja painotrendi dieetin vaikutusta varten
        span_days = (valid_pts[-1]["date"] - valid_pts[0]["date"]).days
        conf = engine.forecast_confidence(len(valid_pts), span_days)
        bw_trend = _bodyweight_trend(db, profile_id) or 0.0
        history = [(p["date"], p["estimated_1rm"]) for p in valid_pts]
        # Kalibrointi aiemman osuvuuden mukaan
        calib = _calibration_for_key(db, profile_id, "lift", exercise_id, history)
        forecast_points = engine.forecast_progress(
            history, horizon_weeks, ceiling, bodyweight_trend_per_week=bw_trend,
            confidence=conf, rate_calibration=calib)
        _snapshot_forecast(db, profile_id, "lift", exercise_id, valid_pts[-1]["estimated_1rm"], forecast_points)
        conf_label = "korkea" if conf >= 0.7 else "kohtalainen" if conf >= 0.4 else "matala"
        calib_note = ""
        if calib > 1.05:
            calib_note = "Aiemmat ennusteet aliarvioivat — tahtia nostettu. "
        elif calib < 0.95:
            calib_note = "Aiemmat ennusteet yliarvioivat — tahtia laskettu. "
        forecast_meta = {
            "confidence": conf, "confidence_label": conf_label,
            "bodyweight_trend": bw_trend, "sessions": len(valid_pts), "calibration": calib,
            "note": ("Ennuste perustuu toteutuneeseen tahtiin ja naturaalinostajan "
                     "realistiseen kattoon (jopa 1 v eteenpäin; loukkaantuminen tai "
                     "sairaus voi tuoda takapakkia). " + calib_note +
                     ("Painon lasku hidastaa arvioitua kehitystä. " if bw_trend < -0.1 else "") +
                     f"Luottamus: {conf_label} ({len(valid_pts)} treenikertaa). Lisää dataa tarkentaa."),
        }

    return {
        "exercise_id": exercise_id,
        "exercise_name": ex.name if ex else None,
        "forecast_meta": forecast_meta,
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

    # Total-uran ennuste: ennusta jokainen pääliike ja summaa viikoittain.
    bw = _latest_bodyweight(db, profile_id)
    bw_trend = _bodyweight_trend(db, profile_id) or 0.0
    profile = db.get(models.Profile, profile_id) if profile_id else None
    sex = profile.sex if profile else None
    horizon = 26
    fc_mid = [0.0] * horizon
    fc_low = [0.0] * horizon
    fc_high = [0.0] * horizon
    fc_dates = None
    have_fc = False
    for ex in lifts:
        pts = [p for p in lift_timeseries.get(ex.name, []) if p["estimated_1rm"] > 0]
        if len(pts) < 2:
            continue
        lk = engine.classify_lift(ex.name)
        ceiling = engine.natural_ceiling(lk, bw, sex) if (lk and bw) else None
        span = (pts[-1]["date"] - pts[0]["date"]).days
        conf = engine.forecast_confidence(len(pts), span)
        fc = engine.forecast_progress([(p["date"], p["estimated_1rm"]) for p in pts],
                                      horizon, ceiling, bodyweight_trend_per_week=bw_trend, confidence=conf)
        if not fc:
            continue
        have_fc = True
        if fc_dates is None:
            fc_dates = [m["date"] for m in fc]
        for i, m in enumerate(fc):
            fc_mid[i] += m["mid"]; fc_low[i] += m["low"]; fc_high[i] += m["high"]

    total_forecast = []
    if have_fc and fc_dates:
        total_forecast = [{"date": fc_dates[i], "mid": round(fc_mid[i], 1),
                           "low": round(fc_low[i], 1), "high": round(fc_high[i], 1)}
                          for i in range(len(fc_dates))]

    return {
        "sport": sport,
        "total_low": round(total_low, 1),
        "total_mid": round(total_mid, 1),
        "total_high": round(total_high, 1),
        "per_lift": per_lift,
        "timeline": timeline,
        "forecast": total_forecast,
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

    _load_bw = _latest_bodyweight(db, profile_id)  # kcal-arviota varten
    by_date: dict[date, dict] = {}
    for s in sessions:
        agg = by_date.setdefault(s.session_date,
                                 {"total_kg": 0.0, "reps": 0, "sets": 0, "kcal_burned": 0.0,
                                  "duration_min": 0, "kcal_estimated": False})
        if s.kcal_burned:
            agg["kcal_burned"] += s.kcal_burned
        elif s.duration_min:
            # Ei älykellodataa -> arvioi kulutus painosta ja kestosta
            est = engine.estimate_workout_kcal(_load_bw, s.duration_min)
            if est:
                agg["kcal_burned"] += est
                agg["kcal_estimated"] = True
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
            pop_avg = engine.population_average(lift_key, bw, sex)
            vs_avg = round(rec["current_1rm"] / pop_avg, 1) if pop_avg else None
            result.append({"exercise_name": ex.name, "current_1rm": rec["current_1rm"],
                           "bodyweight": bw, "population_avg": pop_avg, "vs_population": vs_avg, **lvl})
    return {"bodyweight": bw, "all_levels": engine.STRENGTH_LEVELS, "lifts": result}


@router.get("/body-score")
def body_score(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Kehon yhteispisteet: suhdepisteet (mitat) + fysiikkataso (FFMI) +
    voimataso. Antaa kuvan sekä ulkonäön että voiman tasosta.

    Molemmat tekijät tarvitaan: dataan perustuva (omat mitat/nostot) ja
    malliin perustuva (esteettiset suhteet, voimastandardit). Mitä enemmän
    dataa, sitä luotettavampi tulos.
    """
    profile = db.get(models.Profile, profile_id)
    height = profile.height_cm if profile else None
    sex = profile.sex if profile else None

    # Viimeisin mitta per kohta
    latest_meas: dict[str, float] = {}
    for m in (db.query(models.Measurement)
              .filter(models.Measurement.profile_id == profile_id)
              .order_by(models.Measurement.entry_date).all()):
        latest_meas[m.site] = m.value_cm
    proportion = engine.proportion_score(latest_meas, height, sex)

    # Fysiikkataso (FFMI) viimeisimmästä painosta + rasva-%:sta
    physique = None
    bw_e = (db.query(models.BodyEntry).filter(models.BodyEntry.profile_id == profile_id,
            models.BodyEntry.bodyweight.isnot(None)).order_by(models.BodyEntry.entry_date.desc()).first())
    bf_e = (db.query(models.BodyEntry).filter(models.BodyEntry.profile_id == profile_id,
            models.BodyEntry.body_fat_pct.isnot(None)).order_by(models.BodyEntry.entry_date.desc()).first())
    if bw_e and bf_e:
        comp = engine.body_composition(bw_e.bodyweight, bf_e.body_fat_pct, height)
        physique = engine.physique_level(comp.get("ffmi"), sex)

    # Voimataso: pääliikkeiden keskimääräinen taso (0–7) -> 0–100
    lv = levels(profile_id, db)
    strength_idxs = [l["level_index"] for l in lv["lifts"] if l.get("level_index", -1) >= 0]
    strength_score = round(sum(strength_idxs) / len(strength_idxs) / 7 * 100) if strength_idxs else None

    # Yhteispisteet saatavilla olevista osista
    parts = []
    if proportion:
        parts.append(proportion["score"])
    if physique:
        parts.append(min(100, round(physique["level_index"] / 7 * 100)))
    if strength_score is not None:
        parts.append(strength_score)
    overall = round(sum(parts) / len(parts)) if parts else None

    return {
        "proportion": proportion,
        "physique": physique,
        "strength_score": strength_score,
        "strength_level_avg": (round(sum(strength_idxs) / len(strength_idxs), 1) if strength_idxs else None),
        "overall_score": overall,
        "note": "Pisteet ovat suuntaa antavia. Mitä enemmän mittoja ja nostoja kirjaat, sitä tarkemmat.",
    }


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


@router.get("/volume-analysis")
def volume_analysis(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Viikkovolyymi lihasryhmittäin + ehdotukset (kasvata/vähennä/OK).

    Laskee suoritetut työsarjat kategorioittain tällä ja edellisellä viikolla,
    vertaa hypertrofiasuositukseen ja antaa ehdotuksen. Käyttäjä voi kuitata
    tilanteen OK:ksi, jolloin ehdotukset merkitään kuitatuiksi.
    """
    sessions = (
        db.query(models.WorkoutSession)
        .filter(models.WorkoutSession.profile_id == profile_id,
                models.WorkoutSession.status != "skipped")
        .all()
    )
    if not sessions:
        return {"message": "Kirjaa treenejä, niin näet viikkovolyymin.", "categories": []}

    ref_date = max(s.session_date for s in sessions)
    this_start = ref_date - timedelta(days=6)
    prev_start = ref_date - timedelta(days=13)

    this_week: dict[str, int] = {}
    prev_week: dict[str, int] = {}
    for s in sessions:
        if s.session_date < prev_start:
            continue
        bucket = this_week if s.session_date >= this_start else prev_week
        for we in s.exercises:
            cat = (we.exercise.category or "muu") if we.exercise else "muu"
            sets = sum(1 for st in we.sets if st.completed and st.reps > 0)
            if sets:
                bucket[cat] = bucket.get(cat, 0) + sets

    cats = sorted(set(this_week) | set(prev_week))
    categories = []
    for c in cats:
        sw, sp = this_week.get(c, 0), prev_week.get(c, 0)
        categories.append({"category": c, "sets_week": sw, "sets_prev": sp, **engine.volume_verdict(sw, sp)})
    # Järjestä huomiota vaativat ensin (low/high), sitten ok
    order = {"low": 0, "high": 1, "none": 2, "ok": 3}
    categories.sort(key=lambda x: order.get(x["status"], 9))

    iso = ref_date.isocalendar()
    week_key = f"{iso[0]}-{iso[1]:02d}"
    acked = db.query(models.VolumeAck).filter(
        models.VolumeAck.profile_id == profile_id, models.VolumeAck.week_key == week_key
    ).first() is not None

    return {
        "week_key": week_key,
        "ref_date": ref_date.isoformat(),
        "acknowledged": acked,
        "total_sets_week": sum(this_week.values()),
        "categories": categories,
    }


@router.post("/volume-ack")
def volume_ack(profile_id: int = Query(...), week_key: str = Query(...), db: Session = Depends(get_db)):
    """Kuittaa viikon volyymi OK:ksi (ei muutoksia tarvita)."""
    existing = db.query(models.VolumeAck).filter(
        models.VolumeAck.profile_id == profile_id, models.VolumeAck.week_key == week_key
    ).first()
    if not existing:
        db.add(models.VolumeAck(profile_id=profile_id, week_key=week_key))
        db.commit()
    return {"acknowledged": True, "week_key": week_key}


@router.get("/forecast-accuracy")
def forecast_accuracy(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Aiempien ennusteiden osuvuus: mitä ennuste lupasi vs. mitä toteutui.

    Auttaa sekä käyttäjää (näe miten ennusteet ovat osuneet) että järjestelmää
    (kalibroi tulevia tarkemmiksi). Vain erääntyneet (target_date mennyt) mukana.
    """
    keys = (db.query(models.ForecastLog.kind, models.ForecastLog.ref)
            .filter(models.ForecastLog.profile_id == profile_id).distinct().all())
    comparisons = []
    for kind, ref in keys:
        if kind == "lift":
            try:
                pts = _exercise_session_points(db, int(ref), profile_id)
            except (ValueError, TypeError):
                continue
            actual_series = [(p["date"], p["estimated_1rm"]) for p in pts if p["estimated_1rm"] > 0]
            ex = db.get(models.Exercise, int(ref))
            label = ex.name if ex else f"liike {ref}"
        else:  # measurement
            ms = (db.query(models.Measurement)
                  .filter(models.Measurement.profile_id == profile_id, models.Measurement.site == ref)
                  .order_by(models.Measurement.entry_date).all())
            actual_series = [(m.entry_date, m.value_cm) for m in ms]
            label = ref
        for m in _matured_for_key(db, profile_id, kind, ref, actual_series):
            pred_gain = m["predicted"] - m["base"]
            err = m["actual"] - m["predicted"]
            err_pct = round(abs(err) / m["predicted"] * 100, 1) if m["predicted"] else None
            comparisons.append({
                "kind": kind, "label": label, "made_on": m["made_on"].isoformat(),
                "target_date": m["target_date"].isoformat(), "horizon_weeks": m["horizon_weeks"],
                "base": m["base"], "predicted": m["predicted"], "actual": m["actual"],
                "error": round(err, 1), "error_pct": err_pct,
                "within_band": m["low"] <= m["actual"] <= m["high"],
            })
    comparisons.sort(key=lambda c: c["target_date"], reverse=True)
    n = len(comparisons)
    overall = None
    if n:
        within = sum(1 for c in comparisons if c["within_band"])
        mae = round(sum(abs(c["error"]) for c in comparisons) / n, 1)
        avg_err_pct = round(sum(c["error_pct"] for c in comparisons if c["error_pct"] is not None) /
                            max(1, sum(1 for c in comparisons if c["error_pct"] is not None)), 1)
        overall = {"count": n, "within_band_pct": round(within / n * 100), "mae": mae, "avg_error_pct": avg_err_pct}
    return {"overall": overall, "comparisons": comparisons[:30]}


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
