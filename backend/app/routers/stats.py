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
    # Päivät joina liikkeestä ei ole yhtään suoritettua sarjaa (esim. tälle
    # päivälle ohjelmasta luotu, vielä tekemätön "suunniteltu" treeni) eivät
    # ole kehitystä: ilman tätä ne piirtyivät käyrään nollapisteenä, joka
    # näytti valtavalta tiputukselta ja josta ennusteen katkoviiva lähti.
    return [by_date[d] for d in sorted(by_date)
            if by_date[d]["best_set"] is not None or by_date[d]["volume"] > 0]


def _level_series(points: list[dict], window_days: int = DEFAULT_WINDOW_DAYS) -> list[tuple]:
    """"Nykytaso"-sarja: paras arvioitu 1RM tuoreen ikkunan sisällä per päivä
    (sama sääntö kuin current_1rm). Tästä sarjasta ennuste lähtee ja tähän
    sarjaan toteumaa verrataan — ei yksittäisen treenin arvioon."""
    return engine.rolling_best_series(
        [(p["date"], p["estimated_1rm"]) for p in points if p["estimated_1rm"] > 0], window_days)


# Kun aiempi huippu on eri variaatiosta samaa nostoa (esim. low bar -kyykky
# vs. nykyinen high bar, sumo vs. konventionaalinen mave), se ei ole suoraan
# sama luku: käytetään maltillista alennusta.
CROSS_VARIANT_PRIOR_FACTOR = 0.92


def _prior_best_for_lift(db: Session, profile_id: int | None, lift_key: str,
                         exclude_exercise_id: int) -> tuple[float, date, str] | None:
    """Paras aiempi tulos SAMAN nostoluokan muista liikkeistä (variaatiot)."""
    if not lift_key:
        return None
    best = None
    for ex in db.query(models.Exercise).all():
        if ex.id == exclude_exercise_id or engine.classify_lift(ex.name) != lift_key:
            continue
        pts = _exercise_session_points(db, ex.id, profile_id)
        valid = [p for p in pts if p["estimated_1rm"] > 0]
        if not valid:
            continue
        top = max(valid, key=lambda p: p["estimated_1rm"])
        if best is None or top["estimated_1rm"] > best[0]:
            best = (top["estimated_1rm"], top["date"], ex.name)
    return best


def _lift_forecast(db: Session, profile_id: int | None, ex: models.Exercise,
                   points: list[dict], horizon_weeks: int = 52,
                   window_days: int = DEFAULT_WINDOW_DAYS) -> dict | None:
    """YKSI yhteinen ennustelaskuri pääliikkeelle. Käytetään kehitysgraafissa,
    lajitotalissa ja tavoitepainoissa, jotta kaikki näyttävät saman ennusteen.

    - Lähtötaso (anchor) = current_1rm (paras tuoreen ikkunan sisällä), ei
      viimeisin yksittäinen treeni.
    - Tahti robustista trendistä (viim. ~84 pv), taustatestistä opittu
      kalibrointi + osuvuuslokin kalibrointi + kokemustaso.
    - Aiempi huippu (myös saman noston toinen variaatio) -> lihasmuisti,
      vanhan huipun ikä huomioiden.
    """
    valid_pts = [p for p in points if p["estimated_1rm"] > 0]
    lift_key = engine.classify_lift(ex.name)
    is_main = bool(lift_key) or bool(ex.is_main_lift)
    if not is_main or len(valid_pts) < 2:
        return None
    profile = db.get(models.Profile, profile_id) if profile_id else None
    sex = profile.sex if profile else None
    bw = _latest_bodyweight(db, profile_id)
    ceiling = engine.natural_ceiling(lift_key, bw, sex) if (lift_key and bw) else None
    span_days = (valid_pts[-1]["date"] - valid_pts[0]["date"]).days
    conf = engine.forecast_confidence(len(valid_pts), span_days)
    bw_trend = _bodyweight_trend(db, profile_id) or 0.0
    history = [(p["date"], p["estimated_1rm"]) for p in valid_pts]
    level = engine.rolling_best_series(history, window_days)
    anchor = level[-1][1]
    anchor_date = level[-1][0]

    # Kalibrointi: osuvuusloki (nykytasoa vasten) * taustatesti * kokemustaso.
    # Sekä tahti että taustatesti lasketaan NYKYTASOSARJASTA: treenistä-
    # treeniin heilunta (5x5 vs 3x3 antaa eri arvion samasta voimasta) ei
    # silloin näy tasanteena eikä kohinana, vaan trendi on aito tason muutos.
    log_calib = _calibration_for_key(db, profile_id, "lift", ex.id, level)
    bt = engine.backtest_forecast(level)
    calib = max(0.6, min(1.4, log_calib * bt["rate_ratio"]))
    exp_calib = engine.experience_rate_calibration(profile.experience if profile else None, conf)
    calib = max(0.6, min(1.5, calib * exp_calib))

    # Aiempi huippu: oma historia tai saman noston toinen variaatio
    best_pt = max(valid_pts, key=lambda p: p["estimated_1rm"])
    prior_best, prior_date, prior_src = best_pt["estimated_1rm"], best_pt["date"], None
    cross = _prior_best_for_lift(db, profile_id, lift_key, ex.id) if lift_key else None
    if cross and cross[0] * CROSS_VARIANT_PRIOR_FACTOR > prior_best:
        prior_best, prior_date, prior_src = cross[0] * CROSS_VARIANT_PRIOR_FACTOR, cross[1], cross[2]
    prior_age_weeks = (date.today() - prior_date).days / 7.0
    prior_info = None
    if prior_best > anchor + 0.5:
        prior_info = {"value": round(prior_best, 1), "date": prior_date.isoformat(),
                      "years_ago": round(prior_age_weeks / 52.0, 1),
                      "memory_strength": round(engine.muscle_memory_strength(prior_age_weeks), 2),
                      "source": prior_src}
        # Keho joka on jo nostanut huipun pystyy siihen uudelleen: naturaali-
        # katto (kehon painosta) ei voi olla alle todistetun huipun.
        if ceiling is not None and ceiling < prior_best * 1.03:
            ceiling = round(prior_best * 1.03, 1)
    else:
        prior_best = None

    fc = engine.forecast_progress(
        level, horizon_weeks, ceiling, bodyweight_trend_per_week=bw_trend,
        confidence=conf, rate_calibration=calib, prior_best=prior_best,
        prior_best_age_weeks=prior_age_weeks, error_scale=bt["error_scale"], anchor=anchor)
    if not fc:
        return None
    return {"forecast": fc, "anchor": round(anchor, 1), "anchor_date": anchor_date,
            "confidence": conf, "calibration": calib, "log_calibration": log_calib,
            "backtest": bt, "exp_calib": exp_calib,
            "bodyweight_trend": bw_trend, "sessions": len(valid_pts), "prior": prior_info,
            "ceiling": ceiling, "level": level, "lift_key": lift_key}


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
    lf = _lift_forecast(db, profile_id, ex, points, horizon_weeks, window_days) if (forecast and ex) else None
    if lf:
        forecast_points = lf["forecast"]
        bt, calib, exp_calib, conf, bw_trend = (lf["backtest"], lf["calibration"], lf["exp_calib"],
                                                lf["confidence"], lf["bodyweight_trend"])
        profile = db.get(models.Profile, profile_id) if profile_id else None
        _snapshot_forecast(db, profile_id, "lift", exercise_id, lf["anchor"], forecast_points)
        conf_label = "korkea" if conf >= 0.7 else "kohtalainen" if conf >= 0.4 else "matala"
        calib_note = ""
        if lf["log_calibration"] > 1.05:
            calib_note = "Aiemmat tallennetut ennusteet aliarvioivat toteumaa — tahtia nostettu. "
        elif lf["log_calibration"] < 0.95:
            calib_note = "Aiemmat tallennetut ennusteet yliarvioivat toteumaa — tahtia laskettu. "
        if bt["n"] >= 3:
            if bt["rate_ratio"] >= 1.15:
                calib_note += "Kehityksesi on ollut poikkeuksellisen vahvaa (data ylitti mallin) — tahti pidetty korkeana. "
            elif bt["rate_ratio"] <= 0.7:
                calib_note += "Kehitys on tasaantunut mallin ennustamaa hitaammaksi — tahti laskettu. "
            calib_note += "Haarukka perustuu omien ennustevirheidesi kokoon (kapenee kun data on tasaista). "
        if abs(exp_calib - 1.0) > 0.03:
            exp_lbl = {"aloittelija": "aloittelija", "kokenut": "kokenut",
                       "palaava": "tauolta palaava"}.get(profile.experience if profile else "", "")
            calib_note += (f"Taustakyselyn kokemustaso ({exp_lbl}) "
                           f"{'nostaa' if exp_calib > 1 else 'laskee'} arvioitua tahtia "
                           "kunnes omaa dataa kertyy tarpeeksi. ")
        prior_note = ""
        if lf["prior"]:
            pr = lf["prior"]
            src = f" ({pr['source']}, toinen variaatio, −{round((1 - CROSS_VARIANT_PRIOR_FACTOR) * 100)} %)" if pr["source"] else ""
            prior_note = (f"Aiempi huippu {pr['value']} kg{src} on {pr['years_ago']} v takaa: lihasmuisti "
                          f"nopeuttaa paluuta sinne (etu {round(pr['memory_strength'] * 100)} %"
                          + (" — yli 2 v vanha huippu antaa pienemmän etulyönnin, keho ja tekniikka ovat muuttuneet"
                             if pr["years_ago"] > 2 else "") + "). ")
        forecast_meta = {
            "confidence": conf, "confidence_label": conf_label,
            "bodyweight_trend": bw_trend, "sessions": lf["sessions"], "calibration": calib,
            "anchor": lf["anchor"], "anchor_date": lf["anchor_date"].isoformat(),
            "prior": lf["prior"],
            "note": (f"Ennuste lähtee nykytasosta {lf['anchor']} kg (paras arvio {window_days} pv sisällä — "
                     "yksittäinen kevyt treeni ei pudota sitä) ja perustuu toteutuneeseen tahtiin sekä "
                     "naturaalinostajan realistiseen kattoon (jopa 1 v eteenpäin; loukkaantuminen tai "
                     "sairaus voi tuoda takapakkia). " + prior_note + calib_note +
                     ("Painon lasku hidastaa arvioitua kehitystä. " if bw_trend < -0.1 else "") +
                     f"Luottamus: {conf_label} ({lf['sessions']} treenikertaa). Lisää dataa tarkentaa."),
        }

    level = {d: v for d, v in _level_series(points, window_days)}
    return {
        "exercise_id": exercise_id,
        "exercise_name": ex.name if ex else None,
        "forecast_meta": forecast_meta,
        "points": [
            {
                "date": p["date"].isoformat(),
                "estimated_1rm": p["estimated_1rm"],
                "level_1rm": level.get(p["date"]),
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
    # kunkin liikkeen NYKYTASOSTA (paras tuoreen ikkunan sisällä) siihen
    # mennessä — sama sääntö kuin total_mid:ssä, joten käyrän viimeinen piste
    # on sama luku kuin näytetty yhteistulos eikä kevyt treenipäivä pudota sitä.
    all_dates = sorted({p["date"] for pts in lift_timeseries.values() for p in pts})
    level_by_lift = {name: dict(_level_series(pts, window_days)) for name, pts in lift_timeseries.items()}
    timeline = []
    last_known: dict[str, float] = {}
    for d in all_dates:
        for name, lv in level_by_lift.items():
            if d in lv:
                last_known[name] = lv[d]
        if last_known:
            timeline.append({"date": d.isoformat(), "total": round(sum(last_known.values()), 1)})

    # Total-uran ennuste: sama yhteinen laskuri (_lift_forecast) kuin liikkeen
    # kehitysgraafissa, summattuna viikoittain.
    # TÄRKEÄÄ: kaikki liikkeet ankkuroidaan YHTEISEEN tulevaisuusakseliin, joka
    # alkaa viimeisimmästä toteutuneesta totalista (ref_date) eikä kunkin
    # liikkeen omasta viimeisestä päivästä. Muuten liike, jonka tuorein merkintä
    # on vanha (esim. kirjattu vanha ennätys), vetäisi koko ennusteen alkamaan
    # menneisyydestä. Ennuste projisoidaan aina NYKYHETKESTÄ vuosi eteenpäin.
    bw = _latest_bodyweight(db, profile_id)
    profile = db.get(models.Profile, profile_id) if profile_id else None
    sex = profile.sex if profile else None
    horizon = 52  # ~1 vuosi (pidemmälle ei ennusteta luotettavasti)
    fc_mid = [0.0] * horizon
    fc_low = [0.0] * horizon
    fc_high = [0.0] * horizon
    have_fc = False
    # Yhteinen ankkuripäivä = tuorein toteutunut total (tai tänään jos ei dataa)
    ref_date = all_dates[-1] if all_dates else date.today()
    for ex in lifts:
        pts = lift_timeseries.get(ex.name, [])
        cur = last_known.get(ex.name)  # liikkeen nykytaso ref_date-hetkellä
        lf = _lift_forecast(db, profile_id, ex, pts, horizon, window_days)
        if not lf:
            # Ei ennustettavaa dataa -> pidetään nykyarvo tasaisena (jottei
            # total-ennuste tipahda alle nykytason puuttuvan liikkeen takia).
            if cur:
                for i in range(horizon):
                    fc_mid[i] += cur; fc_low[i] += cur; fc_high[i] += cur
            continue
        have_fc = True
        # Summataan viikkoindeksillä (viikko i liikkeen nykyarvosta eteenpäin);
        # kalenteripäivä otetaan yhteisestä ref_date-akselista, ei liikkeeltä.
        for i, m in enumerate(lf["forecast"]):
            fc_mid[i] += m["mid"]; fc_low[i] += m["low"]; fc_high[i] += m["high"]

    total_forecast = []
    if have_fc:
        total_forecast = [{"date": (ref_date + timedelta(weeks=i + 1)).isoformat(),
                           "mid": round(fc_mid[i], 1),
                           "low": round(fc_low[i], 1), "high": round(fc_high[i], 1)}
                          for i in range(horizon)]

    # Kilpailutaso: yhteistulos vs. painoluokka ja paikallinen→MM
    competition = engine.competition_assessment(sport, total_mid, bw, sex) if bw else None

    return {
        "sport": sport,
        "total_low": round(total_low, 1),
        "total_mid": round(total_mid, 1),
        "total_high": round(total_high, 1),
        "bodyweight": bw,
        "per_lift": per_lift,
        "timeline": timeline,
        "forecast": total_forecast,
        "competition": competition,
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
    ex = db.get(models.Exercise, exercise_id)
    inc = engine.progression_increment(
        ex.name if ex else None, ex.equipment if ex else None,
        ex.category if ex else None, ex.is_main_lift if ex else False,
        ex.per_hand if ex else False)
    suggestions = {
        str(r): engine.round_to_increment(engine.weight_for_reps(one_rm, r, bs.get("rir")), inc)
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


@router.get("/comeback")
def comeback(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Paluu vanhoihin tuloksiin: liikkeet joissa on ennätys mutta joita ei ole
    tehty hetkeen. Näyttää ennätyksen, ajan siitä, realistisen tämänhetkisen
    arvion (detraining) ja maltillisen lähtöpainon uudelleen aloittamiseen."""
    today = date.today()
    result = []
    # Käydään läpi liikkeet, joissa on lokitettua dataa
    ex_ids = [row[0] for row in (
        db.query(models.WorkoutExercise.exercise_id)
        .join(models.WorkoutSession, models.WorkoutExercise.session_id == models.WorkoutSession.id)
        .filter(*( [models.WorkoutSession.profile_id == profile_id] if profile_id is not None else [] ))
        .distinct().all())]
    for ex_id in ex_ids:
        ex = db.get(models.Exercise, ex_id)
        if not ex:
            continue
        points = _exercise_session_points(db, ex_id, profile_id)
        rec = _records_for_exercise(points, DEFAULT_WINDOW_DAYS)
        if not rec:
            continue
        weeks_since = (today - rec["last_trained"]).days / 7.0
        # "Paluu" koskee liikkeitä joita ei ole tehty ~3 viikkoon
        if weeks_since < 3:
            continue
        plan = engine.comeback_plan(rec["best_ever_1rm"], weeks_since)
        if not plan:
            continue
        result.append({
            "exercise_id": ex_id, "exercise_name": ex.name,
            "last_trained": rec["last_trained"].isoformat(),
            "best_ever_date": rec["best_ever_date"].isoformat() if rec["best_ever_date"] else None,
            **plan,
        })
    result.sort(key=lambda r: r["best_ever_1rm"], reverse=True)
    return {"comebacks": result}


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

    # Realistinen korotusaskel liikkeen mukaan (2.5 kg isot, 1 kg eristävät)
    ex = db.get(models.Exercise, exercise_id)
    inc = engine.progression_increment(
        ex.name if ex else None, ex.equipment if ex else None,
        ex.category if ex else None, ex.is_main_lift if ex else False,
        ex.per_hand if ex else False)

    if target_reps == bs["reps"]:
        # Sama toistotavoite kuin viimeksi: korotus = TASAN yksi askel edellisestä
        base = bs["weight"] + (inc if increase else 0.0)
    else:
        # Eri toistotavoite: laske sitä vastaava paino, ja lisää yksi askel jos korotetaan
        base = engine.weight_for_reps(one_rm, target_reps, rir) + (inc if increase else 0.0)
    suggested = engine.round_to_increment(base, inc)
    return {
        "suggested_weight": suggested,
        "increment": inc,
        "from": {"weight": bs["weight"], "reps": bs["reps"], "date": last["date"].isoformat()},
        "note": (
            f"Edellinen paras: {bs['weight']} kg × {bs['reps']}. "
            f"Ehdotus {target_reps} toistolle" + (f" (+{inc} kg)" if increase else "") + f": {suggested} kg."
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
    return {"bodyweight": bw, "all_levels": engine.STRENGTH_LEVELS,
            "level_meanings": engine.LEVEL_MEANINGS, "lifts": result}


@router.get("/target-weights")
def target_weights(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Pääliikkeiden tämänhetkiset tavoitepainot: arvioidusta 1RM:stä johdetut
    työpainot yleisimmille sarjamalleille + ennuste ~1 v päähän. Näin näet
    helposti millä painoilla kannattaa treenata (penkki/kyykky/mave/pystyp.)."""
    bw = _latest_bodyweight(db, profile_id)
    profile = db.get(models.Profile, profile_id) if profile_id else None
    sex = profile.sex if profile else None
    lifts = []
    for ex in db.query(models.Exercise).filter(models.Exercise.is_main_lift.is_(True)).order_by(models.Exercise.name).all():
        points = _exercise_session_points(db, ex.id, profile_id)
        rec = _records_for_exercise(points, DEFAULT_WINDOW_DAYS)
        if not rec:
            continue
        one_rm = rec["current_1rm"]
        inc = engine.progression_increment(ex.name, ex.equipment, ex.category, ex.is_main_lift, ex.per_hand)
        schemes = {
            "5x5": engine.round_to_increment(engine.weight_for_reps(one_rm, 5, 2), inc),
            "3x3": engine.round_to_increment(engine.weight_for_reps(one_rm, 3, 1), inc),
            "1RM": engine.round_to_increment(one_rm, inc),
        }
        # Ennuste ~1 v: SAMA laskuri kuin kehitysgraafissa (kalibroitu,
        # nykytasosta lähtevä), jotta tavoitepainojen luku ja graafi täsmäävät.
        forecast_1rm = forecast_4wk = None
        lf = _lift_forecast(db, profile_id, ex, points, 52, DEFAULT_WINDOW_DAYS)
        if lf:
            forecast_1rm = lf["forecast"][-1]["mid"]
            forecast_4wk = lf["forecast"][3]["mid"] if len(lf["forecast"]) >= 4 else None
        lifts.append({
            "exercise_name": ex.name, "current_1rm": one_rm, "increment": inc,
            "schemes": schemes, "forecast_1rm_1y": forecast_1rm, "forecast_1rm_4wk": forecast_4wk,
            "last_trained": rec["last_trained"].isoformat() if rec["last_trained"] else None,
        })
    return {"bodyweight": bw, "lifts": lifts}


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
        creatine = bool(profile.creatine) if profile else False
        comp = engine.body_composition(bw_e.bodyweight, bf_e.body_fat_pct, height, creatine=creatine)
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
        parts.append(min(100, round(physique["level_index"] / (len(physique["levels"]) - 1) * 100)))
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


@router.get("/bodypart-levels")
def bodypart_levels(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Kehon osien taso per mittakohta: väestön keskiarvosta IFBB Pro -luokkaan,
    pituuteen suhteutettuna. Vyötärö käänteisesti (pienempi parempi)."""
    profile = db.get(models.Profile, profile_id)
    height = profile.height_cm if profile else None
    sex = profile.sex if profile else None
    # Viimeisin mitta per kohta
    latest: dict[str, float] = {}
    for m in (db.query(models.Measurement)
              .filter(models.Measurement.profile_id == profile_id)
              .order_by(models.Measurement.entry_date).all()):
        latest[m.site] = m.value_cm
    # Rasva-% rasvakorjausta varten (mitattu tai arvioitu mitoista)
    bf_e = (db.query(models.BodyEntry).filter(models.BodyEntry.profile_id == profile_id,
            models.BodyEntry.body_fat_pct.isnot(None)).order_by(models.BodyEntry.entry_date.desc()).first())
    bf_pct = bf_e.body_fat_pct if bf_e else engine.body_fat_navy(
        sex, height, latest.get("kaula"), latest.get("vyötärö"), latest.get("lantio"))
    parts = []
    for site, val in latest.items():
        lvl = engine.bodypart_level(site, val, height, sex, body_fat_pct=bf_pct)
        if lvl:
            vs = round(val / lvl["population_avg_cm"], 2) if lvl["population_avg_cm"] else None
            parts.append({**lvl, "vs_population": vs})
    # Järjestä tason mukaan laskevasti
    parts.sort(key=lambda p: p["level_index"], reverse=True)
    return {"height_cm": height, "all_levels": engine.BODYPART_LEVELS, "parts": parts}


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


# Kanoniset päälihasryhmät (koko kehon kate) ja vapaakategorioiden mäppäys
MAJOR_GROUPS = ["rinta", "selkä", "jalat", "olkapäät", "kädet", "keskivartalo"]


def _major_group(category: str | None, muscle_group: str | None, name: str | None) -> str | None:
    """Mäppää liike yhteen pääryhmään koko kehon katetta varten."""
    text = " ".join([(category or ""), (muscle_group or ""), (name or "")]).lower()
    if any(k in text for k in ("rinta", "penkki", "fly", "dippi")):
        return "rinta"
    if any(k in text for k in ("selkä", "soutu", "leuanveto", "ylätalja", "alatalja", "maasta", "mave")):
        return "selkä"
    if any(k in text for k in ("jalat", "jalka", "reisi", "reidet", "kyykky", "pakara", "pohje",
                               "takareisi", "prässi", "lähennys", "loitonnus", "olympia", "tempaus", "rinnalleveto")):
        return "jalat"
    if any(k in text for k in ("olkapää", "olkapäät", "hartia", "pystypunnerrus", "sivunosto", "vipunosto", "delt")):
        return "olkapäät"
    if any(k in text for k in ("hauis", "ojentaja", "kääntö", "curl", "kickback", "kyynärvarsi", "ranne", "kädet", "käsi")):
        return "kädet"
    if any(k in text for k in ("keskivartalo", "vatsa", "vyötärö", "selän ojennus", "alaselkä", "plank")):
        return "keskivartalo"
    return None


@router.get("/program-load")
def program_load(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Kokonaiskuorma OHJELMAKIERROITTAIN: kun ohjelman kaikki treenipäivät on
    tehty kerran (yksi kierto), summataan niiden kg ja merkitään piste kierron
    viimeisen treenin päivälle. Näyttää suunnan selkeämmin kuin per-treeni.
    """
    q = db.query(models.Program)
    if profile_id is not None:
        q = q.filter(models.Program.profile_id == profile_id)
    programs = q.all()
    result = []
    for prog in programs:
        train_day_ids = [d.id for d in prog.days if d.day_type == "train"]
        if not train_day_ids:
            continue
        need = set(train_day_ids)
        # Skipatut treenit lasketaan mukaan kierron täyttäjinä (0 kg): näin kierto
        # sulkeutuu vaikka jokin päivä jäisi väliin, ja total on silloin vain
        # pienempi — juuri niin kuin kuuluukin näyttää.
        sessions = (db.query(models.WorkoutSession)
                    .filter(models.WorkoutSession.program_day_id.in_(train_day_ids),
                            models.WorkoutSession.status.in_(["completed", "skipped"]))
                    .order_by(models.WorkoutSession.session_date, models.WorkoutSession.id).all())
        cycles = []
        seen, load, last_date, cnt, skipped = set(), 0.0, None, 0, 0
        for s in sessions:
            if s.program_day_id in seen:
                continue  # sama päivä jo tässä kierrossa -> odota seuraavaa kiertoa
            if s.status == "completed":
                load += _session_tonnage(s)
            else:
                skipped += 1
            cnt += 1
            seen.add(s.program_day_id)
            last_date = s.session_date
            if need.issubset(seen):
                cycles.append({"date": last_date.isoformat(), "total_kg": round(load, 1),
                               "workouts": cnt, "skipped": skipped})
                seen, load, cnt, skipped = set(), 0.0, 0, 0
        if cycles:
            result.append({"program_id": prog.id, "program_name": prog.name,
                           "is_active": prog.is_active, "cycles": cycles,
                           "open_partial": {"workouts": cnt, "total_kg": round(load, 1),
                                            "skipped": skipped} if cnt else None})
    # Aktiivinen ensin
    result.sort(key=lambda r: (0 if r["is_active"] else 1))
    return {"programs": result}


def _session_tonnage(s: models.WorkoutSession) -> float:
    tonnage = 0.0
    for we in s.exercises:
        top_w = max((st.weight for st in we.sets if st.completed), default=0.0)
        tonnage += sum(st.weight * st.reps for st in we.sets if st.completed)
        if we.missed_reps:
            tonnage = max(0.0, tonnage - we.missed_reps * top_w)
    return tonnage


@router.get("/coverage")
def coverage(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Koko kehon treenaustahti: näyttää KAIKKI päälihasryhmät (myös ne joita ei
    ole treenattu) rullaavalla ~10 pv ikkunalla. Sietää jaksotetun/split-treenin,
    mutta paljastaa jos jokin ryhmä jää jatkuvasti väliin."""
    today = date.today()
    window = 10
    sessions = (db.query(models.WorkoutSession)
                .filter(models.WorkoutSession.profile_id == profile_id,
                        models.WorkoutSession.status != "skipped").all())
    sets_by_group = {g: 0 for g in MAJOR_GROUPS}
    last_by_group: dict[str, date] = {}
    for s in sessions:
        for we in s.exercises:
            if not we.exercise:
                continue
            g = _major_group(we.exercise.category, we.exercise.muscle_group, we.exercise.name)
            if not g:
                continue
            done_sets = sum(1 for st in we.sets if st.completed and st.reps > 0)
            if done_sets:
                if g not in last_by_group or s.session_date > last_by_group[g]:
                    last_by_group[g] = s.session_date
                if 0 <= (today - s.session_date).days < window:
                    sets_by_group[g] += done_sets

    groups = []
    for g in MAJOR_GROUPS:
        sw = sets_by_group[g]
        last = last_by_group.get(g)
        days_since = (today - last).days if last else None
        if sw >= 10:
            status, label = "ok", "hyvä tahti"
        elif sw >= 4:
            status, label = "ok", "riittävä"
        elif sw >= 1:
            status, label = "low", "vähän"
        else:
            status, label = "none", ("ei treenattu" if days_since is None else f"tauolla {days_since} pv")
        groups.append({"group": g, "sets_window": sw, "days_since": days_since,
                       "status": status, "label": label})
    missing = [g["group"] for g in groups if g["status"] == "none"]
    return {"window_days": window, "groups": groups, "missing": missing}


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
            # Toteuma = nykytaso (paras tuoreen ikkunan sisällä) — sama luku
            # josta ennuste lähti, ei yksittäisen treenin arvio.
            actual_series = _level_series(pts, DEFAULT_WINDOW_DAYS)
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


# ---------- Älykäs lihaskuormitus: teholliset sarjat per alue + hermosto ----------

def _cns_set_points(rel: float, contrib_sum: float) -> float:
    """Hermostokuorma yhdestä sarjasta: intensiteetti suhteessa 1RM:ään ×
    liikkeen koko (moninivelinen raskas veto/kyykky rasittaa enemmän kuin
    penkki, eristävät eivät juuri lainkaan)."""
    if rel >= 0.925:
        base = 2.0
    elif rel >= 0.85:
        base = 1.2
    elif rel >= 0.775:
        base = 0.5
    else:
        return 0.0
    # Liikkeen "koko": kontribuutioiden summa ~1 (eristävä) ... ~4+ (maastaveto)
    size = max(0.7, min(1.6, contrib_sum / 2.5))
    return base * size


@router.get("/muscle-load")
def muscle_load(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Lihaskuormitus alueittain: 14 pv liukuva ikkuna viikkotahdiksi jaettuna.

    Jokainen liike jakaa kuormansa usealle alueelle osuuskertoimin (penkki ->
    rinta + ojentajat + etuolkapäät; kapea penkki -> pääosin ojentajat;
    taljavedot -> myös hauis + kyynärvarret; kyykyt -> pakarat/pohkeet mukana).

    IKKUNA: 14 pv (jaettuna kahdella = sarjaa/vk) eikä tiukka 7 pv, jotta arvio
    ei heilahda päivässä "liikaa treenattu" -> "vajaa" kun yksittäinen treeni
    putoaa ikkunan reunalta. Hermostokuorma (CNS) lasketaan silti 7 pv:ltä,
    koska hermosto palautuu päivissä — se SAA elää nopeasti.
    Ehdotukset vajaille alueille poimitaan ensisijaisesti omasta aktiivisesta
    ohjelmasta.
    """
    today = date.today()
    WINDOW = 14
    this_start = today - timedelta(days=WINDOW - 1)
    prev_start = today - timedelta(days=2 * WINDOW - 1)
    cns_start = today - timedelta(days=6)  # hermosto: aidosti akuutti 7 pv

    sessions = (db.query(models.WorkoutSession)
                .filter(models.WorkoutSession.profile_id == profile_id,
                        models.WorkoutSession.status == "completed")
                .all())
    if not sessions:
        return {"message": "Kirjaa treenejä, niin näet lihaskohtaisen kuormituksen.",
                "areas": [], "cns": None, "suggestions": []}

    # Per-alue teholliset sarjat & tonnage tälle ja edelliselle 14 pv jaksolle,
    # sekä viimeisin treenipäivä per alue (merkittävä kuorma, kerroin >= 0.5).
    eff_week = {a: 0.0 for a in engine.MUSCLE_AREAS}
    eff_prev = {a: 0.0 for a in engine.MUSCLE_AREAS}
    ton_week = {a: 0.0 for a in engine.MUSCLE_AREAS}
    last_by_area: dict[str, date] = {}
    workouts_week = 0
    workouts_prev = 0

    # Hermostokuorma: tarvitaan tuore 1RM-arvio raskaille moniniveliikkeille.
    one_rm_cache: dict[int, float | None] = {}

    def _current_1rm(ex_id: int) -> float | None:
        if ex_id not in one_rm_cache:
            rec = _records_for_exercise(
                _exercise_session_points(db, ex_id, profile_id), DEFAULT_WINDOW_DAYS)
            one_rm_cache[ex_id] = rec["current_1rm"] if rec else None
        return one_rm_cache[ex_id]

    cns_week = 0.0
    cns_prev = 0.0
    heavy_sets = 0
    very_heavy_sets = 0

    for s in sessions:
        in_week = s.session_date >= this_start
        in_prev = prev_start <= s.session_date < this_start
        in_cns = s.session_date >= cns_start
        in_cns_prev = (cns_start - timedelta(days=7)) <= s.session_date < cns_start
        if in_week:
            workouts_week += 1
        elif in_prev:
            workouts_prev += 1
        for we in s.exercises:
            ex = we.exercise
            if not ex:
                continue
            mapping = engine.exercise_muscle_map(ex.name, ex.category, ex.muscle_group)
            if not mapping:
                continue
            done = [st for st in we.sets if st.completed and st.reps > 0]
            if not done:
                continue
            n_sets = len(done)
            tonnage = sum(st.weight * st.reps for st in done)
            # Viimeksi treenattu (merkittävä osuus)
            for area, f in mapping.items():
                if f >= 0.5 and (area not in last_by_area or s.session_date > last_by_area[area]):
                    last_by_area[area] = s.session_date
            if not (in_week or in_prev):
                continue
            for area, f in mapping.items():
                if in_week:
                    eff_week[area] += n_sets * f
                    ton_week[area] += tonnage * f
                else:
                    eff_prev[area] += n_sets * f
            # Hermostokuorma vain isoista moninivelliikkeistä (kontribuutio-
            # summa >= 2), suhteessa tämänhetkiseen 1RM:ään. Akuutti 7 pv.
            contrib_sum = sum(mapping.values())
            if (in_cns or in_cns_prev) and contrib_sum >= 2.0 and any(st.weight > 0 for st in done):
                one_rm = _current_1rm(ex.id)
                if one_rm and one_rm > 0:
                    for st in done:
                        rel = st.weight / one_rm
                        pts = _cns_set_points(rel, contrib_sum)
                        if pts <= 0:
                            continue
                        if in_cns:
                            cns_week += pts
                            if rel >= 0.925:
                                very_heavy_sets += 1
                            elif rel >= 0.85:
                                heavy_sets += 1
                        else:
                            cns_prev += pts

    # ---- Aluekohtaiset statukset (datavaroitus jos ikkuna vajaa) ----
    # 14 pv summa jaetaan kahdella -> vertailukelpoinen sarjaa/vk-tahti.
    enough_data = workouts_week >= 3
    areas = []
    for a in engine.MUSCLE_AREAS:
        lo, hi = engine.MUSCLE_WEEKLY_TARGETS[a]
        sw = round(eff_week[a] / 2.0, 1)
        sp = round(eff_prev[a] / 2.0, 1)
        last = last_by_area.get(a)
        days_since = (today - last).days if last else None
        if sw >= hi * 1.15:
            status, note = "high", f"Reilusti yli suositushaarukan ({lo}–{hi} sarjaa/vk) — varmista palautuminen."
        elif sw >= lo:
            status, note = "ok", "Hyvällä alueella."
        elif sw > 0:
            if enough_data:
                status, note = "low", f"Alle suositushaarukan ({lo}–{hi} tehollista sarjaa/vk)."
            else:
                status, note = "info", "Dataa vielä vähän 14 pv jaksolla — liian aikaista arvioida."
        else:
            status = "none" if enough_data else "info"
            note = ("Ei kuormaa 14 pv jaksolla." if enough_data
                    else "Dataa vielä vähän 14 pv jaksolla — liian aikaista arvioida.")
        areas.append({
            "area": a, "effective_sets": sw, "prev_sets": sp,
            "tonnage": round(ton_week[a] / 2.0), "target_min": lo, "target_max": hi,
            "status": status, "days_since": days_since, "note": note,
        })
    order = {"low": 0, "none": 1, "high": 2, "ok": 3, "info": 4}
    areas_sorted = sorted(areas, key=lambda x: (order.get(x["status"], 9), -x["effective_sets"]))

    # ---- Hermosto: pisteet + peilaus palautumiseen ja tuntumaan ----
    cns_score = round(cns_week, 1)
    if cns_score >= 18:
        cns_verdict, cns_label = "very_high", "erittäin korkea"
    elif cns_score >= 11:
        cns_verdict, cns_label = "high", "korkea"
    elif cns_score >= 4:
        cns_verdict, cns_label = "moderate", "kohtalainen"
    else:
        cns_verdict, cns_label = "low", "kevyt"

    # Palautumis-cross-check: readiness + viime treenien tuntuma
    rd_score = None
    try:
        from .recovery import readiness as _rd
        rd = _rd(profile_id, db)
        if rd.get("has_data"):
            rd_score = rd.get("score")
    except Exception:  # noqa: BLE001
        pass
    recent_feels = [s.feeling for s in sorted(sessions, key=lambda x: x.session_date, reverse=True)[:5]
                    if s.feeling]
    neg_feels = sum(1 for f in recent_feels if f == "negative")

    cns_note = (f"Raskaita lähimaksimisarjoja ({heavy_sets + very_heavy_sets} kpl, joista "
                f"{very_heavy_sets} yli ~92 % maksimista) isoissa moninivelliikkeissä. ")
    if cns_verdict in ("high", "very_high"):
        if (rd_score is not None and rd_score < 60) or neg_feels >= 2:
            cns_verdict = "overreach"
            cns_note += ("Palautumismittarit/tuntuma vahvistavat rasituksen: hermosto ei ehdi palautua. "
                         "Pidä 1–2 kevyempää päivää tai pudota pääliikkeiden painoja ~10 % hetkeksi.")
        elif rd_score is not None and rd_score >= 75:
            cns_note += ("Hermostokuorma on korkea mutta palautumismittarit kunnossa — kestät tämän nyt. "
                         "Älä kuitenkaan pinoa montaa maksimipäivää peräkkäin.")
        else:
            cns_note += ("Useampi raskas pääliikepäivä viikossa verottaa hermostoa, vaikka eri "
                         "lihakset olisivat vuorossa. Jätä maksimiyritysten väliin 2–3 päivää.")
    elif cns_verdict == "moderate":
        cns_note += "Sopiva määrä raskasta työtä — voimakehitykselle hyvä taso."
    else:
        cns_note += ("Vähän lähimaksimityötä: hyvä palautusviikoksi, mutta voima kehittyy varmimmin "
                     "kun isoissa liikkeissä käydään säännöllisesti 85 %:n tuntumassa.")

    cns = {
        "score": cns_score, "prev_score": round(cns_prev, 1),
        "heavy_sets": heavy_sets, "very_heavy_sets": very_heavy_sets,
        "verdict": cns_verdict, "label": cns_label, "readiness_score": rd_score,
        "note": cns_note,
    }

    # ---- Ehdotukset vajaille alueille: ensin omasta aktiivisesta ohjelmasta ----
    suggestions = []
    # Suurin vaje ensin: suhde tavoitteen alarajaan (0 = ei kuormaa lainkaan)
    lacking_rows = sorted((a for a in areas_sorted if a["status"] in ("low", "none")),
                          key=lambda a: a["effective_sets"] / max(1, a["target_min"]))
    lacking = [a["area"] for a in lacking_rows][:3]
    if lacking:
        prog = (db.query(models.Program)
                .filter(models.Program.profile_id == profile_id,
                        models.Program.is_active.is_(True)).first())
        prog_exercises = []
        if prog:
            seen_ids = set()
            for d in prog.days:
                for pe in d.exercises:
                    if pe.exercise and pe.exercise.id not in seen_ids:
                        seen_ids.add(pe.exercise.id)
                        prog_exercises.append(pe.exercise)
        library = None
        for area in lacking:
            pick = None
            in_program = False
            best_f = 0.0
            for ex in prog_exercises:
                f = engine.exercise_muscle_map(ex.name, ex.category, ex.muscle_group).get(area, 0.0)
                if f >= 0.6 and f > best_f:
                    pick, best_f, in_program = ex, f, True
            if not pick:
                if library is None:
                    library = db.query(models.Exercise).all()
                for ex in library:
                    f = engine.exercise_muscle_map(ex.name, ex.category, ex.muscle_group).get(area, 0.0)
                    if f >= 0.8 and f > best_f:
                        pick, best_f = ex, f
            if pick:
                suggestions.append({
                    "area": area, "exercise_id": pick.id, "exercise_name": pick.name,
                    "in_program": in_program,
                    "note": (f"{pick.name} on jo ohjelmassasi — lisää siihen 1–2 sarjaa tai tee se useammin."
                             if in_program else
                             f"Lisää esim. {pick.name} (ei vielä ohjelmassasi) paikkaamaan aluetta."),
                })

    data_note = None
    if not enough_data:
        data_note = (f"Viimeisen 14 pv aikana vasta {workouts_week} treeni(ä) — vaje-arviot näytetään "
                     "vasta kun jaksolla on vähintään 3 treeniä, ettei hälytetä turhaan.")

    return {
        "window": {"days": WINDOW, "this_start": this_start.isoformat(),
                   "prev_start": prev_start.isoformat(), "ref_date": today.isoformat()},
        "workouts_week": workouts_week, "workouts_prev": workouts_prev,
        "areas": areas_sorted, "cns": cns, "suggestions": suggestions,
        "data_note": data_note,
    }
