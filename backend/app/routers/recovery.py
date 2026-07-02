"""Palautuminen ja kunto: kardiotapahtumat, aerobisen kunnon seuranta ja
valmiuspisteet (ylikuormituksen tunnistus uni/HRV/leposyke/kuorma-yhdistelmästä).

Kardio tuo poltetut kalorit myös päivän kokonaiskulutukseen (dieettipuoli).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db
from .stats import _latest_bodyweight, _session_tonnage

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


# METs eri lajeille kun kalorimäärää ei anneta (arvio painosta ja kestosta).
CARDIO_MET = {
    "juoksumatto": 9.0, "juoksu": 9.5, "crosstrainer": 7.0, "pyöräily": 7.5,
    "kävely": 3.8, "soutu": 7.0, "uinti": 7.0, "hyppynaru": 11.0, "muu": 6.0,
    # Lihashuolto / lämmittely (matala kulutus, mutta seurantaa varten)
    "lämmittely": 4.0, "venyttely": 2.5, "foam roll": 2.8, "liikkuvuus": 2.8,
}


# ---------- Kardiotapahtumat ----------
@router.get("/cardio", response_model=list[schemas.CardioSessionOut])
def list_cardio(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    q = db.query(models.CardioSession)
    if profile_id is not None:
        q = q.filter(models.CardioSession.profile_id == profile_id)
    return q.order_by(models.CardioSession.session_date.desc(), models.CardioSession.id.desc()).all()


@router.post("/cardio", response_model=schemas.CardioSessionOut, status_code=201)
def create_cardio(payload: schemas.CardioSessionCreate, profile_id: int = Query(...),
                  db: Session = Depends(get_db)):
    # Arvioi kcal jos ei annettu mutta paino + kesto tiedossa (MET-kaava)
    kcal = payload.kcal
    if not kcal and payload.duration_min:
        bw = _latest_bodyweight(db, profile_id)
        if bw:
            met = CARDIO_MET.get(payload.activity, 6.0)
            kcal = round(met * bw * (payload.duration_min / 60.0))
    session = models.CardioSession(
        profile_id=profile_id,
        session_date=payload.session_date or date.today(),
        activity=payload.activity,
        duration_min=payload.duration_min,
        kcal=kcal,
        avg_hr=payload.avg_hr,
        distance_km=payload.distance_km,
        notes=payload.notes,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/cardio/{cardio_id}", status_code=204)
def delete_cardio(cardio_id: int, db: Session = Depends(get_db)):
    c = db.get(models.CardioSession, cardio_id)
    if not c:
        raise HTTPException(status_code=404, detail="Kardiotapahtumaa ei löytynyt.")
    db.delete(c)
    db.commit()


@router.get("/cardio/trend")
def cardio_trend(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Aerobisen kunnon kehitys: per tapahtuma keskinopeus (km/h) ja tahti
    (min/km) sekä viikon kokonaiskesto ja -kalorit."""
    sessions = (db.query(models.CardioSession)
                .filter(models.CardioSession.profile_id == profile_id)
                .order_by(models.CardioSession.session_date).all())
    points = []
    for s in sessions:
        speed = pace = None
        if s.distance_km and s.duration_min and s.duration_min > 0:
            speed = round(s.distance_km / (s.duration_min / 60.0), 2)  # km/h
            pace = round(s.duration_min / s.distance_km, 2)            # min/km
        points.append({
            "date": s.session_date.isoformat(), "activity": s.activity,
            "duration_min": s.duration_min, "kcal": s.kcal, "avg_hr": s.avg_hr,
            "distance_km": s.distance_km, "speed_kmh": speed, "pace_min_km": pace,
        })
    # Viikon yhteenveto (viim. 7 pv)
    today = date.today()
    week = [s for s in sessions if 0 <= (today - s.session_date).days < 7]
    week_kcal = round(sum(s.kcal or 0 for s in week))
    week_min = round(sum(s.duration_min or 0 for s in week))
    return {"points": points, "week_kcal": week_kcal, "week_minutes": week_min, "week_sessions": len(week)}


@router.get("/readiness")
def readiness(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Valmiuspisteet ja ylikuormitusvaroitukset: HRV, leposyke, uni ja
    treenikuorman akuutti:krooninen-suhde (ACWR) yhdistettynä."""
    today = date.today()
    entries = (db.query(models.BodyEntry)
               .filter(models.BodyEntry.profile_id == profile_id)
               .order_by(models.BodyEntry.entry_date).all())

    def _stat(key, days_from, days_to):
        vals = [getattr(e, key) for e in entries
                if getattr(e, key) is not None
                and days_from <= (today - e.entry_date).days < days_to]
        return (sum(vals) / len(vals) if vals else None), len(vals)

    # Pitkän ajan vertailujakso (7–42 pv) vaimentaa yksittäiset heilahdukset
    hrv_recent, hrv_rn = _stat("hrv", 0, 7)
    hrv_base, hrv_bn = _stat("hrv", 7, 42)
    rhr_recent, rhr_rn = _stat("resting_hr", 0, 7)
    rhr_base, rhr_bn = _stat("resting_hr", 7, 42)
    sleep_recent, sleep_n = _stat("sleep_hours", 0, 7)

    # Treenikuorma: kokonaiskuorma (rauta) + kardiokalorit, ACWR
    workouts = (db.query(models.WorkoutSession)
                .filter(models.WorkoutSession.profile_id == profile_id,
                        models.WorkoutSession.status != "skipped").all())
    cardio = (db.query(models.CardioSession)
              .filter(models.CardioSession.profile_id == profile_id).all())

    def load_in(days_from, days_to):
        load = 0.0
        for s in workouts:
            if days_from <= (today - s.session_date).days < days_to:
                load += _session_tonnage(s)
        for c in cardio:
            if days_from <= (today - c.session_date).days < days_to:
                load += (c.kcal or 0) * 20  # kardio samaan mittakaavaan kuorman kanssa
        return load

    acute = load_in(0, 7)
    chronic4 = load_in(0, 28) / 4.0  # keskiviikko 4 viikolta
    acwr_info = engine.acwr_status(acute, chronic4)
    acwr = acwr_info["acwr"] if acwr_info else None

    # Treenifiilis (huono hymiö) viim. 14 pv — auttaa kun muuta dataa on vähän
    recent_feel = [s.feeling for s in workouts
                   if s.feeling and 0 <= (today - s.session_date).days < 14]
    neg_ratio = (sum(1 for f in recent_feel if f == "negative") / len(recent_feel)) if recent_feel else None

    # Ravinnon vajaus viim. 14 pv (vain jos tarpeeksi kirjattuja päiviä)
    nutrition_deficit, nutrition_n = _nutrition_deficit(db, profile_id, today)

    result = engine.readiness(
        hrv_recent, hrv_base, hrv_bn, hrv_rn,
        rhr_recent, rhr_base, rhr_bn, rhr_rn,
        sleep_recent, sleep_n, acwr,
        neg_feeling_ratio=neg_ratio, feeling_n=len(recent_feel),
        nutrition_deficit_pct=nutrition_deficit, nutrition_n=nutrition_n)
    result["acwr"] = acwr_info
    result["has_data"] = bool(result["factors"])

    # Deload-suositus: matalat valmiuspisteet TAI selvä kuormapiikki
    spike = acwr is not None and acwr > 1.5
    low = result["has_data"] and result["score"] < 55
    if spike or low:
        reason = ("kuormapiikki (ACWR " + str(acwr) + ")") if spike else "matalat palautumismittarit"
        result["deload_recommended"] = True
        result["deload_message"] = (
            f"Harkitse kevennysviikkoa — {reason}. Pudota kuormaa ~40–50 % tai sarjoja "
            "puoleen 5–7 päiväksi, pidä liikkeet samoina. Keho palautuu ja tulokset usein hyppäävät kevennyksen jälkeen.")
    else:
        result["deload_recommended"] = False
    return result


def _nutrition_deficit(db: Session, profile_id: int, today: date):
    """Keskimääräinen kalorivajaus (osuus tarpeesta) viim. 14 pv, ja montako
    päivää ruokaa on kirjattu. Vajaus vain jos dataa on tarpeeksi säännöllisesti."""
    logs = (db.query(models.FoodLog)
            .filter(models.FoodLog.profile_id == profile_id,
                    models.FoodLog.entry_date >= today - timedelta(days=13),
                    models.FoodLog.entry_date <= today).all())
    by_date: dict = {}
    for fl in logs:
        by_date[fl.entry_date] = by_date.get(fl.entry_date, 0.0) + (fl.food.kcal * fl.grams / 100.0)
    n = len(by_date)
    if n < 5:
        return None, n
    avg_intake = sum(by_date.values()) / n
    # Karkea tarve: paino * 30 (ei kriittinen tarkkuus, vain vajauksen suunta)
    bw = _latest_bodyweight(db, profile_id) or 75
    need = bw * 32
    deficit = max(0.0, (need - avg_intake) / need)
    return round(deficit, 2), n
